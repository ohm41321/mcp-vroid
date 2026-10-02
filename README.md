# MCP VRoid — macOS & Linux

**Control VRoid Studio through MCP on macOS and Linux/Hyprland.**
Launch VRoid, capture its window, locate controls with OCR, edit character
parameters, and run save/export flows from an MCP client.

This is [ohm41321/mcp-vroid](https://github.com/ohm41321/mcp-vroid), our
version of [nhodges/mcp-vroid](https://github.com/nhodges/mcp-vroid). It adds
a native macOS backend while retaining the original Linux/Hyprland backend.
Both platforms use the same 18 MCP tools.

## Platform support

| Platform | VRoid installation | Support and validation |
|---|---|---|
| **macOS** | Native VRoid Studio.app | Added in this version. Window handling, OCR, parameter editing and save-dialog entry exercised on macOS 26 / Apple silicon. Final save/export and the VRM Settings flow still need end-to-end validation. |
| **Linux / Hyprland** | Steam / Proton | Retained from upstream, where it was developed and tested on Arch Linux + Hyprland. Requires Xwayland and the native pointer helper. |

The backend is selected automatically: `macos` on macOS, `hyprland` on Linux.
Override it with `MCP_VROID_BACKEND=macos` or `MCP_VROID_BACKEND=hyprland`.
Other Linux compositors and Windows are not currently supported.

**Status:** experimental GUI automation calibrated for VRoid Studio 2.14.0
(English UI). Run desktop actions attended.

## What's included in this version

* Native macOS window discovery, capture and mouse/keyboard input through
  Quartz, AppKit and CGEvent, with Accessibility and Screen Recording checks.
* A shared driver interface for macOS and Linux, including platform-aware
  shortcuts (`cmd` maps to Command on macOS and Control on Linux).
* OCR fallback for light-grey UI labels and Retina-aware UI anchors.
* Unicode handling for macOS text input, including emoji.
* Display-free unit tests and a GitHub Actions matrix for Linux and macOS.

## Why

VRoid Studio has no scripting API, no CLI, no plugin surface. The only way in
is the one a person uses: look at the window and move the mouse. So that is
what this does — screenshot the window (`grim` on Hyprland, `screencapture`
on macOS), locate things with OCR and colour matching, and inject real
pointer and keyboard events at the compositor level. The MCP client's model
is the eyes; these tools are the hands.

```
   grim / screencapture ──► PNG ──► tesseract / cv2 ──► (x, y) ──► virtual pointer + XTEST / CGEvent
    ▲                                                                          │
    └──────────────────────────  screenshot again  ◄───────────────────────────┘
```

## Demo

These screenshots come from the upstream Linux/Hyprland demo, driven by an
MCP client. They illustrate the shared tools; they are not evidence of a
completed macOS export.

Setting body parameters by typing exact values into the Parameters panel
(`vroid_open_tab("Body")` → `vroid_set_slider("Head Size", -0.15)`):

![The VRoid editor's Body tab, driven: parameters panel with typed values](docs/editor-parameters.png)

Inside the hair editor, tuning procedural hair guides (`vroid_click` on the
group, `vroid_set_slider` on Height / Interval / Twist Intensity):

![The VRoid hair editor with a procedural hair group selected and its parameters open](docs/hair-editor.png)

Filling the VRM Settings modal on the way to an export (`vroid_export_vrm`
walks the whole flow, including Wine's save dialog):

![The Export as VRM screen with the VRM Settings modal, required fields being typed](docs/export-vrm.png)

## Requirements

Two backends, picked by platform (`MCP_VROID_BACKEND=hyprland|macos`
overrides): everything desktop-specific lives in
`src/mcp_vroid/driver/backends/`.

### Linux: Hyprland

The upstream Linux backend was developed and tested on **Arch Linux +
Hyprland**, with VRoid Studio 2.14.0 (English UI) running under
**Steam/Proton**. Requirements:

| | needed for | how portable |
|---|---|---|
| **Hyprland** ≥ 0.55 | window discovery, focus, workspaces, closing the screensaver — via `hyprctl` and its Lua dispatch API | **Hyprland-specific.** Implemented in `src/mcp_vroid/driver/backends/hyprland.py`; other compositors need a backend port. |
| `grim` | screenshots | any **wlroots** compositor (`wlr-screencopy`) |
| **`zwlr_virtual_pointer_unstable_v1`** | moving and clicking the real cursor | any **wlroots** compositor |
| **Xwayland** (`DISPLAY`) | keyboard and wheel, via X11 **XTEST** | any Wayland session with Xwayland |
| `tesseract` + `eng` traineddata | OCR — the entire locating story | portable |
| `gcc`, `wayland-scanner`, `libwayland-client` | building the pointer helper | portable |
| **VRoid Studio** via Steam/Proton (appid `1486350`) | the app being driven | the Steam launch path is assumed; a native/Wine install needs the launch command changed |
| Python **3.11+** and [`uv`](https://docs.astral.sh/uv/) | the server itself | portable |

So: **wlroots + Xwayland** for the input and capture layer, **Hyprland only**
for window management. On Arch:

```bash
sudo pacman -S grim tesseract tesseract-data-eng wayland gcc pkgconf
```

### macOS

Tested on macOS 26 (Apple silicon, Retina) with the **native VRoid Studio
2.14.0** build from vroid.com (bundle `net.pixiv.vroid.macosx`). No Steam, no
Wine, no native helper to compile.

| | needed for | notes |
|---|---|---|
| `pyobjc-framework-Quartz` (+ Cocoa) | window list, focus, CGEvent input, screen geometry | installed by `uv sync` on macOS |
| `/usr/sbin/screencapture` | screenshots | ships with macOS |
| System Events (`osascript`) | maximising the window, un-minimising it, focus fallback | ships with macOS |
| `tesseract` + `eng` | OCR | `brew install tesseract` |
| **Accessibility** permission | posting pointer/keyboard events, System Events | see below |
| **Screen Recording** permission | `screencapture`; without it you get the wallpaper, silently | see below |
| VRoid Studio.app | the app being driven | `open -b net.pixiv.vroid.macosx` is how it is launched |

**Permissions:** open *System Settings → Privacy & Security → Accessibility*
and *→ Screen Recording*. Grant access to the responsible process shown by
macOS: this may be your terminal or MCP client, or the Python executable
used by `uv`. Granting only the host app is not always sufficient. Restart
the host and MCP server after granting, then check that `vroid_status`
reports `helpers.accessibility` and `helpers.screen_recording` as `true`.
Acting tools refuse to run without Accessibility.

What "workspace 9" means here: `vroid_launch` brings VRoid to the front and
maximises its window to the screen's visible frame (menu bar excluded). The
Unity window has no native fullscreen — its zoom button is a plain
`AXZoomButton` and `AXFullScreen` only re-zooms it — so the 28 pt title bar
stays; the backend trims it from the reported geometry and from captures,
so `y = 0` is the tab strip like on Hyprland. `vroid_release` re-activates
the app you were in before (switching the Space back if VRoid was in
another one). Window captures normally use the window id
(`screencapture -l`), which works from any Space without activating VRoid.
If that capture does not match the reported bounds (for example, a Stage
Manager thumbnail), the fallback may bring VRoid forward and switch Spaces
before capturing its screen region.

Two things that bit during bring-up, both handled in the backend: macOS
attributes permissions to the *responsible process*, which under some hosts
is the `python3.12` binary in uv's cache rather than the host app (check the
Accessibility list for it); and Unity only sees ⌘/⇧ when the modifiers
arrive as `FlagsChanged` events, so plain key-down events for ⌘ made
`Cmd+Shift+S` a no-op while AppKit's save panel accepted them fine.

## Quickstart

Both platforms require **Python 3.11+**, [`uv`](https://docs.astral.sh/uv/)
and an installed copy of VRoid Studio with its UI set to English.

```bash
git clone https://github.com/ohm41321/mcp-vroid.git
cd mcp-vroid
uv sync --locked        # virtualenv + platform-specific dependencies
```

On **Linux/Hyprland**, also build the required pointer helper:

```bash
bash native/build.sh
```

On **macOS**, install OCR and grant the permissions described above:

```bash
brew install tesseract
```

On Linux, `native/build.sh` compiles a ~150-line C client for the Wayland
virtual-pointer protocol (the protocol XML is vendored under
`native/protocols/`). Without it every pointer tool fails with
`native/vpointer missing`; `vroid_status` tells you whether it is there. On
macOS there is nothing to build — grant the two permissions instead.

Register it with Claude Code:

```bash
claude mcp add vroid -- uv run --directory /path/to/mcp-vroid mcp-vroid
```

…or with any client that takes an `mcpServers` block:

```json
{
  "mcpServers": {
    "vroid": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/mcp-vroid", "mcp-vroid"]
    }
  }
}
```

Then ask your client to call `vroid_status`, and if it looks healthy,
`vroid_launch()`.

Clients often start servers with a **sanitised environment**. On Linux this
server recovers `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY`,
`HYPRLAND_INSTANCE_SIGNATURE` and `DISPLAY` from the runtime dir at startup
(`src/mcp_vroid/session_env.py`), so `hyprctl` / `grim` / XTEST work anyway.
`vroid_status` reports what it had to fill in; anything already in the
environment wins. macOS needs nothing recovered.

Optional environment variables:

| var | default | meaning |
|---|---|---|
| `MCP_VROID_CAPTURES` | `<state-home>/mcp-vroid/captures` | where screenshots are written |
| `MCP_VROID_OUT` | `<state-home>/mcp-vroid/out` | default dir for exports/saves |
| `MCP_VROID_VPOINTER` | `<checkout>/native/vpointer` | path to the pointer helper (Linux) |
| `MCP_VROID_MAX_IMAGE_PX` | `1600` | longest edge of images sent to the client (0 = never downscale) |
| `MCP_VROID_BACKEND` | by platform | `hyprland` or `macos` |

`<state-home>` is `$XDG_STATE_HOME`, or `~/.local/state` when unset, on both
platforms. Captures and exports are kept outside the checkout by default.

## Tools

18 tools, in four groups.

**Lifecycle**

| tool | what it does |
|---|---|
| `vroid_launch(restart=false, timeout=240)` | Start VRoid if needed (Steam on Linux, the app bundle on macOS), park it on Hyprland workspace 9 / bring it to the front on macOS, remember where you were, focus + fullscreen (macOS: maximise) it. `restart=true` kills the running instance first — unsaved work is lost. |
| `vroid_status()` | Backend, window present/focused/title/geometry, active workspace (frontmost app on macOS), capture dirs, and whether the helpers — `vpointer`/`grim`/`tesseract`/`hyprctl`, or pyobjc/`screencapture`/`tesseract` plus the Accessibility and Screen Recording permissions — are available. Read-only, no OCR. |
| `vroid_release()` | Switch back to the workspace (Linux) or app (macOS) the user was on. VRoid keeps running. |

**Seeing**

| tool | what it does |
|---|---|
| `vroid_screenshot(region?, tag?, whole_screen?, full_resolution?)` | Capture the window (or the whole output, for the save dialog), save it, and return it as MCP image content for the client's model to look at. Reports native size and the downscale factor applied for transport. |
| `vroid_find_text(query, region?, exact?, limit?)` | Fresh capture + tesseract; returns matching word boxes and centres in image px. Pass `region` to reduce OCR work. Timing depends on the machine: the Linux reference took ~10 s per full frame; the M-series Mac took ~0.6 s per pass. |
| `vroid_find_button(color='primary'\|'disabled', label?, region?)` | Finds VRoid's solid `#0096FA` pills by colour, because tesseract loses white-on-blue labels. A grey pill means *disabled*. |
| `vroid_current_screen()` | `start` / `editor` / `export_vrm` / `hair_editor` / `unknown`. |

**Acting — raw input**

| tool | what it does |
|---|---|
| `vroid_click(x, y, space='image', button='left', double=false)` | Glides the pointer in a few steps (so hover states fire) and clicks. |
| `vroid_drag(x1, y1, x2, y2, space='image', button='left')` | Press → 24-step glide → release. Right-drag orbits the camera, middle-drag pans. |
| `vroid_scroll(dy, dx=0, x?, y?, space='image')` | Wheel notches (X11 buttons 4/5 and 6/7, or CGEvent scroll-wheel lines). Park the pointer over the panel you mean to scroll. |
| `vroid_type(text, clear_first=false)` | Types into the focused widget (XTEST / CGEvent). |
| `vroid_key(combo, times=1)` | `Return`, `Escape`, `cmd+s`, `cmd+shift+s`, … — `cmd` is the app's shortcut modifier on either platform (Ctrl on Linux, ⌘ on macOS); `ctrl` is the literal Control key. |

**Acting — flows**

| tool | what it does |
|---|---|
| `vroid_new_character(base='Fem'\|'Masc')` | Start screen → Create New → base → editor. |
| `vroid_open_tab(name)` | Face / Hairstyle / Body / Outfit / Accessories / Look. |
| `vroid_set_slider(label, value)` | Scrolls the Parameters panel to the row and types an exact value into its numeric box. |
| `vroid_set_color(label, hex)` | Same, for a `#RRGGBB` colour box. |
| `vroid_export_vrm(path, avatar_name, creator, version='1.0')` | The whole Export-as-VRM walk, including the VRM Settings metadata modal and the save dialog (Wine's, or the macOS save panel). `version` picks VRM1.0 or VRM0.0. |
| `vroid_save_project(name?)` | Ctrl/Cmd+Shift+S to an explicit `.vroid` path, or a plain Save with no argument. |

Every acting tool focuses VRoid first and **refuses to act if the focused
window is not VRoid Studio**.

## How it works

The loop is **see → locate → act → see again**:

1. `vroid_launch()`
2. `vroid_screenshot()` — the image goes to the client's model, which *looks* at it
3. `vroid_find_text("Export")` or `vroid_find_button()` for coordinates
4. `vroid_click(x, y)` — always with coordinates from a *fresh* capture
5. `vroid_screenshot()` to confirm what actually happened

**Seeing** is `grim` (Hyprland) on the window geometry or `screencapture -l`
(macOS) on the window id, then tesseract for word boxes and OpenCV for
solid-colour buttons (VRoid's primary pills are `#0096FA`, and OCR reliably
loses white-on-blue labels). OCR runs a plain and an inverted (light-on-dark)
pass, and a midtone-boosted pass for VRoid's light-grey captions when those
two find nothing.

**Acting** on Hyprland goes down two different paths, for annoying reasons:

* *Pointer* — a small C client (`native/vpointer.c`) speaking
  `zwlr_virtual_pointer_unstable_v1`. It moves the real compositor cursor, so
  hover states and drags behave exactly as they do for a human, and it needs
  no permissions: `ydotool`'s `/dev/uinput` route is `0600 root:root` and
  would need sudo or a udev rule.
* *Keyboard and wheel* — X11 **XTEST** through Xwayland, because the
  virtual-pointer protocol has no keyboard counterpart and VRoid is an
  Xwayland client anyway.

On macOS everything is a **CGEvent** posted on the HID event tap: mouse
moves/drags/clicks (with a real click count for double-clicks), scroll-wheel
lines, and keyboard events that carry both an ANSI virtual key code (so
⌘-shortcuts land) and the Unicode string (so any character types).

**Coordinate spaces.** Three are in play and they are all different:

| space | Hyprland reference machine | macOS reference machine | who uses it |
|---|---|---|---|
| **layout** (logical) | 2048 × 1152 | 1470 × 956 points | `hyprctl` + the virtual pointer / Quartz + CGEvent |
| **image pixels** of a capture | 2560 × 1440 | 2940 × 1790 (maximised window, title bar trimmed) | tesseract, cv2, everything you see |
| **X11** pixels (Xwayland) | 2560 × 1440 | — | XTEST |

Tools take and return **image px** (`space="image"`) by default and convert
internally, so `vroid_find_text` output can be handed straight to
`vroid_click`. If `MCP_VROID_MAX_IMAGE_PX` downscaled the picture you were
shown, multiply coordinates read off it by the inverse of the reported
`downscale` — or just ask `vroid_find_text`, which always reports native px.

Rules of thumb, learned the hard way:

* **Read the whole frame, not a crop.** A "Close Hairstyle Editor" confirm
  modal sat in the middle of the screen through six failed clicks because the
  check only OCR'd the top 60 px.
* **Don't judge change by the 3D viewport.** VRoid dithers every frame, so a
  full-window diff reads ~0.98 even when nothing happened. Watch a UI strip.
* **Prefer numeric boxes to slider drags.** `vroid_set_slider` types an exact
  value; dragging is for controls that have no box.
* **Primary buttons are found by colour, not text.** A grey pill where you
  expect blue is the app telling you a required field is empty.

A detailed map of VRoid's UI — tab strip, rails, panels, the export flow, the
hair editor, with measured coordinates — is in **[docs/ui-map.md](docs/ui-map.md)**.

## Limitations and brittleness

This is GUI automation with no API underneath. Be realistic about it:

* **OCR is the whole locating story**, and it is imperfect. Small,
  letter-spaced or light-on-dark labels get split or dropped (`Export` →
  `E` + `xport`). White-on-blue is lost entirely, which is why
  `vroid_find_button` exists. Icons have no text at all — those anchors are
  hard-coded in VRoid's UI points, measured from the nearest window edge.
* **Coupled to the UI version.** Needles and icon anchors were calibrated
  on VRoid Studio 2.14.0, English, at 2560×1440 / scale 1.25. A pixiv UI
  reflow, another language, or a different monitor can require re-measuring.
  (Japanese UI → kebab `⋮` → Settings → Language.) The macOS build draws the
  same UI at 2 px per point; the anchors are expressed in UI points from the
  window edges, and the toolbar icons, rail, parameter boxes and colour
  boxes were checked against a live 2940×1790 capture. Modal-centre regions
  are still window fractions.
* **Modals appear outside your search region** and swallow clicks silently.
* **Timing is guessed.** The 3D viewport takes ~5 s after a base is chosen;
  export takes 5–30 s, longer for heavy models.
* **The save dialog is a separate window** — Wine's, with its own class and
  geometry, or a centred `NSSavePanel` on macOS — use
  `vroid_screenshot(whole_screen=true)` there. On macOS the path goes in via
  ⌘⇧G ("Go to the folder") then the file name; verified up to the point of
  pressing Save, which an actual export has not yet exercised here.
* **Save As to an existing file is not handled reliably.** The replacement
  confirmation is unhandled and a stale file can satisfy the completion
  check. Use a new `.vroid` filename. VRM export deletes an existing target
  before starting; use a new `.vrm` path to preserve previous exports.
* **Single instance, single session, single display.** One VRoid window, one
  desktop, no headless mode, no parallelism. It drives *your* screen; on macOS
  the primary display (the one with the menu bar at 0,0) is assumed.
* **The idle screensaver** can grab the session mid-run (Linux). The guard
  refuses to type into it and closes that one window (and only that one)
  before acting.
* **Attended use is recommended.** See below.

## Security

**This server injects real mouse and keyboard events into your live desktop
session and takes screenshots of it.** That is the entire point, and it is
also the risk:

* Screenshots may capture anything on the output — `whole_screen=true`
  captures everything, and captures are written to disk unencrypted.
* Keystrokes go to whatever holds keyboard focus. The driver refuses to act
  unless VRoid Studio is focused, but a careless or hostile prompt can still
  click anywhere *inside* VRoid.
* Screenshot and OCR tools can bring VRoid forward if the macOS window-id
  capture fails its geometry check while VRoid is on another Space.
* `vroid_launch(restart=true)` kills VRoid Studio and loses unsaved work.
* Nothing here is sandboxed and there is no confirmation step.

**Run it attended**, on a session you are watching. Don't run it on a shared
or multi-user machine, don't leave an agent driving it unsupervised, and treat
the captures directory as sensitive. `vroid_release()` gives the desktop back
when you're done.

## Development

```bash
uv run pytest -q                                 # display-free unit tests (gestures, key maps, both backends)
uv run python scripts/smoke_test.py              # start the server, list tools, call vroid_status
uv run python scripts/smoke_test.py --screenshot # + one passive capture if VRoid is open
uv run vroid-driver shot                         # the original driver CLI, still here
```

The unit tests require no running VRoid instance or desktop permissions.
The smoke test checks MCP startup and status on a configured desktop;
`--screenshot` also needs Screen Recording on macOS. These checks do not
prove that a save or export completes successfully.

`vroid-driver` (`mcp_vroid.driver.cli`) is a shell interface to the same
engine — `launch`, `shot`, `find`, `click`, `tab`, `slider`, `export`, `cam`,
`apply-params`, … — handy for debugging without an MCP client in the loop.

Layout:

```
src/mcp_vroid/server.py       MCP tool definitions (stdio)
src/mcp_vroid/session_env.py  recovers the Wayland/X session env (no-op on macOS)
src/mcp_vroid/driver/         the engine
  window.py                   find / launch / focus / workspaces (platform-neutral surface)
  capture.py                  Shot + coordinate spaces
  locate.py                   tesseract OCR + colour button matching
  input.py                    gestures: glide-click, drag, wheel, type, keys
  actions.py                  the VRoid-specific flows
  backends/hyprland.py        hyprctl + grim + vpointer + XTEST
  backends/macos.py           Quartz window list + screencapture + CGEvent + AppKit
native/vpointer.c             zwlr_virtual_pointer client (Linux)
tests/                        display-free unit tests
```

## Contributing

Open [issues](https://github.com/ohm41321/mcp-vroid/issues) and pull requests
in this repository. Useful contributions include:

* **A port to another compositor or OS.** Implement the module-level
  functions in `driver/backends/hyprland.py` (a Sway port is a `swaymsg`
  rewrite of the window half; `grim` and `zwlr_virtual_pointer` already work
  there) and register the name in `backends/__init__.py`.
* **A pixel-by-pixel re-measure of the anchors on macOS**, and a report of
  the export flow end to end there.
* **Anchors for other resolutions or DPI scales**, or for the Japanese UI.
* **Bug reports** — include your compositor, VRoid Studio version, monitor
  resolution and scale, and the output of `vroid_status`. A capture from the
  failing step helps enormously.

GitHub Actions runs the display-free unit tests on Linux and macOS with
Python 3.11 and 3.12. Desktop smoke tests and live VRoid flows must be run
locally. There is no formatter or linter configured; match the surrounding
style.

## Credits and licence

Original project and Linux implementation:
[nhodges/mcp-vroid](https://github.com/nhodges/mcp-vroid) by Nuri Hodges.
This repository adds native macOS support, cross-platform driver structure,
tests and setup documentation. The original MIT copyright notice is
preserved in [LICENSE](LICENSE).

MIT — see [LICENSE](LICENSE). VRoid Studio is a product of pixiv Inc.; this
project is unaffiliated with pixiv and simply drives the app's UI.
