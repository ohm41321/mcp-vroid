"""macOS backend: Quartz window list, `screencapture`, CGEvent, AppKit.

VRoid Studio ships a native macOS build (bundle `net.pixiv.vroid.macosx`),
so there is no Steam/Proton/Wine layer here - but there is still no API, so
the loop is the same: capture, OCR, inject events.

    window discovery   CGWindowListCopyWindowInfo (owner = "VRoid Studio")
    frontmost app      owner of the frontmost on-screen window, from the same
                       list: NSWorkspace.frontmostApplication() only updates
                       on the main run loop, which the MCP server's worker
                       threads never spin
    focus / release    NSRunningApplication.activate (falls back to System Events)
    "fullscreen"       maximise to the screen's visible frame via System
                       Events. The Unity window offers no native fullscreen
                       (its zoom button is AXZoomButton, and AXFullScreen
                       just re-zooms it), so the title bar stays and the
                       reported geometry excludes it.
    capture            /usr/sbin/screencapture -l <window id> for the window
                       (works from any Space without changing focus),
                       -R x,y,w,h for screen regions; Retina-scaled. The
                       generic geometry fallback may activate VRoid.
    pointer / wheel    CGEventPost on the HID event tap
    keyboard           CGEvent keyboard events with the Unicode string set, so
                       any character types regardless of layout

Coordinate spaces: Core Graphics "global" points, origin top-left of the main
display, are the *layout* space. `screencapture` writes backing-store pixels,
so image px = points x backingScaleFactor (2.0 on Retina).

Permissions (System Settings > Privacy & Security) for the process that
launches the server - Terminal, or the MCP client app:
    Accessibility     posting CGEvents, System Events UI scripting
    Screen Recording  screencapture, and window *titles* in the window list
`helpers()` reports both; input refuses to run without Accessibility rather
than have every event silently dropped.
"""
from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

from .base import Output, Window

try:  # the pyobjc frameworks are only installed on macOS
    import Quartz
    from AppKit import (NSApplicationActivateIgnoringOtherApps,
                        NSRunningApplication, NSScreen)
except ImportError:  # pragma: no cover - exercised on Linux only
    Quartz = None

BACKEND = "macos"
BUNDLE_ID = "net.pixiv.vroid.macosx"
APP_NAME = "VRoid Studio"
OWNER_HINTS = ("vroid studio", "vroidstudio")
TITLE_HINTS = ("vroid",)

WORKSPACE = BUNDLE_ID   # "where VRoid lives": VRoid frontmost, maximised
PRIMARY_MOD = "cmd"     # the app's shortcuts use Command on macOS

# NSSavePanel: a centred VRoid-owned window titled "Save" (880x767 pt here,
# user-resizable) with the "Save As:" field at its top and the Save button
# at its bottom, so the search region is the middle band of a screen
# capture, full height.
SAVE_DIALOG_REGION = (0.15, 0.0, 0.85, 1.0)
SAVE_DIALOG_FIELD_LABEL = "Save As"
SAVE_DIALOG_TITLES = ("export", "save as", "save", "export as vrm")

_MIN_MAIN_WINDOW = 200   # points; Unity keeps a few tiny helper windows around
TITLEBAR_PT = 28         # standard NSWindow title bar; kCGWindowBounds includes it


def _need_quartz() -> None:
    if Quartz is None:
        raise RuntimeError(
            "pyobjc is not installed - `uv sync` on macOS pulls "
            "pyobjc-framework-Quartz; this backend cannot run without it")


# --- permissions ------------------------------------------------------------

def _cf(name: str):
    return ctypes.cdll.LoadLibrary(
        f"/System/Library/Frameworks/{name}.framework/{name}")


def accessibility_trusted() -> bool:
    try:
        lib = _cf("ApplicationServices")
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return bool(lib.AXIsProcessTrusted())
    except (OSError, AttributeError):  # pragma: no cover
        return False


def screen_recording_allowed(request: bool = False) -> bool:
    try:
        lib = _cf("CoreGraphics")
        lib.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        ok = bool(lib.CGPreflightScreenCaptureAccess())
        if not ok and request:
            lib.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
            ok = bool(lib.CGRequestScreenCaptureAccess())
        return ok
    except (OSError, AttributeError):  # pragma: no cover
        return False


def _require_trusted() -> None:
    if not accessibility_trusted():
        raise RuntimeError(
            "macOS refuses synthetic input: grant Accessibility to the app "
            "that launched this server (Terminal / your MCP client) in "
            "System Settings > Privacy & Security > Accessibility, then "
            "restart it")


# --- windows ----------------------------------------------------------------

# Neither NSWorkspace.frontmostApplication() nor NSRunningApplication
# .isActive() can be trusted here: both are refreshed by the *main* run
# loop, and the MCP server runs tools on worker threads, so they keep
# reporting whatever was active at import (verified: a worker never saw
# VRoid being activated, and isActive() stayed True after switching away).
# Two live sources instead, and the guard wants them to agree:

def _ax_front_pid() -> int:
    """PID of the app that owns keyboard focus, from the Accessibility
    server (kAXFocusedApplicationAttribute). -1 when unavailable: no
    Accessibility permission, or kAXErrorCannotComplete (-25204), which is
    the answer whenever the focused app is VRoid itself (Unity's AX server
    does not respond) - so this can only veto, never confirm."""
    try:
        AS, CF = _cf("ApplicationServices"), _cf("CoreFoundation")
        CF.CFStringCreateWithCString.restype = ctypes.c_void_p
        CF.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        CF.CFRelease.argtypes = [ctypes.c_void_p]
        AS.AXUIElementCreateSystemWide.restype = ctypes.c_void_p
        AS.AXUIElementCopyAttributeValue.restype = ctypes.c_int
        AS.AXUIElementCopyAttributeValue.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        AS.AXUIElementGetPid.restype = ctypes.c_int
        AS.AXUIElementGetPid.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        system = AS.AXUIElementCreateSystemWide()
        attr = CF.CFStringCreateWithCString(
            None, b"AXFocusedApplication", 0x08000100)   # kCFStringEncodingUTF8
        app = ctypes.c_void_p()
        err = AS.AXUIElementCopyAttributeValue(system, attr, ctypes.byref(app))
        CF.CFRelease(attr)
        pid = ctypes.c_int(-1)
        if err == 0 and app.value:
            AS.AXUIElementGetPid(app.value, ctypes.byref(pid))
            CF.CFRelease(app.value)
        CF.CFRelease(system)
        return pid.value if err == 0 else -1
    except (OSError, AttributeError):  # pragma: no cover
        return -1


def _ws_front_pid() -> int:
    """PID of the app owning the frontmost normal window, from the window
    server: the on-screen list is live and ordered front to back. That is
    where pointer events land, but not necessarily where keys go (an active
    app with no windows leaves someone else's window in front)."""
    _need_quartz()
    infos = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID) or []
    for i in infos:
        if int(i.get("kCGWindowLayer", 0)) == 0:
            return int(i.get("kCGWindowOwnerPID", -1))
    return -1


def _front_pid() -> int:
    pid = _ax_front_pid()
    return pid if pid > 0 else _ws_front_pid()


def _frontmost():
    pid = _front_pid()
    if pid <= 0:
        return None
    return NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)


def _frontmost_id() -> str:
    app = _frontmost()
    if app is None:
        return ""
    return str(app.bundleIdentifier() or app.localizedName() or "")


def _vroid_pids() -> set[int]:
    _need_quartz()
    return {int(a.processIdentifier()) for a in
            NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)}


def _window_infos() -> list[dict]:
    """Every window on every Space. VRoid usually sits in its own fullscreen
    Space, which an on-screen-only listing would hide whenever another app is
    frontmost; `kCGWindowIsOnscreen` says which ones are visible right now."""
    _need_quartz()
    opts = (Quartz.kCGWindowListOptionAll
            | Quartz.kCGWindowListExcludeDesktopElements)
    return list(Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID) or [])


def _onscreen(info: dict) -> bool:
    return bool(info.get("kCGWindowIsOnscreen", False))


def _is_vroid_owner(info: dict, pids: set[int]) -> bool:
    if int(info.get("kCGWindowOwnerPID", -1)) in pids:
        return True
    owner = str(info.get("kCGWindowOwnerName") or "").lower()
    return any(h in owner for h in OWNER_HINTS)


def _mk(info: dict, front_pid: int, out: Output | None = None) -> Window:
    b = info["kCGWindowBounds"]
    x, y, w, h = int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])
    out = out or primary_output()
    full = _is_fullscreen(x, y, w, h, out)
    if h > TITLEBAR_PT and not _is_native_fullscreen(x, y, w, h, out):
        # kCGWindowBounds includes the title bar (unless the window is in
        # genuine fullscreen, which this app never is): report the *content*
        # rectangle, so y = 0 of a capture is the tab strip, as on Hyprland.
        y, h = y + TITLEBAR_PT, h - TITLEBAR_PT
    return Window(
        address=str(info["kCGWindowNumber"]),
        cls=str(info.get("kCGWindowOwnerName") or ""),
        title=str(info.get("kCGWindowName") or ""),
        x=x, y=y, w=w, h=h,
        workspace="active-space" if _onscreen(info) else "other-space",
        focused=int(info.get("kCGWindowOwnerPID", -1)) == front_pid,
        fullscreen=full,
    )


def _top_inset() -> int:
    """Height of the camera-housing strip on notched MacBooks (0 elsewhere):
    a fullscreen window stops below it."""
    try:
        return int(NSScreen.screens()[0].safeAreaInsets().top)
    except Exception:  # pragma: no cover - pre-12.0 AppKit
        return 0


def _visible_frame() -> tuple[int, int, int, int]:
    """The area a window may occupy (below the menu bar), top-left origin."""
    sc = NSScreen.screens()[0]
    f, v = sc.frame(), sc.visibleFrame()
    return (int(v.origin.x), int(f.size.height - (v.origin.y + v.size.height)),
            int(v.size.width), int(v.size.height))


def _is_native_fullscreen(x: int, y: int, w: int, h: int, out: Output) -> bool:
    """Whole display, with or without the notch inset (no title bar)."""
    if (x, w) != (out.x, out.w):
        return False
    inset = _top_inset()
    return (y, h) in ((out.y, out.h), (out.y + inset, out.h - inset))


def _is_fullscreen(x: int, y: int, w: int, h: int, out: Output) -> bool:
    """True for our driving geometry: maximised to the visible frame (what
    fullscreen() produces), or genuinely fullscreen - whichever of those the
    window happens to be in."""
    if _is_native_fullscreen(x, y, w, h, out):
        return True
    return (x, y, w, h) == _visible_frame()


def list_windows() -> list[Window]:
    out = primary_output()
    fp = _front_pid()
    return [_mk(i, fp, out) for i in _window_infos()
            if int(i.get("kCGWindowLayer", 0)) == 0 and _onscreen(i)]


def _vroid_infos() -> list[dict]:
    pids = _vroid_pids()
    return [i for i in _window_infos()
            if int(i.get("kCGWindowLayer", 0)) == 0 and _is_vroid_owner(i, pids)]


def _area(info: dict) -> float:
    b = info["kCGWindowBounds"]
    return float(b["Width"] * b["Height"])


def find_window() -> Window | None:
    """The VRoid Studio main window, on any Space. Never matches another app
    (a browser tab called "VRoid" has a different owner). Unity also keeps a
    hidden 500x500 helper and a few 33 px strips around; they never carry a
    title, so a titled window wins (on-screen first, then the largest).
    Titles need Screen Recording permission; without them fall back to the
    largest window of at least _MIN_MAIN_WINDOW pt. The title rule matters
    because Stage Manager reports a window parked in its strip at thumbnail
    bounds (158x186 pt was seen), smaller than the helper."""
    infos = _vroid_infos()
    titled = [i for i in infos if str(i.get("kCGWindowName") or "").strip()]
    if titled:
        best = max(titled, key=lambda i: (_onscreen(i), _area(i)))
    else:
        big = [i for i in infos
               if i["kCGWindowBounds"]["Width"] >= _MIN_MAIN_WINDOW
               and i["kCGWindowBounds"]["Height"] >= _MIN_MAIN_WINDOW]
        if not big:
            return None
        best = max(big, key=_area)
    return _mk(best, _front_pid())


def find_dialog_window() -> Window | None:
    """The NSSavePanel: a second VRoid-owned window that is on screen
    and smaller than the main one. Titles are only visible with Screen
    Recording permission, so fall back to "any other sizeable VRoid window
    that is actually visible" - which excludes Unity's hidden 500x500 helper."""
    main = find_window()
    fp = _front_pid()
    others = []
    for i in _vroid_infos():
        if not _onscreen(i):
            continue
        w = _mk(i, fp)
        if main and w.address == main.address:
            continue
        if w.title.strip().lower() in SAVE_DIALOG_TITLES:
            return w
        if w.w >= _MIN_MAIN_WINDOW and w.h >= 100:
            others.append(w)
    return others[0] if others else None


def focused_desc() -> str:
    app = _frontmost()
    if app is None:
        return "unknown"
    desc = f"app={app.localizedName()!r} bundle={app.bundleIdentifier()!r}"
    win = find_window()
    if _is_vroid_app(app) and win is not None and win.workspace != "active-space":
        desc += " (main window off screen: minimised or on another Space)"
    return desc


def _is_vroid_app(app) -> bool:
    if app is None:
        return False
    bid = str(app.bundleIdentifier() or "")
    name = str(app.localizedName() or "").lower()
    return bid == BUNDLE_ID or any(h in name for h in OWNER_HINTS)


def is_vroid_focused() -> bool:
    """VRoid owns keyboard focus (Accessibility), owns the frontmost window
    (window server), *and* its main window is on the current Space (not
    minimised/hidden). Keys follow the active app and pointer events land
    on whatever is under the pointer, so both sources must agree before
    anything is injected; the on-screen check stops clicks going through
    to the desktop or another app occupying VRoid's rectangle."""
    pids = _vroid_pids()
    ax = _ax_front_pid()
    if ax > 0 and ax not in pids:
        return False
    ws = _ws_front_pid()
    if ws not in pids and not _is_vroid_app(
            NSRunningApplication.runningApplicationWithProcessIdentifier_(ws)
            if ws > 0 else None):
        return False
    win = find_window()
    return win is not None and win.workspace == "active-space"


def launch() -> None:
    subprocess.Popen(["open", "-b", BUNDLE_ID],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def kill() -> None:
    _need_quartz()
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    for a in apps:
        a.terminate()
    deadline = time.time() + 5
    while time.time() < deadline and any(not a.isTerminated() for a in apps):
        time.sleep(0.3)
    for a in apps:
        if not a.isTerminated():
            a.forceTerminate()


# --- "workspace" juggling: which app is frontmost --------------------------

def active_workspace() -> str:
    return _frontmost_id()


def park(win: Window, workspace=WORKSPACE) -> None:
    """No-op: there is no workspace to move to; focus() brings the app
    (and whichever Space its window is on) to the front."""


def enter(workspace=WORKSPACE) -> str:
    """Bring VRoid to the front; returns the bundle id of the app that was."""
    prev = _frontmost_id()
    if prev != BUNDLE_ID:
        focus()
    return prev


def leave(prev: str) -> None:
    if not prev or prev == BUNDLE_ID or prev == _frontmost_id():
        return
    _need_quartz()
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(prev)
    if apps:
        apps[0].activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.4)


def dismiss_screensaver() -> bool:
    return False


def notify(msg: str, ms: int = 3000, color: str = "") -> None:
    safe = msg.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(["osascript", "-e",
                    f'display notification "{safe}" with title "mcp-vroid"'],
                   capture_output=True)


def _osascript(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["osascript", "-e", script],
                          capture_output=True, text=True)


def _system_events(body: str) -> subprocess.CompletedProcess:
    """UI-script the VRoid process via System Events (needs Accessibility)."""
    return _osascript(
        'tell application "System Events"\n'
        f'  tell (first process whose bundle identifier is "{BUNDLE_ID}")\n'
        f'    {body}\n'
        '  end tell\n'
        'end tell')


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    _need_quartz()
    for a in NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID):
        a.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    deadline = time.time() + 2.0
    while time.time() < deadline and not is_vroid_focused():
        time.sleep(0.1)
    if not is_vroid_focused():
        # macOS 14+ may refuse cross-app activation from a background process;
        # System Events can still do it (with Accessibility granted).
        _system_events("set frontmost to true")
        time.sleep(0.4)
    win = _settled(win)
    if win.workspace != "active-space":
        # activation does not restore a minimised window
        _system_events('set value of attribute "AXMinimized" of window 1 to false')
        win = _settled(win)
    if win.workspace != "active-space":
        raise RuntimeError(
            "VRoid Studio's window is not on screen (minimised or hidden); "
            "restore it by hand")
    return win


def _settled(win: Window, timeout: float = 3.0) -> Window:
    """Wait for the window to be on screen with stable bounds: switching to
    its Space slides it in, and bounds read mid-animation are offset."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        time.sleep(0.25)
        w = find_window()
        if w is None:
            continue
        if w.workspace == "active-space" and last is not None \
                and w.geometry == last.geometry:
            return w
        last = w
    return find_window() or win


def fullscreen(win: Window | None = None) -> Window:
    """Maximise the window to the screen's visible frame, so its geometry -
    and every coordinate read off a capture - is stable across runs.

    Not native fullscreen: the Unity window does not offer it (no
    AXFullScreenButton; setting AXFullScreen merely re-zooms the window).
    The title bar therefore stays, and `_mk` trims it from the geometry.
    Needs Accessibility; without it the window is driven where it is.
    """
    win = focus(win)
    if not win.fullscreen:
        vx, vy, vw, vh = _visible_frame()
        r = _system_events(f"set position of window 1 to {{{vx}, {vy}}}")
        if r.returncode == 0:
            r = _system_events(f"set size of window 1 to {{{vw}, {vh}}}")
        if r.returncode != 0:
            print(f"mcp-vroid: could not maximise VRoid via System Events "
                  f"({r.stderr.strip()}); driving it as-is", file=sys.stderr)
            return win
        deadline = time.time() + 3.0
        while time.time() < deadline:
            time.sleep(0.25)
            w = find_window()
            if w and w.fullscreen:
                break
        time.sleep(0.5)  # let the app relayout
    return find_window() or win


def ui_scale(shot_scale: float) -> float:
    """Image px per VRoid UI point. The native build draws its UI at the
    display's backing scale, which is exactly a capture's px-per-point."""
    return shot_scale


# --- output + capture -------------------------------------------------------

def primary_output() -> Output:
    _need_quartz()
    screen = NSScreen.screens()[0]          # origin (0, 0) in global coords
    f = screen.frame()
    return Output(0, 0, int(f.size.width), int(f.size.height),
                  float(screen.backingScaleFactor()))


def capture_region(x: int, y: int, w: int, h: int, path: Path) -> None:
    if not screen_recording_allowed(request=True):
        raise RuntimeError(
            "macOS Screen Recording permission missing: without it "
            "screencapture returns the wallpaper. Grant it to the app that "
            "launched this server in System Settings > Privacy & Security > "
            "Screen Recording, then restart it")
    subprocess.run(
        ["screencapture", "-x", "-o", "-t", "png", "-R", f"{x},{y},{w},{h}",
         str(path)],
        check=True, capture_output=True,
    )


def capture_window(win: Window, path: Path) -> bool:
    """Capture the window by id: works whatever Space it is on and whatever
    covers it, so read-only tools never have to steal focus. The image has
    the title bar (trimmed here to match `find_window()`'s geometry) and,
    without -o, a shadow."""
    if not screen_recording_allowed(request=True):
        raise RuntimeError(
            "macOS Screen Recording permission missing: without it "
            "screencapture returns the wallpaper. Grant it to the app that "
            "launched this server in System Settings > Privacy & Security > "
            "Screen Recording, then restart it")
    subprocess.run(
        ["screencapture", "-x", "-o", "-t", "png", "-l", str(win.address),
         str(path)],
        check=True, capture_output=True,
    )
    img = Image.open(path).convert("RGB")
    scale = primary_output().scale
    if img.width != int(round(win.w * scale)):
        # The bounds are not the window's real size - Stage Manager reports
        # a window parked in its strip at thumbnail size, and bounds read
        # mid-animation are off. Let the caller focus and re-measure.
        path.unlink(missing_ok=True)
        return False
    want_h = int(round(win.h * scale))
    if img.height > want_h:
        img = img.crop((0, img.height - want_h, img.width, img.height))
    img.save(path)
    return True


# --- pointer + wheel: CGEvent -----------------------------------------------

_HELD: str | None = None            # button currently held (drags)
_POS: tuple[float, float] | None = None


def _btn(name: str):
    Q = Quartz
    return {
        "left": (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp,
                 Q.kCGEventLeftMouseDragged, Q.kCGMouseButtonLeft),
        "right": (Q.kCGEventRightMouseDown, Q.kCGEventRightMouseUp,
                  Q.kCGEventRightMouseDragged, Q.kCGMouseButtonRight),
        "middle": (Q.kCGEventOtherMouseDown, Q.kCGEventOtherMouseUp,
                   Q.kCGEventOtherMouseDragged, Q.kCGMouseButtonCenter),
    }[name]


def _post(ev) -> None:
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def cursor_pos() -> tuple[float, float] | None:
    _need_quartz()
    loc = Quartz.CGEventGetLocation(Quartz.CGEventCreate(None))
    return float(loc.x), float(loc.y)


def _mouse(kind, pos, button, click_state: int = 1) -> None:
    ev = Quartz.CGEventCreateMouseEvent(None, kind, pos, button)
    Quartz.CGEventSetIntegerValueField(ev, Quartz.kCGMouseEventClickState,
                                       click_state)
    _post(ev)


def _here() -> tuple[float, float]:
    global _POS
    if _POS is None:
        _POS = cursor_pos() or (0.0, 0.0)
    return _POS


def run_pointer(ops, extent: tuple[int, int]) -> None:
    global _HELD, _POS
    _need_quartz()
    _require_trusted()
    for op in ops:
        kind = op[0]
        if kind == "move":
            _POS = (float(op[1]), float(op[2]))
            if _HELD:
                _, _, dragged, b = _btn(_HELD)
                _mouse(dragged, _POS, b)
            else:
                _mouse(Quartz.kCGEventMouseMoved, _POS, Quartz.kCGMouseButtonLeft)
        elif kind == "sleep":
            time.sleep(op[1] / 1000.0)
        elif kind == "down":
            down, _, _, b = _btn(op[1])
            _mouse(down, _here(), b)
            _HELD = op[1]
        elif kind == "up":
            _, up, _, b = _btn(op[1])
            _mouse(up, _here(), b)
            _HELD = None
        elif kind == "click":
            down, up, _, b = _btn(op[1])
            n = op[2] if len(op) > 2 else 1
            for i in range(1, n + 1):
                if i > 1:
                    time.sleep(0.08)
                _mouse(down, _here(), b, click_state=i)
                time.sleep(0.03)
                _mouse(up, _here(), b, click_state=i)
        elif kind == "scroll":
            scroll(int(op[1]))
        else:
            raise ValueError(f"unknown pointer op {op!r}")


def scroll(ticks: int, horizontal: bool = False) -> None:
    """Wheel notches at the current pointer. Positive = down / right.

    Core Graphics counts positive as up/left, hence the sign flip.
    """
    _need_quartz()
    _require_trusted()
    step = -1 if ticks > 0 else 1
    for _ in range(abs(ticks)):
        if horizontal:
            ev = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitLine, 2, 0, step)
        else:
            ev = Quartz.CGEventCreateScrollWheelEvent(
                None, Quartz.kCGScrollEventUnitLine, 1, step)
        _post(ev)
        time.sleep(0.05)


# --- keyboard: CGEvent ------------------------------------------------------
#
# Virtual key codes are the ANSI-US positions from Carbon's Events.h. The
# app's shortcuts (Cmd+S, Cmd+Shift+S, Cmd+A) are looked up by *position*, so
# this is what a Unity player wants; literal text additionally carries the
# Unicode string, so it lands correctly on any input source.

KEYCODES = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "1": 0x12,
    "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E,
    "o": 0x1F, "u": 0x20, "[": 0x21, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B,
    "/": 0x2C, "n": 0x2D, "m": 0x2E, ".": 0x2F, "`": 0x32,
    "return": 0x24, "tab": 0x30, "space": 0x31, "backspace": 0x33,
    "escape": 0x35, "delete": 0x75, "home": 0x73, "end": 0x77,
    "pageup": 0x74, "pagedown": 0x79, "left": 0x7B, "right": 0x7C,
    "down": 0x7D, "up": 0x7E,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
    "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
}

# X11 keysym names the flows and the Hyprland backend use -> our names.
KEY_ALIASES = {
    "enter": "return", "esc": "escape", "back_space": "backspace",
    "bs": "backspace", "prior": "pageup", "next": "pagedown", "del": "delete",
    "forwarddelete": "delete", " ": "space",
}

# Shifted ANSI-US characters -> the unshifted key they sit on.
SHIFTED = dict(zip('~!@#$%^&*()_+{}|:"<>?', '`1234567890-=[]\\;\',./'))

# CGEventFlags masks (CGEventTypes.h) - literals so the tables import anywhere.
FLAG_SHIFT, FLAG_CTRL, FLAG_ALT, FLAG_CMD = 1 << 17, 1 << 18, 1 << 19, 1 << 20
MODIFIERS = {          # name -> (virtual key code, event flag)
    "cmd": (0x37, FLAG_CMD), "command": (0x37, FLAG_CMD),
    "super": (0x37, FLAG_CMD), "meta": (0x37, FLAG_CMD),
    "shift": (0x38, FLAG_SHIFT),
    "alt": (0x3A, FLAG_ALT), "option": (0x3A, FLAG_ALT),
    "ctrl": (0x3B, FLAG_CTRL), "control": (0x3B, FLAG_CTRL),
}


def keystroke(name: str) -> tuple[int, bool]:
    """(virtual key code, needs_shift) for a key name or single character.

    Raises ValueError for anything not on the ANSI map; `type_text` falls
    back to Unicode events for those, `key` refuses like the X11 path does.
    """
    if len(name) == 1:
        n = KEY_ALIASES.get(name, name)          # " " -> space; case matters
    else:
        n = KEY_ALIASES.get(name.lower(), name.lower())
    if len(n) == 1:
        if n in SHIFTED:
            return KEYCODES[SHIFTED[n]], True
        if n.isupper() and n.lower() in KEYCODES:
            return KEYCODES[n.lower()], True
        if n in KEYCODES:
            return KEYCODES[n], False
        raise ValueError(f"no macOS key code for {name!r}")
    if n in KEYCODES:
        return KEYCODES[n], False
    if n in MODIFIERS:
        return MODIFIERS[n][0], False
    raise ValueError(f"no macOS key code for {name!r}")


def mod_flags(mods) -> tuple[list[int], int]:
    """([modifier key codes], combined CGEventFlags) for a list of names."""
    codes, flags = [], 0
    for m in mods or ():
        try:
            code, flag = MODIFIERS[m.lower()]
        except KeyError:
            raise ValueError(f"unknown modifier {m!r}") from None
        codes.append(code)
        flags |= flag
    return codes, flags


def _key_event(code: int, down: bool, flags: int = 0, text: str | None = None):
    ev = Quartz.CGEventCreateKeyboardEvent(None, code, down)
    if flags:
        Quartz.CGEventSetFlags(ev, flags)
    if text is not None:
        # Quartz counts UTF-16 code units, including both halves of a
        # surrogate pair for emoji and other non-BMP characters.
        Quartz.CGEventKeyboardSetUnicodeString(
            ev, len(text.encode("utf-16-le")) // 2, text)
    return ev


def _mod_event(code: int, flags: int):
    """A modifier press/release. Hardware modifiers arrive as FlagsChanged
    events, not KeyDown/KeyUp, and Unity tracks Cmd/Shift from those: with
    plain key events for the modifiers Cmd+Shift+S did nothing in VRoid,
    while AppKit widgets (which read the flags on the key event) were fine."""
    ev = Quartz.CGEventCreateKeyboardEvent(None, code, True)
    Quartz.CGEventSetType(ev, Quartz.kCGEventFlagsChanged)
    Quartz.CGEventSetFlags(ev, flags)
    return ev


def _tap(code: int, mod_codes: list[int], flags: int, text: str | None = None,
         hold: float = 0.02) -> None:
    held = 0
    for mc, mf in zip(mod_codes, _flags_of(mod_codes)):
        held |= mf
        _post(_mod_event(mc, held))
        time.sleep(0.02)
    _post(_key_event(code, True, flags, text))
    time.sleep(hold)
    _post(_key_event(code, False, flags, text))
    for mc, mf in reversed(list(zip(mod_codes, _flags_of(mod_codes)))):
        held &= ~mf
        time.sleep(0.02)
        _post(_mod_event(mc, held))


def _flags_of(mod_codes: list[int]) -> list[int]:
    by_code = {code: flag for code, flag in MODIFIERS.values()}
    return [by_code[c] for c in mod_codes]


def type_text(text: str, delay_ms: int = 22) -> None:
    """Type a literal string into the focused widget."""
    _need_quartz()
    _require_trusted()
    for ch in text:
        if ch == "\n":
            key("return")
            continue
        try:
            code, need_shift = keystroke(ch)
        except ValueError:
            code, need_shift = 0, False        # Unicode-only event
        flags = FLAG_SHIFT if need_shift else 0
        mods = [MODIFIERS["shift"][0]] if need_shift else []
        _tap(code, mods, flags, text=ch)
        time.sleep(delay_ms / 1000.0)
    time.sleep(0.15)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a named key (Return, Escape, BackSpace, a, ...) with modifiers."""
    _need_quartz()
    _require_trusted()
    code, need_shift = keystroke(name)
    mod_codes, flags = mod_flags(mods)
    if need_shift and MODIFIERS["shift"][0] not in mod_codes:
        mod_codes.append(MODIFIERS["shift"][0])
        flags |= FLAG_SHIFT
    for _ in range(times):
        _tap(code, mod_codes, flags)
        time.sleep(0.06)
    time.sleep(0.12)


def input_focus_ok() -> bool:
    return is_vroid_focused()


# --- save dialog ------------------------------------------------------------

def app_path(p: Path) -> str:
    return str(Path(p).resolve())


def save_dialog_enter_path(out_path: Path) -> None:
    """NSSavePanel: Cmd+Shift+G opens "Go to the folder", which takes the
    directory; back in the panel the name field is focused again, so
    select-all and type the file name."""
    key("g", mods=["cmd", "shift"])
    time.sleep(0.7)
    key("a", mods=["cmd"])
    type_text(str(Path(out_path).resolve().parent))
    time.sleep(0.4)
    key("return")
    time.sleep(1.0)
    key("a", mods=["cmd"])
    type_text(out_path.name)
    time.sleep(0.3)


# --- status -----------------------------------------------------------------

def helpers() -> dict:
    return {
        "pyobjc": Quartz is not None,
        "screencapture": bool(shutil.which("screencapture")),
        "tesseract": bool(shutil.which("tesseract")),
        "accessibility": accessibility_trusted(),
        "screen_recording": screen_recording_allowed(),
        "app_installed": subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{BUNDLE_ID}'"],
            capture_output=True, text=True).stdout.strip() != ""
            if shutil.which("mdfind") else None,
    }
