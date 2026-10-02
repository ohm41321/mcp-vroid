"""Hyprland/Wayland backend: hyprctl, grim, native/vpointer and X11 XTEST.

This is the original driver, verbatim where possible. Window management is
Hyprland-specific (hyprctl + its Lua dispatch API); capture and the pointer
work on any wlroots compositor; keyboard and wheel go through Xwayland.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from ..paths import VPOINTER
from .base import Output, Window

BACKEND = "hyprland"
STEAM_APPID = "1486350"

# VRoid runs under Proton, so it is an XWayland window. Hyprland reports
#   class = "steam_app_1486350"   title = "VRoid Studio 2.14.0"
CLASS_HINTS = ("vroidstudio", "vroid studio", f"steam_app_{STEAM_APPID}")
TITLE_HINTS = ("vroid",)

WORKSPACE = 9          # dedicated workspace we drive VRoid on
PRIMARY_MOD = "ctrl"   # the modifier the app's shortcuts use (Ctrl+S, ...)

# Wine's save dialog: where its "File name:" field sits in a whole-screen
# capture (fractions), and the label to click as a fallback.
SAVE_DIALOG_REGION = (0.0, 0.0, 0.4, 0.3)
SAVE_DIALOG_FIELD_LABEL = "name"
SAVE_DIALOG_TITLES = ("export", "save as", "save")


def hyprctl(*args: str) -> str:
    return subprocess.run(
        ["hyprctl", *args], capture_output=True, text=True, check=True
    ).stdout


def hyprctl_json(*args: str):
    return json.loads(hyprctl("-j", *args))


def dispatch(lua: str) -> str:
    """Hyprland >= 0.55 takes Lua dispatchers, e.g.
    hyprctl dispatch 'hl.dsp.window.close()'.
    """
    out = hyprctl("dispatch", lua)
    if out.strip().startswith("error"):
        raise RuntimeError(f"hyprctl dispatch failed: {lua}\n{out}")
    return out


def _win_expr(win: Window | None) -> str:
    return f"hl.get_window('address:{win.address}')" if win else "nil"


def notify(msg: str, ms: int = 3000, color: str = "rgb(88aaff)") -> None:
    subprocess.run(["hyprctl", "notify", "1", str(ms), color, msg],
                   capture_output=True)


# --- windows ----------------------------------------------------------------

def _clients() -> list[dict]:
    return hyprctl_json("clients")


def _mk(c: dict) -> Window:
    return Window(
        address=c["address"], cls=c.get("class", ""), title=c.get("title", ""),
        x=c["at"][0], y=c["at"][1], w=c["size"][0], h=c["size"][1],
        workspace=c["workspace"]["id"], focused=c.get("focusHistoryID", -1) == 0,
        fullscreen=bool(c.get("fullscreen", 0)),
    )


def _is_vroid(cls: str, title: str) -> bool:
    cls, title = cls.lower(), title.lower()
    return any(h in cls for h in CLASS_HINTS) or title.startswith("vroid studio")


def list_windows() -> list[Window]:
    return [_mk(c) for c in _clients()]


def find_window() -> Window | None:
    """Return the VRoid Studio window, or None. Never matches anything else."""
    for c in _clients():
        cls = (c.get("class") or "").lower()
        title = (c.get("title") or "").lower()
        if any(h in cls for h in CLASS_HINTS) or any(h in title for h in TITLE_HINTS):
            # Guard against e.g. a browser tab named "VRoid": require the
            # window class to look like the game, or an exact-ish title.
            if _is_vroid(cls, title):
                return _mk(c)
    return None


def find_dialog_window() -> Window | None:
    """Wine's Save/Export dialog is a separate top-level window."""
    for c in _clients():
        if (c.get("title") or "").strip().lower() in SAVE_DIALOG_TITLES:
            return _mk(c)
    return None


def focused_desc() -> str:
    try:
        a = hyprctl_json("activewindow")
    except subprocess.CalledProcessError:
        return "unknown"
    return f"class={a.get('class')!r} title={a.get('title')!r}"


def is_vroid_focused() -> bool:
    try:
        a = hyprctl_json("activewindow")
    except subprocess.CalledProcessError:
        return False
    if not a or "class" not in a:
        return False
    return _is_vroid(a.get("class") or "", a.get("title") or "")


def launch() -> None:
    subprocess.Popen(
        ["steam", f"steam://rungameid/{STEAM_APPID}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def kill() -> None:
    subprocess.run(["pkill", "-f", "VRoidStudio.exe"], capture_output=True)


# --- workspace juggling -----------------------------------------------------

def active_workspace() -> int:
    return hyprctl_json("activeworkspace")["id"]


def park(win: Window, workspace: int = WORKSPACE) -> None:
    """Move VRoid to its own workspace without switching to it."""
    if win.workspace != workspace:
        dispatch(f"hl.dsp.window.move({{ workspace = {workspace}, "
                 f"silent = true, window = {_win_expr(win)} }})")
        time.sleep(0.3)


def enter(workspace: int = WORKSPACE) -> int:
    """Switch to the driving workspace; returns the workspace we came from."""
    prev = active_workspace()
    if prev != workspace:
        dispatch(f"hl.dsp.focus({{ workspace = {workspace} }})")
        time.sleep(0.3)
    return prev


def leave(prev: int) -> None:
    if active_workspace() != prev:
        dispatch(f"hl.dsp.focus({{ workspace = {prev} }})")


def dismiss_screensaver() -> bool:
    """Close an idle screensaver overlay if one grabbed the session.

    Only ever closes a window whose class contains "screensaver" - the same
    thing any keypress would do, but without typing into an unknown window.
    """
    for c in _clients():
        if "screensaver" in (c.get("class") or "").lower():
            dispatch(f"hl.dsp.window.close({{ window = "
                     f"hl.get_window('address:{c['address']}') }})")
            time.sleep(1.0)
            return True
    return False


def focus(win: Window | None = None) -> Window:
    win = win or find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    dispatch(f"hl.dsp.focus({{ window = {_win_expr(win)} }})")
    time.sleep(0.25)
    return find_window() or win


def fullscreen(win: Window | None = None) -> Window:
    """Make VRoid maximised/fullscreen so geometry is stable across runs."""
    win = focus(win)
    if not win.fullscreen:
        dispatch("hl.dsp.window.fullscreen()")
        time.sleep(0.6)
    return find_window() or win


# --- output + capture -------------------------------------------------------

def primary_output() -> Output:
    mons = hyprctl_json("monitors")
    if not mons:
        raise RuntimeError("hyprctl reports no monitors")
    mon = mons[0]
    scale = float(mon.get("scale", 1.0))
    return Output(int(mon["x"]), int(mon["y"]),
                  int(round(mon["width"] / scale)),
                  int(round(mon["height"] / scale)), scale)


def capture_region(x: int, y: int, w: int, h: int, path: Path) -> None:
    subprocess.run(
        ["grim", "-g", f"{x},{y} {w}x{h}", str(path)],
        check=True, capture_output=True,
    )


def capture_window(win: Window, path: Path) -> bool:
    """grim only captures screen regions; the caller falls back to
    capture_region on the window's geometry."""
    return False


# --- pointer: native/vpointer -----------------------------------------------
#
# ydotool is not installed here and /dev/uinput is root-only (0600
# root:root), so evdev injection would need sudo/a udev rule; the Wayland
# virtual-pointer protocol needs neither.

def render_script(ops) -> str:
    """Pointer ops -> the line protocol native/vpointer.c reads on stdin."""
    lines: list[str] = []
    for op in ops:
        kind = op[0]
        if kind == "move":
            lines.append(f"move {op[1]:.0f} {op[2]:.0f}")
        elif kind == "sleep":
            lines.append(f"sleep {int(op[1])}")
        elif kind in ("down", "up"):
            lines.append(f"{kind} {op[1]}")
        elif kind == "click":
            n = op[2] if len(op) > 2 else 1
            for i in range(n):
                if i:
                    lines.append("sleep 80")
                lines.append(f"click {op[1]}")
        elif kind == "scroll":
            lines.append(f"scroll {int(op[1])}")
        else:
            raise ValueError(f"unknown pointer op {op!r}")
    return "\n".join(lines) + "\n"


def run_pointer(ops, extent: tuple[int, int]) -> None:
    if not VPOINTER.exists():
        raise RuntimeError(f"{VPOINTER} missing - run native/build.sh")
    w, h = extent
    subprocess.run([str(VPOINTER), "-W", str(w), "-H", str(h)],
                   input=render_script(ops), text=True, check=True,
                   capture_output=True)


def cursor_pos() -> tuple[float, float] | None:
    cur = hyprctl("cursorpos").strip().split(",")
    try:
        return float(cur[0]), float(cur[1])
    except (ValueError, IndexError):
        return None


# --- keyboard + wheel: X11 XTEST through Xwayland ---------------------------
#
# wtype (zwp_virtual_keyboard) does NOT work against this app: VRoid runs
# under Proton/XWayland and the X server keeps a stale copy of wtype's
# throwaway keymap, so "SpikeAvatar" arrives as a single "1". XTEST through
# Xwayland uses the real keymap and lands correctly, so keyboard input goes
# over X11 while the pointer stays on the Wayland virtual-pointer protocol.
# The wheel also goes over X11: VRoid ignores zwlr_virtual_pointer axis
# events but honours X button 4/5 (6/7 horizontal) events.

_XK_ALIASES = {
    "enter": "Return", "return": "Return", "esc": "Escape", "escape": "Escape",
    "tab": "Tab", "backspace": "BackSpace", "delete": "Delete",
    "space": "space", "up": "Up", "down": "Down", "left": "Left",
    "right": "Right", "home": "Home", "end": "End", "pageup": "Prior",
    "pagedown": "Next", "ctrl": "Control_L", "control": "Control_L",
    "shift": "Shift_L", "alt": "Alt_L", "super": "Super_L", "meta": "Super_L",
    "cmd": "Control_L", "command": "Control_L",   # the app's primary modifier
}

_dpy = None


def _display():
    global _dpy
    if _dpy is None:
        import os
        from Xlib import display
        os.environ.setdefault("DISPLAY", ":0")
        _dpy = display.Display(os.environ["DISPLAY"])
    return _dpy


def _keysym(name: str) -> int:
    from Xlib import XK
    name = _XK_ALIASES.get(name.lower(), name)
    ks = XK.string_to_keysym(name)
    if ks == 0 and len(name) == 1:
        ks = ord(name)
        if ks > 0x7F:  # unicode keysym encoding
            ks += 0x01000000
    return ks


def _keycode(ks: int) -> tuple[int, bool]:
    """(keycode, needs_shift) for a keysym on the *current* layout."""
    d = _display()
    code = d.keysym_to_keycode(ks)
    if code == 0:
        return 0, False
    # is it the shifted level?
    try:
        base = d.keycode_to_keysym(code, 0)
    except Exception:
        base = ks
    return code, base != ks


def _tap(code: int, mods: list[int], hold: float = 0.02) -> None:
    from Xlib import X
    from Xlib.ext import xtest
    d = _display()
    for m in mods:
        xtest.fake_input(d, X.KeyPress, m)
    d.sync()
    xtest.fake_input(d, X.KeyPress, code)
    d.sync()
    time.sleep(hold)
    xtest.fake_input(d, X.KeyRelease, code)
    d.sync()
    for m in reversed(mods):
        xtest.fake_input(d, X.KeyRelease, m)
    d.sync()


def _remap_spare(ks: int) -> int:
    """Bind a keysym the layout lacks onto a scratch keycode."""
    d = _display()
    code = 250  # high, unused on a normal xkb map
    d.change_keyboard_mapping(code, [[ks, ks, ks, ks]])
    d.sync()
    time.sleep(0.03)
    return code


def type_text(text: str, delay_ms: int = 22) -> None:
    """Type a literal string into the focused widget (XTEST)."""
    d = _display()
    shift = d.keysym_to_keycode(_keysym("Shift_L"))
    spare_used = False
    for ch in text:
        if ch == "\n":
            key("Return")
            continue
        ks = _keysym(ch)
        code, need_shift = _keycode(ks)
        if code == 0:
            code, need_shift, spare_used = _remap_spare(ks), False, True
        _tap(code, [shift] if need_shift else [])
        time.sleep(delay_ms / 1000.0)
    if spare_used:
        d.change_keyboard_mapping(250, [[0, 0, 0, 0]])
        d.sync()
    time.sleep(0.15)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a named key: Return, Escape, Tab, BackSpace, a, ... with mods."""
    d = _display()
    ks = _keysym(name)
    code, need_shift = _keycode(ks)
    if code == 0:
        raise ValueError(f"no keycode for {name!r}")
    mod_codes = [d.keysym_to_keycode(_keysym(m)) for m in (mods or [])]
    if need_shift:
        mod_codes.append(d.keysym_to_keycode(_keysym("Shift_L")))
    for _ in range(times):
        _tap(code, mod_codes)
        time.sleep(0.06)
    time.sleep(0.12)


def scroll(ticks: int, horizontal: bool = False) -> None:
    """Wheel notches at the current pointer. Positive = down / right."""
    from Xlib import X
    from Xlib.ext import xtest
    d = _display()
    if horizontal:
        btn = 7 if ticks > 0 else 6
    else:
        btn = 5 if ticks > 0 else 4
    for _ in range(abs(ticks)):
        xtest.fake_input(d, X.ButtonPress, btn); d.sync()
        xtest.fake_input(d, X.ButtonRelease, btn); d.sync()
        time.sleep(0.07)


def input_focus_ok() -> bool:
    """True when the X input focus is on the VRoid window."""
    try:
        name = _display().get_input_focus().focus.get_wm_name() or ""
    except Exception:
        return False
    return "vroid" in name.lower()


# --- save dialog ------------------------------------------------------------

def app_path(p: Path) -> str:
    r"""/home/you/x -> Z:\home\you\x  (the Proton prefix maps Z:\ to /)."""
    return "Z:" + str(Path(p).resolve()).replace("/", "\\")


def save_dialog_enter_path(out_path: Path) -> None:
    """Wine's dialog opens with the file-name field focused and selected, so
    typing the Windows path replaces it; no click needed."""
    type_text(app_path(out_path))


def ui_scale(shot_scale: float) -> float:
    """Image px per VRoid UI point. The Proton/Xwayland client renders 1:1
    with output pixels whatever the Hyprland scale (the reference anchors -
    tab strip at y = 23 - were measured at 2560x1440, scale 1.25), so this
    is 1.0 regardless of the capture's px-per-layout-unit."""
    return 1.0


# --- status -----------------------------------------------------------------

def helpers() -> dict:
    return {
        "vpointer": {"path": str(VPOINTER), "present": VPOINTER.exists()},
        "grim": bool(shutil.which("grim")),
        "tesseract": bool(shutil.which("tesseract")),
        "hyprctl": bool(shutil.which("hyprctl")),
    }
