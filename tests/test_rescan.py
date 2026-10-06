"""Rescan (P13): models and devices read again without restarting. The plain
lines (volis/gui/rescan.py, no Qt), then the window against a temporary
models folder. No model is loaded."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from volis import audio  # noqa: E402
from volis.gui import rescan  # noqa: E402
from volis.gui.rescan import Item  # noqa: E402

from test_models import PARAKEET, PARAKEET_FILES, QWEN, model, write_gguf  # noqa: E402


def snap(**kinds) -> dict:
    return {kind: kinds.get(kind, []) for kind in rescan.KINDS}


def test_what_is_new_gone_broken_and_working_again_is_said_plainly():
    before = snap(recognizer=[Item("a", "Whisper A"), Item("b", "Whisper B"), Item("c", "Whisper C", False, "missing: x")],
                  microphone=[Item("Mic", "Mic")])
    after = snap(recognizer=[Item("a", "Whisper A", False, "missing: tokens.txt"), Item("c", "Whisper C"),
                             Item("d", "Whisper D")],
                 microphone=[Item("Mic", "Mic"), Item("Headset", "Headset")])
    assert rescan.compare(before, after) == [
        "New recognizer: Whisper D.",
        "No longer there: the recognizer Whisper B.",
        "Can't be used any more: the recognizer Whisper A (missing: tokens.txt).",
        "Works now: the recognizer Whisper C.",
        "New microphone: Headset.",
    ]
    assert rescan.compare(before, before) == []


def test_a_new_folder_that_is_broken_says_why():
    after = snap(translator=[Item("bad", "bad", False, "not a GGUF file")])
    assert rescan.compare(snap(), after) == ["New translator, but it can't be used: bad (not a GGUF file)."]


def test_the_line_for_a_choice_that_had_to_change():
    assert rescan.selection_line("recognizer", "Whisper B", "Whisper A", "the best match for Spanish") == (
        "The recognizer you had chosen (Whisper B) is gone; now using Whisper A (the best match for Spanish).")
    assert rescan.selection_line("speakers", "Headset", "the system default", "Windows' default") == (
        "The speakers you had chosen (Headset) are gone; now using the system default (Windows' default).")
    assert rescan.selection_line("translator", "Gemma", "") == (
        "The translator you had chosen (Gemma) is gone; nothing else can take its place.")
    running = rescan.selection_line("recognizer", "B", "A", running=True)
    assert "keeps what it loaded" in running and "next Start" in running


def test_the_fallback_translator_is_the_preferred_one_or_the_first_that_works():
    items = [Item("x", "X", False, "broken"), Item("y", "Y"), Item("z", "Z")]
    assert rescan.first_usable(items) == "y"
    assert rescan.first_usable(items, prefer="z") == "z"
    assert rescan.first_usable(items, prefer="x") == "y", "the preferred one doesn't work"
    assert rescan.first_usable([]) == ""


# ---------------------------------------------------------------- the window


@pytest.fixture
def window(tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication

    from volis import paths, perf
    from volis.config import Config, PythonConfig
    from volis.gui.window import MainWindow

    QApplication.instance() or QApplication([])
    devices = {"in": [audio.Device("Laptop microphone", True, None)], "out": [audio.Device("Laptop speakers", True, None)]}
    monkeypatch.setattr(audio, "list_input_devices", lambda: list(devices["in"]))
    monkeypatch.setattr(audio, "list_output_devices", lambda: list(devices["out"]))
    monkeypatch.setattr(perf, "read_gpu", lambda: None)
    monkeypatch.setattr(paths, "performance_file", lambda root: tmp_path / "performance.json")
    asr = tmp_path / "models" / "asr"
    model(asr, "parakeet-one", PARAKEET, PARAKEET_FILES)
    mt = tmp_path / "models" / "mt"
    mt.mkdir(parents=True)
    write_gguf(mt / "small.gguf", QWEN)
    (tmp_path / "models" / "tts").mkdir()
    config = Config()
    config.asr.engine = "parakeet-one"
    w = MainWindow(tmp_path, config, PythonConfig())
    w.save = lambda: None  # a test never writes settings
    w.devices = devices
    yield w
    w.perf_panel.sampler.stop()
    w.close()


def ids(combo) -> list[str]:
    return [combo.itemData(i) for i in range(combo.count())]


def test_a_model_folder_added_then_renamed_appears_then_disappears(window, tmp_path):
    asr = tmp_path / "models" / "asr"
    assert ids(window.recognizer) == ["parakeet-one"] and not window.notice.isVisible()

    model(asr, "parakeet-two", PARAKEET.replace("Parakeet TDT 0.6B v3 (int8)", "Second Parakeet"), PARAKEET_FILES)
    window.rescan()
    assert set(ids(window.recognizer)) == {"parakeet-one", "parakeet-two"}
    assert window.notice.text() == "New recognizer: Second Parakeet."
    assert window.recognizer.currentData() == "parakeet-one", "the choice is kept"

    window.recognizer.setCurrentIndex(window.recognizer.findData("parakeet-two"))
    window.config.asr.engine = "parakeet-two"
    (asr / "parakeet-two").rename(asr / "parakeet-renamed")
    window.rescan()
    assert set(ids(window.recognizer)) == {"parakeet-one", "parakeet-renamed"}
    text = window.notice.text()
    assert "No longer there: the recognizer Second Parakeet." in text
    assert "The recognizer you had chosen (Second Parakeet) is gone; now using" in text and "best match" in text
    assert window.recognizer.currentData() in ("parakeet-one", "parakeet-renamed")


def test_a_broken_folder_is_listed_greyed_out_with_its_reason(window, tmp_path):
    bad = tmp_path / "models" / "asr" / "half-copied"
    bad.mkdir()
    (bad / "engine.toml").write_text('name = "Half"\nkind = "segment"\nbackend = "no-such-backend"\n', encoding="utf-8")
    window.rescan()
    index = window.recognizer.findData("half-copied")
    assert index >= 0 and not window.recognizer.model().item(index).isEnabled()
    assert "no-such-backend" in window.recognizer.itemData(index, 3)  # Qt.ToolTipRole
    assert "it can't be used" in window.notice.text()
    assert window.recognizer.currentData() == "parakeet-one"


def test_a_headset_plugged_in_appears_in_both_device_lists(window):
    window.devices["in"].append(audio.Device("Headset microphone", False, None))
    window.devices["out"].append(audio.Device("Headset earphones", False, None))
    window.rescan()
    assert "Headset microphone" in ids(window.input_device) and "Headset earphones" in ids(window.output_device)
    assert window.notice.text() == "New microphone: Headset microphone.\nNew speakers: Headset earphones."

    window.input_device.setCurrentIndex(window.input_device.findData("Headset microphone"))
    window.config.audio.input_device = "Headset microphone"
    window.devices["in"].pop()
    window.rescan()
    assert window.input_device.currentData() == "", "back to Windows' default"
    assert "The microphone you had chosen (Headset microphone) is gone; now using the system default" in window.notice.text()


def test_a_translator_that_is_gone_is_replaced_by_one_that_works(window, tmp_path):
    mt = tmp_path / "models" / "mt"
    (mt / "extra").mkdir()
    write_gguf(mt / "extra" / "extra.gguf", QWEN)
    window.rescan()
    assert "extra/extra.gguf" in ids(window.translator)
    window.translator.setCurrentIndex(window.translator.findData("extra/extra.gguf"))
    window.pyconfig.translate.model = "extra/extra.gguf"
    (mt / "extra" / "extra.gguf").unlink()
    (mt / "extra").rmdir()
    window.rescan()
    assert window.translator.currentData() == "small.gguf"
    assert "The translator you had chosen" in window.notice.text()


def test_nothing_changed_is_said_too_and_f5_is_the_shortcut(window):
    window.rescan()
    assert window.notice.text() == "Rescanned: nothing has changed." and window.notice.isVisibleTo(window)
    actions = [a for menu in window.menuBar().actions() for a in menu.menu().actions()]
    assert any(a.shortcut().toString() == "F5" and "Rescan" in a.text() for a in actions)


def test_while_running_the_lists_update_and_the_note_says_the_change_waits(window, tmp_path, monkeypatch):
    monkeypatch.setattr(window, "running", lambda: True)
    asr = tmp_path / "models" / "asr"
    (asr / "parakeet-one").rename(asr / "parakeet-moved")
    window.rescan()
    assert ids(window.recognizer) == ["parakeet-moved"]
    assert "keeps what it loaded" in window.notice.text() and "next Start" in window.notice.text()
