"""Pointer + keyboard injection.

The gestures (glide-then-click, press-glide-release, wheel notches, typed
strings, named keys) are composed here and replayed by the platform backend:
`native/vpointer` + X11 XTEST on Hyprland, CGEvent on macOS. Both go to
whatever window has focus, so every call re-checks that VRoid is focused
first.

All public coordinates are *window-relative layout units* unless you pass
space="layout" or space="image" (image needs the Shot's scale).
"""
from __future__ import annotations

import time

from . import window as W
from .backends import backend as _B

BUTTONS = {"left": "left", "right": "right", "middle": "middle",
           1: "left", 2: "middle", 3: "right"}

PRIMARY_MOD = W.PRIMARY_MOD   # "ctrl" on Linux, "cmd" on macOS

_SAFE = True   # module-level guard: verify VRoid focus before every action


def set_safety(on: bool) -> None:
    global _SAFE
    _SAFE = on


def _guard() -> None:
    if not _SAFE:
        return
    if not W.is_vroid_focused() and W.dismiss_screensaver():
        W.focus()
    W.assert_vroid_focused()


def _layout_extent() -> tuple[int, int]:
    out = W.primary_output()
    return out.w, out.h


def _run_pointer(ops: list) -> None:
    _B.run_pointer(ops, _layout_extent())


def _resolve(x: float, y: float, space: str, shot=None) -> tuple[float, float]:
    if space == "layout":
        return x, y
    if space == "image":
        if shot is None:
            raise ValueError("space='image' needs shot=")
        return shot.to_layout(x, y)
    win = W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    return win.to_layout(x, y)


def glide_ops(cx: float, cy: float, lx: float, ly: float, moves: int,
              step_ms: int = 12) -> list:
    """Pointer ops for a straight glide in `moves` steps, so hover fires."""
    ops = []
    for i in range(1, moves + 1):
        t = i / moves
        ops.append(("move", cx + (lx - cx) * t, cy + (ly - cy) * t))
        ops.append(("sleep", step_ms))
    return ops


# --- pointer ----------------------------------------------------------------

def move(x: float, y: float, space: str = "window", shot=None) -> None:
    lx, ly = _resolve(x, y, space, shot)
    _run_pointer([("move", lx, ly)])


def click(x: float, y: float, button: str = "left", space: str = "window",
          shot=None, settle: float = 0.35, moves: int = 3,
          count: int = 1) -> None:
    """Move (in a few steps, so hover states fire) then click.

    count=2 is a real double click (both presses inside the OS's threshold).
    """
    _guard()
    lx, ly = _resolve(x, y, space, shot)
    cx, cy = _B.cursor_pos() or (lx, ly)
    ops = glide_ops(cx, cy, lx, ly, moves)
    ops += [("sleep", 60), ("click", BUTTONS.get(button, "left"), count)]
    _run_pointer(ops)
    time.sleep(settle)


def double_click(x: float, y: float, **kw) -> None:
    kw["count"] = 2
    click(x, y, **kw)


def drag(x1: float, y1: float, x2: float, y2: float, button: str = "left",
         space: str = "window", shot=None, steps: int = 24,
         settle: float = 0.4) -> None:
    """Press at (x1,y1), glide to (x2,y2), release. Used for sliders."""
    _guard()
    ax, ay = _resolve(x1, y1, space, shot)
    bx, by = _resolve(x2, y2, space, shot)
    b = BUTTONS.get(button, "left")
    ops = [("move", ax, ay), ("sleep", 120), ("down", b), ("sleep", 120)]
    ops += glide_ops(ax, ay, bx, by, steps, step_ms=16)
    ops += [("sleep", 150), ("up", b)]
    _run_pointer(ops)
    time.sleep(settle)


def scroll(ticks: int, x: float | None = None, y: float | None = None,
           space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Wheel scroll. Negative = up/away, positive = down."""
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    _B.scroll(ticks)
    time.sleep(settle)


def hscroll(ticks: int, x: float | None = None, y: float | None = None,
            space: str = "window", shot=None, settle: float = 0.3) -> None:
    """Horizontal wheel. Negative = left, positive = right.

    Rarely useful in VRoid - the panels only scroll vertically - but the
    export screen's wide accordions and the file dialogs accept it.
    """
    _guard()
    if x is not None and y is not None:
        move(x, y, space, shot)
        time.sleep(0.2)
    _B.scroll(ticks, horizontal=True)
    time.sleep(settle)


# --- keyboard ---------------------------------------------------------------

def type_text(text: str, delay_ms: int = 22) -> None:
    """Type a literal string into the focused widget."""
    _guard()
    _B.type_text(text, delay_ms)


def key(name: str, mods: list[str] | None = None, times: int = 1) -> None:
    """Press a named key: Return, Escape, Tab, BackSpace, a, ... with mods.

    Modifier names: ctrl, shift, alt, super/meta and `cmd` - the app's
    primary shortcut modifier (Control on Linux, Command on macOS).
    """
    _guard()
    _B.key(name, mods, times)


def clear_field() -> None:
    """Select-all + delete in the focused text field."""
    key("a", mods=[PRIMARY_MOD])
    key("BackSpace")


def hotkey(combo: str) -> None:
    """'ctrl+shift+s' -> modifier-held keypress.

    Written with `cmd` as the first modifier, a combo means "the app's
    shortcut" on either platform: hotkey(f"{PRIMARY_MOD}+shift+s").
    """
    *mods, k = combo.split("+")
    key(k, mods=mods)


def x_focus_ok() -> bool:
    """True when the input focus is on the VRoid window."""
    return _B.input_focus_ok()
