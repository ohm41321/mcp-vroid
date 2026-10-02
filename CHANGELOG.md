# Changelog

All notable changes to this project are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions
follow [semantic versioning](https://semver.org/).

## [Unreleased]

### Added

* **macOS backend** (`src/mcp_vroid/driver/backends/macos.py`): the native
  VRoid Studio build is driven through Quartz (window list across Spaces,
  frontmost app from the window server), AppKit (focus / release), System
  Events (maximise to the visible frame, un-minimise), `screencapture`
  (normally by window id without changing focus; Retina-scaled) and CGEvent
  (pointer, wheel, keyboard with `FlagsChanged` modifiers so Unity sees ⌘).
  Selected automatically on Darwin; `MCP_VROID_BACKEND` overrides.
* `vroid_status` reports the backend and, on macOS, the Accessibility and
  Screen Recording permissions; input refuses to run without Accessibility.
* `cmd` as a modifier name in `vroid_key`: the app's shortcut modifier on
  either platform (Ctrl on Linux, ⌘ on macOS).
* OCR midtone-boost fallback pass (`locate.FALLBACK_PASSES`), so VRoid's
  light-grey tab labels and captions are found even when the frame contains
  true black; `find_text` only pays for it when the usual passes miss.
* Display-free unit tests (`uv run pytest`) for backend selection, gesture
  composition, the vpointer script format and the macOS key map.
* GitHub Actions unit-test matrix for Linux and macOS on Python 3.11/3.12.

### Changed

* The driver is split into a platform-neutral surface (`window`, `capture`,
  `input`) and per-platform backends; the Hyprland code moved verbatim into
  `backends/hyprland.py`. Public driver and tool APIs are unchanged.
* `input.double_click` sends both presses in one gesture (click count 2)
  instead of two separate glide-and-click calls.
* Icon anchors in `actions.py` are VRoid UI points measured from the nearest
  window edge (`_pt`, `_ui`) instead of window fractions, so they hold on a
  Retina capture; numerically identical on the 2560×1440 reference.
* The save-dialog path types through the focus guard like every other input.
* `python-xlib` is a Linux-only dependency; `pyobjc-framework-Quartz` is
  macOS-only.

### Removed

* The unused `backend="wayland"` wheel path in `input.scroll` (VRoid ignores
  virtual-pointer axis events; XTEST was always the default).

### Fixed

* macOS keyboard events count UTF-16 code units correctly, preserving emoji
  and other characters outside the Basic Multilingual Plane.

## [0.1.0] — 2026-08-24

First public release.

### Added

* **MCP server** (`mcp-vroid`, stdio) exposing 18 tools over VRoid Studio:
  * lifecycle — `vroid_launch`, `vroid_status`, `vroid_release`
  * seeing — `vroid_screenshot`, `vroid_find_text`, `vroid_find_button`,
    `vroid_current_screen`
  * raw input — `vroid_click`, `vroid_drag`, `vroid_scroll`, `vroid_type`,
    `vroid_key`
  * flows — `vroid_new_character`, `vroid_open_tab`, `vroid_set_slider`,
    `vroid_set_color`, `vroid_export_vrm`, `vroid_save_project`
* **Driver engine** (`mcp_vroid.driver`): `grim` capture, tesseract OCR and
  OpenCV colour matching for locating, `hyprctl` for window management, and
  input through a `zwlr_virtual_pointer_unstable_v1` helper (pointer) plus
  X11 XTEST (keyboard and wheel).
* **`native/vpointer`** — a small C client for the Wayland virtual-pointer
  protocol, built by `native/build.sh`. Moves the real compositor cursor and
  needs no `/dev/uinput` access.
* **Session-environment recovery** so the server works when an MCP client
  launches it with a sanitised environment.
* **Focus guard** — every acting tool refuses to run unless VRoid Studio is
  the focused window; the idle screensaver is dismissed rather than typed
  into.
* **`vroid-driver` CLI** for driving the same engine from a shell.
* `scripts/smoke_test.py` — starts the server, lists tools, calls the
  read-only ones; never sends input.
* Documentation: README, [`docs/ui-map.md`](docs/ui-map.md).

### Known limitations

Calibrated against VRoid Studio 2.14.0 (English) at 2560×1440 / scale 1.25 on
Hyprland. See the README's *Limitations and brittleness* section.

[0.1.0]: https://github.com/nhodges/mcp-vroid/releases/tag/v0.1.0
