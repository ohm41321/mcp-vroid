"""Platform backends: everything that talks to a window system lives here.

The generic driver modules (`window`, `capture`, `input`) keep the API the
flows and the MCP server use; each backend implements the same set of
module-level functions on top of a different desktop:

    hyprland   Hyprland/Wayland: hyprctl, grim, zwlr_virtual_pointer, XTEST
    macos      macOS: Quartz window list, screencapture, CGEvent, AppKit

Selection is by platform, overridable with MCP_VROID_BACKEND (useful for
running the unit tests against a backend you are not on).
"""
from __future__ import annotations

import importlib
import os
import sys
from types import ModuleType

NAMES = ("hyprland", "macos")


def select_name() -> str:
    forced = os.environ.get("MCP_VROID_BACKEND", "").strip().lower()
    if forced:
        if forced not in NAMES:
            raise RuntimeError(f"MCP_VROID_BACKEND={forced!r}; known: {NAMES}")
        return forced
    return "macos" if sys.platform == "darwin" else "hyprland"


def load(name: str | None = None) -> ModuleType:
    return importlib.import_module(f"{__name__}.{name or select_name()}")


backend = load()
