"""Screenshot the VRoid window and hand back a PIL image.

Coordinates: the compositor's layout is *logical* (Hyprland: 2048x1152 for
a 2560x1440 panel at scale 1.25; macOS: points, 1470x956 on a Retina
MacBook). Captures come back at the output's native scale, so image pixels
are `scale` times the layout units. A Shot carries the mapping so callers
can hand OCR pixel coords straight back to input.click().
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from . import window as W
from .backends import backend as _B
from .paths import CAPTURES


def output_scale() -> float:
    return W.primary_output().scale


def next_capture_path(tag: str = "") -> Path:
    n = 0
    for p in CAPTURES.glob("[0-9][0-9][0-9]*.png"):
        try:
            n = max(n, int(p.name[:3]))
        except ValueError:
            pass
    name = f"{n + 1:03d}" + (f"-{tag}" if tag else "") + ".png"
    return CAPTURES / name


@dataclass
class Shot:
    image: Image.Image
    path: Path
    ox: int          # region origin x, layout coords
    oy: int
    scale: float     # image px per layout unit

    @property
    def size(self):
        return self.image.size

    def to_window(self, px: float, py: float) -> tuple[float, float]:
        """Image pixel -> window-relative layout coords."""
        return (px / self.scale, py / self.scale)

    def to_layout(self, px: float, py: float) -> tuple[float, float]:
        return (self.ox + px / self.scale, self.oy + py / self.scale)

    def crop(self, box) -> "Shot":
        l, t, r, b = box
        return Shot(self.image.crop(box), self.path,
                    int(self.ox + l / self.scale), int(self.oy + t / self.scale),
                    self.scale)


def grab_region(x: int, y: int, w: int, h: int, tag: str = "",
                path: Path | None = None) -> Shot:
    path = path or next_capture_path(tag)
    scale = output_scale()
    _B.capture_region(x, y, w, h, path)
    img = Image.open(path).convert("RGB")
    # the capture may clamp the region at the output edge; derive the real scale.
    if w:
        scale = img.width / w
    return Shot(img, path, x, y, scale)


def grab_window(win: W.Window | None = None, tag: str = "") -> Shot:
    win = win or W.find_window()
    if win is None:
        raise RuntimeError("VRoid Studio window not found")
    path = next_capture_path(tag)
    if _B.capture_window(win, path):
        # by window id (macOS): correct even when the window is on another
        # Space or covered, so looking never steals focus. The backend has
        # checked the image matches the window's bounds.
        img = Image.open(path).convert("RGB")
        return Shot(img, path, win.x, win.y, img.width / win.w)
    if win.workspace == "other-space":
        # the window lives in a Space that is not showing (or its bounds
        # are stale); a capture of its rectangle would show whatever is.
        # Bring it forward first, which also re-measures it.
        win = W.focus(win)
    return grab_region(*win.geometry, tag=tag, path=path)


def grab_screen(tag: str = "") -> Shot:
    out = W.primary_output()
    return grab_region(out.x, out.y, out.w, out.h, tag=tag)
