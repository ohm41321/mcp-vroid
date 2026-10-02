# Notes for agents working on mcp-vroid

## Verify

```bash
uv run pytest -q                       # display-free: gestures, key maps, backend surface
uv run python scripts/smoke_test.py    # server over stdio, vroid_status (no input)
uv run vroid-driver shot && uv run vroid-driver find Face   # live capture + OCR (VRoid open)
```

Anything that clicks or types drives the real desktop: run it attended.

## macOS backend footguns (learned the hard way)

* `NSWorkspace.frontmostApplication()` and `NSRunningApplication.isActive()`
  only refresh on the *main* run loop. Pumping `NSRunLoop.currentRunLoop()`
  fixes the CLI but not the MCP server, whose tools run on worker threads
  (verified: a worker never saw VRoid become frontmost, so `leave()`
  short-circuited; `isActive()` stayed True after switching away). The
  backend reads the frontmost app from the window server instead
  (`macos._ws_front_pid`: owner of the first layer-0 on-screen window) and
  lets the Accessibility server's `AXFocusedApplication` veto it
  (`_ax_front_pid`). AX answers `kAXErrorCannotComplete` (-25204) whenever
  the focused app is VRoid/Unity, so it is a veto, not the source of truth;
  an active app with *no* on-screen window (bare Finder, a menu-bar
  utility) can therefore pass the guard while keys go to it.
* Stage Manager reports a window parked in its strip at thumbnail bounds
  (158x186 pt seen for the main window) - below the helper's 500x500, so
  `find_window` prefers titled windows and `capture_window` declines when
  the `-l` image does not match the bounds (caller focuses + re-measures).
* `CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly)` hides windows
  in other Spaces. Use `kCGWindowListOptionAll` and read
  `kCGWindowIsOnscreen`; `Window.workspace` is `active-space`/`other-space`.
* `screencapture -l <window id>` captures the window from any Space (title
  bar included, trimmed by the backend); `-R` captures whatever is on the
  active Space. `grab_window` uses `-l`, so read-only tools never switch
  Spaces.
* Unity ignores ⌘/⇧ sent as KeyDown events for the modifier keycodes: post
  them as `kCGEventFlagsChanged` (`macos._mod_event`). AppKit widgets (the
  save panel) accept either, which is why the panel worked and the app's
  `Cmd+Shift+S` did not.
* VRoid's own popups (hamburger menu) do not close on Escape; toggle them
  by clicking the same control again.
* The host app can re-activate itself while a script runs (seen with the
  terminal host: VRoid lost focus mid-flow). The focus guard then raises
  rather than typing into the host; retry with `vroid_launch`.
* Bounds read during the Space-switch slide are offset (x = -1250 was seen
  for a window at x = 185). `macos._settled()` waits for two equal reads.
* The Unity window has no native fullscreen: its zoom button is a plain
  `AXZoomButton`, `AXFullScreen` re-zooms it to 1334×834, and System Events
  fails with "Invalid index" when VRoid's Space is not active. `fullscreen()`
  = focus, then set position/size to `NSScreen.visibleFrame` (0, 33, 1470,
  923 here); the "fullscreen" flag means that geometry.
* `kCGWindowBounds` includes the 28 pt title bar; the backend trims it so
  `y = 0` is the tab strip like on Hyprland (2940×1790 capture on this Mac).
* Notched MacBooks: a native-fullscreen window is `(0, 32, w, h - 32)`, not
  the screen frame. `_is_native_fullscreen` accepts both and skips the trim.
* Unity keeps a hidden 500x500 helper window and four 33 px strips; only the
  main window is ≥ 200 pt on both axes *and* on screen. The save-panel
  detector therefore requires on-screen.
* `ImageOps.autocontrast` is a no-op once a frame holds true black, and
  VRoid's inactive tab labels are light grey — full-frame OCR missed
  "Face"/"Body" until the gamma-2.0 fallback in `locate.FALLBACK_PASSES`
  was added (run only when the plain and inverted passes find nothing).
* Permissions are per *responsible process*. Under this host that was the
  `python3.12` binary in uv's cache (`~/.local/share/uv/python/.../bin/
  python3.12`), not the host app: granting Accessibility to the host left
  `AXIsProcessTrusted()` false until the python binary itself was added.
  False means every CGEvent is silently dropped; the backend raises instead.
* Tesseract full-frame on an M-series Mac is ~0.6 s per pass, not the ~10 s
  the README quotes for the Linux box.

## Verified live on macOS (2026-09-22)

`prepare()` (focus + maximise), `open_tab`, `scroll_panel`, `read_param`,
the hamburger menu, and the save panel: `Cmd+Shift+S` opens an `NSSavePanel`
titled "Save" (880×767 pt, centred, found by `find_dialog_window`), ⌘⇧G +
directory + Return + ⌘A + name lands in the "Save As:" field (OCR confirms
the stem), Escape cancels. Not run: the final Return / an actual export
(`vroid-driver export`), and VRM-settings modal anchors — do that with a
throwaway model.

## Known gaps

* `save_project_as` never deletes an existing target (`export_vrm` does),
  so the panel's "already exists — Replace?" prompt is unhandled and a stale
  file satisfies the size check (pre-existing on Linux).

## Release preparation (2026-10-02)

* `CGEventKeyboardSetUnicodeString` takes a UTF-16 code-unit count, not
  Python's character count. `len(text)` truncated emoji/non-BMP characters;
  the read-only event round-trip regression failed for `😀`, `𠮷`, and
  `A😀` before the fix. Count `len(text.encode("utf-16-le")) // 2`.
* `grab_window` can focus VRoid when window-id capture declines and the
  window is on another Space. README documents this fallback; do not promise
  all screenshot/OCR calls preserve focus.
