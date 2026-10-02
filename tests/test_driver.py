"""Display-free tests: backend selection, gesture composition, key mapping.

Nothing here touches a window system. The backend's injection functions are
monkeypatched to record what they would have sent.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from mcp_vroid.driver import backends
from mcp_vroid.driver.backends import hyprland, macos


# --- selection --------------------------------------------------------------

def test_select_by_platform(monkeypatch):
    monkeypatch.delenv("MCP_VROID_BACKEND", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert backends.select_name() == "macos"
    monkeypatch.setattr(sys, "platform", "linux")
    assert backends.select_name() == "hyprland"


def test_select_override(monkeypatch):
    monkeypatch.setenv("MCP_VROID_BACKEND", "hyprland")
    assert backends.select_name() == "hyprland"
    monkeypatch.setenv("MCP_VROID_BACKEND", "bogus")
    with pytest.raises(RuntimeError):
        backends.select_name()


def test_backends_expose_same_surface():
    names = {
        "BACKEND", "WORKSPACE", "PRIMARY_MOD", "SAVE_DIALOG_REGION",
        "SAVE_DIALOG_FIELD_LABEL", "find_window", "list_windows",
        "find_dialog_window", "focused_desc", "is_vroid_focused", "launch",
        "kill", "active_workspace", "park", "enter", "leave",
        "dismiss_screensaver", "focus", "fullscreen", "notify",
        "primary_output", "capture_region", "run_pointer", "cursor_pos",
        "scroll", "type_text", "key", "input_focus_ok", "app_path",
        "save_dialog_enter_path", "helpers", "capture_window", "ui_scale",
    }
    for mod in (hyprland, macos):
        missing = names - set(dir(mod))
        assert not missing, f"{mod.BACKEND} lacks {sorted(missing)}"


# --- hyprland: pointer script rendering --------------------------------------

def test_render_script_matches_vpointer_protocol():
    ops = [("move", 10.4, 20.6), ("sleep", 12), ("down", "left"),
           ("move", 30, 40), ("up", "left"), ("click", "right", 1),
           ("click", "left", 2), ("scroll", -1)]
    assert hyprland.render_script(ops) == (
        "move 10 21\nsleep 12\ndown left\nmove 30 40\nup left\n"
        "click right\nclick left\nsleep 80\nclick left\nscroll -1\n")


def test_render_script_rejects_unknown_op():
    with pytest.raises(ValueError):
        hyprland.render_script([("teleport", 1, 2)])


def test_wine_path(tmp_path):
    p = tmp_path / "out" / "a.vrm"
    assert hyprland.app_path(p) == "Z:" + str(p.resolve()).replace("/", "\\")
    assert hyprland.app_path(p).startswith("Z:\\")


# --- macos: key mapping ------------------------------------------------------

@pytest.mark.parametrize("name, code, shift", [
    ("a", 0x00, False), ("A", 0x00, True), ("s", 0x01, False),
    ("Return", 0x24, False), ("enter", 0x24, False), ("BackSpace", 0x33, False),
    ("Escape", 0x35, False), ("Prior", 0x74, False), ("Next", 0x79, False),
    ("-", 0x1B, False), ("_", 0x1B, True), ("#", 0x14, True), (" ", 0x31, False),
    ("F", 0x03, True), ("5", 0x17, False),
])
def test_macos_keystroke(name, code, shift):
    assert macos.keystroke(name) == (code, shift)


def test_macos_keystroke_unknown():
    with pytest.raises(ValueError):
        macos.keystroke("é")
    with pytest.raises(ValueError):
        macos.keystroke("Hyper_L")


def test_macos_mod_flags():
    codes, flags = macos.mod_flags(["cmd", "shift"])
    assert codes == [0x37, 0x38]
    assert flags == macos.FLAG_CMD | macos.FLAG_SHIFT
    assert macos.mod_flags(["ctrl"])[1] == macos.FLAG_CTRL
    assert macos.mod_flags(["super"])[0] == [0x37]      # X11 name for Command
    with pytest.raises(ValueError):
        macos.mod_flags(["hyper"])


def test_macos_app_path_is_native(tmp_path):
    assert macos.app_path(tmp_path / "x.vrm") == str((tmp_path / "x.vrm").resolve())


# --- generic input: gestures are composed once, replayed by the backend -------

@pytest.fixture
def recorder(monkeypatch):
    """Load the generic driver on the hyprland backend with injection stubbed."""
    monkeypatch.setenv("MCP_VROID_BACKEND", "hyprland")
    for m in list(sys.modules):
        if m.startswith("mcp_vroid.driver"):
            monkeypatch.delitem(sys.modules, m)   # restored at teardown
    backends_mod = importlib.import_module("mcp_vroid.driver.backends")
    B = backends_mod.backend
    assert B.BACKEND == "hyprland"
    sent: dict = {"pointer": [], "keys": [], "text": [], "scroll": []}
    monkeypatch.setattr(B, "run_pointer", lambda ops, extent: sent["pointer"].append((ops, extent)))
    monkeypatch.setattr(B, "cursor_pos", lambda: (0.0, 0.0))
    monkeypatch.setattr(B, "key", lambda name, mods=None, times=1: sent["keys"].append((name, list(mods or []), times)))
    monkeypatch.setattr(B, "type_text", lambda text, delay_ms=22: sent["text"].append(text))
    monkeypatch.setattr(B, "scroll", lambda ticks, horizontal=False: sent["scroll"].append((ticks, horizontal)))
    from mcp_vroid.driver.backends.base import Output
    monkeypatch.setattr(B, "primary_output", lambda: Output(0, 0, 2048, 1152, 1.25))
    I = importlib.import_module("mcp_vroid.driver.input")
    I.set_safety(False)
    monkeypatch.setattr("time.sleep", lambda s: None)
    yield I, sent
    I.set_safety(True)
    # drop the hyprland-forced modules so later imports resolve the real backend
    for m in list(sys.modules):
        if m.startswith("mcp_vroid.driver"):
            del sys.modules[m]


def test_click_glides_then_clicks(recorder):
    I, sent = recorder
    I.click(90, 60, space="layout", moves=3, count=2, button="right")
    (ops, extent), = sent["pointer"]
    assert extent == (2048, 1152)
    moves = [op for op in ops if op[0] == "move"]
    assert [(round(x), round(y)) for _, x, y in moves] == [(30, 20), (60, 40), (90, 60)]
    assert ops[-1] == ("click", "right", 2)


def test_double_click_is_one_gesture(recorder):
    I, sent = recorder
    I.double_click(5, 5, space="layout")
    assert len(sent["pointer"]) == 1
    assert sent["pointer"][0][0][-1] == ("click", "left", 2)


def test_drag_holds_button_across_glide(recorder):
    I, sent = recorder
    I.drag(0, 0, 24, 0, space="layout", steps=4, button="middle")
    (ops, _), = sent["pointer"]
    kinds = [op[0] for op in ops]
    assert kinds.index("down") < kinds.index("up")
    assert ops[kinds.index("down")] == ("down", "middle")
    assert ops[-1] == ("up", "middle")
    xs = [op[1] for op in ops[kinds.index("down"):] if op[0] == "move"]
    assert xs == [6, 12, 18, 24]


def test_image_space_uses_shot_scale(recorder):
    I, sent = recorder
    from mcp_vroid.driver.capture import Shot
    shot = Shot.__new__(Shot)
    shot.ox, shot.oy, shot.scale = 100, 50, 2.0
    I.click(200, 100, space="image", shot=shot, moves=1)
    (ops, _), = sent["pointer"]
    assert ops[0] == ("move", 200.0, 100.0)   # 100 + 200/2, 50 + 100/2


def test_clear_field_and_hotkey_use_primary_modifier(recorder):
    I, sent = recorder
    I.clear_field()
    I.hotkey(f"{I.PRIMARY_MOD}+shift+s")
    assert sent["keys"] == [("a", [I.PRIMARY_MOD], 1), ("BackSpace", [], 1),
                            ("s", [I.PRIMARY_MOD, "shift"], 1)]
    assert I.PRIMARY_MOD == "ctrl"


def test_scroll_direction_passthrough(recorder):
    I, sent = recorder
    I.scroll(-3)
    I.hscroll(2)
    assert sent["scroll"] == [(-3, False), (2, True)]


# --- UI-point anchors: same points, different pixels per backend -----------

def _fake_shot(w: int, h: int, scale: float):
    from PIL import Image
    from mcp_vroid.driver.capture import Shot
    return Shot(Image.new("RGB", (w, h)), Path("/dev/null"), 0, 0, scale)


def test_anchors_scale_with_ui_scale(monkeypatch):
    from mcp_vroid.driver import actions as A
    mac_ui_scale = macos.ui_scale       # A._B may *be* macos: grab it before patching
    # Hyprland reference: 1 image px per UI point whatever the layout scale
    monkeypatch.setattr(A._B, "ui_scale", hyprland.ui_scale)
    s = _fake_shot(2560, 1440, 1.25)
    assert A._pt(s, *A.EXPORT_ICON) == (2560 - 96, 23)
    assert A._pt(s, A.PARAM_VALUE_X, 0)[0] == 2560 - 56
    assert A._pt(s, *A.CLOSE_X) == (23, 23)
    # Retina Mac: the same UI drawn at 2 px per point in a 2940x1790 window
    monkeypatch.setattr(A._B, "ui_scale", mac_ui_scale)
    s = _fake_shot(2940, 1790, 2.0)
    assert A._pt(s, *A.EXPORT_ICON) == (2940 - 192, 46)
    assert A._pt(s, A.PARAM_VALUE_X, 0)[0] == 2940 - 112   # measured: value text at x=2827
    assert A._ui(s, 24) == 48


def test_macos_capture_window_trims_title_bar(monkeypatch, tmp_path):
    """screencapture -l returns the window with its 28 pt title bar; the
    backend crops it so the image matches find_window()'s geometry."""
    from PIL import Image
    from mcp_vroid.driver.backends.base import Output, Window
    path = tmp_path / "w.png"
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        Image.new("RGB", (2940, 1846), "white").save(cmd[-1])
    monkeypatch.setattr(macos, "screen_recording_allowed", lambda request=False: True)
    monkeypatch.setattr(macos.subprocess, "run", fake_run)
    monkeypatch.setattr(macos, "primary_output", lambda: Output(0, 0, 1470, 956, 2.0))
    win = Window("13499", "VRoid Studio", "t", 0, 61, 1470, 895, "active-space", True, True)
    assert macos.capture_window(win, path) is True
    assert "-l" in calls[0] and "13499" in calls[0]
    assert Image.open(path).size == (2940, 1790)
    # Stage Manager thumbnail bounds: the image does not match, so decline
    # and let the caller focus + re-measure instead of mis-scaling
    tiny = Window("13499", "VRoid Studio", "t", 16, 657, 158, 158, "other-space", False, False)
    assert macos.capture_window(tiny, path) is False
    assert not path.exists()


def test_macos_modifiers_are_flags_changed(monkeypatch):
    """Unity only tracks Cmd/Shift from FlagsChanged events."""
    pytest.importorskip("Quartz")
    import Quartz
    posted = []
    monkeypatch.setattr(macos, "_post", lambda ev: posted.append(
        (Quartz.CGEventGetType(ev), Quartz.CGEventGetIntegerValueField(ev, Quartz.kCGKeyboardEventKeycode))))
    monkeypatch.setattr(macos.time, "sleep", lambda s: None)
    code, _ = macos.keystroke("s")
    mods, flags = macos.mod_flags(["cmd", "shift"])
    macos._tap(code, mods, flags)
    types = [t for t, _ in posted]
    assert types == [Quartz.kCGEventFlagsChanged] * 2 + [Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp] + [Quartz.kCGEventFlagsChanged] * 2
    assert [c for _, c in posted] == [0x37, 0x38, code, code, 0x38, 0x37]


@pytest.mark.parametrize("text", ["é", "ไทย", "😀", "𠮷", "A😀"])
def test_macos_unicode_event_round_trips(text):
    """Construct events without posting input to the desktop."""
    Quartz = pytest.importorskip("Quartz")
    event = macos._key_event(0, True, text=text)
    length, actual = Quartz.CGEventKeyboardGetUnicodeString(event, 32, None, None)
    assert actual == text
    assert length == len(text.encode("utf-16-le")) // 2
