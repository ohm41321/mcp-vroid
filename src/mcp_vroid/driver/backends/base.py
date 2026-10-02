"""Types shared by every backend."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Window:
    address: str          # compositor window id (Hyprland address / CG window number)
    cls: str              # window class (Hyprland) / owning app name (macOS)
    title: str
    x: int
    y: int
    w: int
    h: int
    workspace: int | str | None   # Hyprland workspace id; the frontmost app on macOS
    focused: bool
    fullscreen: bool = False

    @property
    def geometry(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) in *layout* (logical) coordinates."""
        return (self.x, self.y, self.w, self.h)

    def to_layout(self, x: float, y: float) -> tuple[float, float]:
        """Window-relative point -> layout point."""
        return (self.x + x, self.y + y)


@dataclass
class Output:
    """The display we capture and inject on, in layout (logical) units."""
    x: int
    y: int
    w: int
    h: int
    scale: float          # image px per layout unit


# Pointer scripts are lists of ops the backend replays:
#   ("move", x, y)        absolute motion, layout coords
#   ("sleep", ms)
#   ("down", button)      button in {"left", "right", "middle"}
#   ("up", button)
#   ("click", button, n)  n presses (2 = double click)
#   ("scroll", step)      wheel notch, +1 down / -1 up
PointerOp = tuple
