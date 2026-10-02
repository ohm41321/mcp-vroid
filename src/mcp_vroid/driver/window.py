"""Find / launch / focus the VRoid Studio window.

Everything desktop-specific is in `backends/` (Hyprland via hyprctl, macOS
via Quartz/AppKit); this module is the platform-neutral surface the flows
and the MCP server use, plus the bits that are the same everywhere.
"""
from __future__ import annotations

import time

from .backends import backend as _B
from .backends.base import Output, Window  # noqa: F401  (re-exported)

BACKEND: str = _B.BACKEND
WORKSPACE = _B.WORKSPACE            # where VRoid is driven (ws 9 / the app, frontmost)
PRIMARY_MOD: str = _B.PRIMARY_MOD   # modifier the app's shortcuts use (ctrl / cmd)

find_window = _B.find_window
list_windows = _B.list_windows
find_dialog_window = _B.find_dialog_window
is_vroid_focused = _B.is_vroid_focused
launch = _B.launch
kill = _B.kill
active_workspace = _B.active_workspace
park = _B.park
enter = _B.enter
leave = _B.leave
dismiss_screensaver = _B.dismiss_screensaver
focus = _B.focus
fullscreen = _B.fullscreen
notify = _B.notify
primary_output = _B.primary_output
helpers = _B.helpers
app_path = _B.app_path


def assert_vroid_focused() -> None:
    if not is_vroid_focused():
        raise RuntimeError(
            "refusing to act: focused window is not VRoid Studio "
            f"({_B.focused_desc()})"
        )


def wait_for_window(timeout: float = 180.0, poll: float = 2.0) -> Window:
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = find_window()
        if w and w.w > 200 and w.h > 200:
            return w
        time.sleep(poll)
    raise TimeoutError(f"VRoid Studio window did not appear within {timeout}s")


def launch_and_wait(timeout: float = 240.0) -> Window:
    w = find_window()
    if w:
        return w
    launch()
    return wait_for_window(timeout)


def prepare(timeout: float = 240.0) -> tuple[Window, int | str]:
    """Launch if needed, park on our workspace, switch there, focus, maximise.

    Returns (window, previous_workspace) so the caller can restore.
    """
    win = launch_and_wait(timeout)
    dismiss_screensaver()
    park(win)
    prev = enter()
    win = fullscreen(win)
    assert_vroid_focused()
    return win, prev
