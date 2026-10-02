# VRoid Studio UI map

VRoid Studio **2.14.0**, English UI, captured fullscreen at **2560 × 1440**
(Hyprland layout 2048 × 1152, scale 1.25). All coordinates below are **image
px** — the space `vroid_click` and `vroid_find_text` use by default.

Treat every number as a *hint*. The tools locate by OCR and colour first and
fall back to these anchors only for things that have no text (icons). The
UI keeps its size in *points* whatever the window size: left-anchored
widgets (rail, hamburger, tabs) keep their distance from the left edge,
right-anchored ones (toolbar icons, parameter boxes) from the right, so
`actions.py` stores anchors as points from the nearest edge and scales by
the backend's `ui_scale` (1 px/pt on the Hyprland box, 2 on a Retina Mac).

On macOS (native build, Retina) the maximised window captures at **2940 ×
1790** image px (1470 × 895 pt: the display minus menu bar and the 28 pt
title bar, which the backend trims so `y = 0` is the tab strip); a whole
screen capture is 2940 × 1912. The UI is the same, drawn at 2× — halve the
numbers below for points, double them for macOS px. Checked live: share
icon 96 pt from the right, parameter value box 56 pt from the right, colour
box 145 pt from the right / 24 pt below its label, rail x = 24 pt with icons
at y ≈ 80 + 50·i pt.

## Start screen

* `Create New` `+` card at ≈ (118, 218), its caption at (118, 328)
* `New` / `Open` top-right at (2439, 99) / (2495, 100)
* Sample Models grid below

`Create New` opens a modal — *"Select a base to start with"* — with captions
`Fem` at (1199, 862) and `Masc` at (1359, 862). Click the **thumbnail ~100 px
above** the caption, not the caption itself.

## Editor

Tab strip at y ≈ 23:

| tab | x |
|---|---|
| `Face` | 97 |
| `Hairstyle` | 198 |
| `Body` | 302 |
| `Outfit` | 392 |
| `Accessories` | 509 |
| `Look` | 622 |

* Hamburger `☰` at (29, 23) → Save (Ctrl+S), Save As… (Ctrl+Shift+S),
  import / bulk export, undo/redo, back to model selection. **Escape does not
  close this menu** — click elsewhere.
* Toolbar top-right: camera (2415, 23), **share/export** (2464, 23),
  kebab `⋮` (2512, 23).
* Left icon rail (x ≈ 24, first icon y ≈ 77, then every ~48 px) —
  sub-category for the current tab.
* Left panel: preset grid, with `Presets` / `Custom` at y ≈ 120.
* Right panel: Customize, then Parameters.

### Right-panel controls

| control | drive it by |
|---|---|
| slider | the numeric box at x ≈ 2505 (`vroid_set_slider`); the track spans x ≈ 2278 → 2516 with 0.0 centred |
| colour | the `#RRGGBB` box at x ≈ 2450 (`vroid_set_color`) |
| checkbox / radio | click the square/circle |
| accordion | click the caption (e.g. `> Reduce Polygons`) |
| dropdown | only in the native Wine dialogs; click, then arrow keys |

### Parameter names

`Body` starts `Model's Height : 161.2 cm`, then `Fem Height`, `Masc Height`,
`Body Size`, `Head Size`, `Head Width`, `Head Tip (Y)`, `Neck Length` /
`Thickness` / `Width`, `Soften Collarbone`, `Show Adam's Apple`,
`Shoulder Width`, …

`Face` has ~40 rows: `Eye Size X/Y`, `Eyes Position (X/Y)`,
`Rotate Eye Socket`, `Inner/Outer Eye Slant`, `Iris Size X/Y`, `Gaze (Y)`, …

`vroid_set_slider` scrolls the panel to find the row for you.

## Hair editor

Hairstyle tab → left-rail part icon → `Custom` sub-tab → `+ Create New` →
right panel `Edit Hairstyle`.

Inside:

* `Add Freehand Hair Guides` / `Add Procedural Hair Guides` top-left
* a `Hair Groups` list down the left
* tool palette at (330 / 365 / 398 / 432, 83)
* undo / redo at (76, 23) / (133, 23)

**Leaving asks first.** The `✕` at (23, 23) pops a *Close Hairstyle Editor*
modal offering `Save as new item` / `Overwrite` / `Close without saving`.

## Export as VRM

1. Share icon (2464, 23) → `Export as VRM`
2. Full-screen export page; the blue `Export` pill sits at ≈ (2412, 197).
   Reduce Polygons / Materials / Bones accordions are on the right.
3. **VRM Settings** modal — centred, roughly x 1000 → 1560, scrollable:
   * `Export Format` radios: `VRM1.0` / `VRM0.0`
   * `Avatar Name` **required**
   * `Version`
   * `Creators` **required**
   * copyright / contact / references, usage permission checkboxes

   The Export pill stays **grey and dead** until both required fields are
   filled — `vroid_find_button(color='disabled')` will tell you so.
4. **Wine save dialog** — its own window, title `Export`. The `File name:`
   field opens focused and selected, so typing a Windows path replaces it and
   Return fires the default button.

Two traps here:

* The Proton prefix maps `Z:\` to `/`, so `/home/you/models/x.vrm` is
  `Z:\home\you\models\x.vrm`. `vroid_export_vrm` does the translation.
* **Do not click a `Save` located by OCR** in that dialog: the `Save in:`
  label matches the same needle.

Use `vroid_screenshot(whole_screen=true)` while the Wine dialog is up — it is
not a child of the VRoid window and is not inside its geometry.
