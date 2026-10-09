"""Typing text into the window (P15). Qt offscreen, a temporary models
folder, scripted translators: no model is loaded."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from volis import audio, typed  # noqa: E402
from volis import events as ev  # noqa: E402

from test_models import QWEN, write_gguf  # noqa: E402
from test_typed import Scripted  # noqa: E402

ES, FA = "¿Dónde le duele?", "کجا درد می‌کند؟"
ANSWERS = {ES: "Where does it hurt?", "Buenos días.": "Good morning.", FA: "Where does it hurt?"}


@pytest.fixture
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from volis import paths
    from volis.config import Config, PythonConfig
    from volis.gui.window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio, "list_input_devices", lambda: [])
    monkeypatch.setattr(audio, "list_output_devices", lambda: [])
    monkeypatch.setattr(paths, "performance_file", lambda root: tmp_path / "performance.json")
    mt = tmp_path / "models" / "mt"
    for folder in ("gemma-3-4b-it-GGUF", "aya-expanse-8b-GGUF", "translategemma-4b-it-GGUF", "qwen3-8b-GGUF"):
        (mt / folder).mkdir(parents=True)
        write_gguf(mt / folder / f"{folder[:-5]}-Q4_K_M.gguf", QWEN)
    for role in ("asr", "tts"):
        (tmp_path / "models" / role).mkdir()
    config = Config()
    config.languages.source, config.languages.target = "es", "en"
    w = MainWindow(tmp_path, config, PythonConfig())
    w.save = lambda: None
    spoken, loads = [], []

    def load(entry):
        loads.append(entry.id)
        return Scripted(ANSWERS, "cuda" if "gemma" in entry.id else "cpu", name=entry.id)

    w.typed_worker = typed.Worker(tmp_path, w.pyconfig, w.typed_events, load=load,
                                  speak=lambda text, language: spoken.append((text, language)))
    w.spoken, w.loads = spoken, loads
    w.show()
    yield w
    w.pipeline = None
    w.perf_panel.sampler.stop()
    w.close()


def settle(window) -> None:
    deadline = time.monotonic() + 5
    while not window.typed_worker.idle() and time.monotonic() < deadline:
        time.sleep(0.01)
    window.tick()


def rows(table) -> list[list[str]]:
    return [[table.item(r, c).text() for c in range(table.columnCount())] for r in range(table.rowCount())]


def test_enter_translates_and_the_row_is_marked_typed(window):
    window.typed_text.setPlainText(ES)
    window.typed_text.setFocus()
    QTest.keyClick(window.typed_text, Qt.Key.Key_Return)
    settle(window)
    assert window.typed_text.toPlainText() == "", "the box is cleared for the next one"
    got = rows(window.table)
    assert got[0][:3] == ["typed", ES, "Where does it hurt?"]
    assert window.session.lines[0].typed
    assert window.spoken == [("Where does it hurt?", "en")], "Speak translations applies to typed text"


def test_shift_enter_is_a_new_line_and_each_line_becomes_its_own_row(window):
    window.speak.setChecked(False)
    window.typed_text.setFocus()
    QTest.keyClicks(window.typed_text, "Buenos dias")
    QTest.keyClick(window.typed_text, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert window.typed_text.toPlainText() == "Buenos dias\n", "nothing was sent"
    assert window.table.rowCount() == 0
    window.typed_text.setPlainText(f"Buenos días.\n\n{ES}")
    window.typed_button.click()
    settle(window)
    assert [r[1] for r in rows(window.table)] == ["Buenos días.", ES]
    assert [r[2] for r in rows(window.table)] == ["Good morning.", "Where does it hurt?"]
    assert window.spoken == [], "not spoken when Speak translations is off"
    assert window.loads == ["gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf"] or len(window.loads) == 1


def test_a_typed_row_is_logged_with_the_rest_for_export(window):
    window.typed_text.setPlainText(ES)
    window.submit_typed()
    settle(window)
    kinds = [type(e).__name__ for e in window.collected.events]
    assert kinds == ["SentenceMsg", "Translated"]
    assert window.collected.events[0].typed


class RunningPipeline:
    def __init__(self) -> None:
        self.typed: list = []

    def translate_typed(self, lines) -> None:
        self.typed.append(list(lines))


def test_while_a_conversation_runs_it_translates_the_typed_text_itself(window):
    window.session.begin("es", "en", False, True, False)
    window.pipeline = RunningPipeline()
    window.session.apply(ev.Listening())
    window.typed_text.setPlainText(f"{ES}\nBuenos días.")
    window.submit_typed()
    assert window.pipeline.typed == [[ES, "Buenos días."]]
    assert window.loads == [], "the translator isn't loaded a second time"


def test_a_space_typed_in_the_box_is_not_a_turn(window):
    window.mode_turn.setChecked(True)
    window.session.begin("es", "en", False, True, False)
    window.session.mode = "turn"
    window.pipeline = RunningPipeline()
    window.session.apply(ev.Listening())
    presses = []
    window.turn_key_event = lambda edges: presses.append(edges)
    window.activateWindow()
    window.typed_text.setFocus()
    QTest.keyClicks(window.typed_text, "a b")
    assert window.typed_text.toPlainText() == "a b" and presses == []
