"""GUI-automation driver for VRoid Studio.

The loop is: capture -> locate (tesseract OCR / cv2 template match)
-> act (real pointer + keyboard events) -> capture again.

The desktop-specific half lives in `backends/`: Hyprland/Wayland (grim,
wlr virtual pointer, X11 XTEST) and macOS (screencapture, CGEvent).

Originally written as the `tools/vroid-driver` spike in the author's
`arrakis` project; vendored here as the engine under the MCP server.
"""
from .paths import CAPTURES, OUT, VPOINTER  # noqa: F401
