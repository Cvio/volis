"""The test bench page. Qt offscreen, a temporary models
folder, stand-in recognizers and translators: nothing is loaded, no sound
device is opened."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading  # noqa: E402
import time  # noqa: E402
import wave  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402

from volis import audio, bench, perf  # noqa: E402
from volis.audio import SAMPLE_RATE  # noqa: E402

from test_bench import GOOD, PIECES, POOR, SAID, Listener  # noqa: E402
from test_models import CARD, QWEN, hf_folder, write_gguf  # noqa: E402
from test_perf import sample  # noqa: E402
from test_typed import Scripted  # noqa: E402

ES = "¿Dónde le duele?"
ANSWERS = {ES: "Where does it hurt?", "Buenos días.": "Good morning."}
CLIP = np.zeros(SAMPLE_RATE, np.float32)


@pytest.fixture
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from volis.config import Config, PythonConfig
    from volis.gui.app_window import AppWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio, "list_input_devices", lambda: [])
    monkeypatch.setattr(audio, "list_output_devices", lambda: [])
    monkeypatch.setattr(perf, "read_gpu", lambda: sample().gpu)
    mt = tmp_path / "models" / "mt"
    for folder in ("gemma-3-4b-it-GGUF", "aya-expanse-8b-GGUF"):
        (mt / folder).mkdir(parents=True)
        write_gguf(mt / folder / f"{folder[:-5]}-Q4_K_M.gguf", QWEN)
    asr = tmp_path / "models" / "asr"
    hf_folder(asr, "whisper-large-v3-turbo")  # says nothing about its languages: offered for all
    hf_folder(asr, "whisper-large-v3-turbo-es", README__md=CARD)  # its card says: Spanish
    (tmp_path / "models" / "tts").mkdir()
    config = Config()
    config.languages.source, config.languages.target = "es", "en"
    w = AppWindow(tmp_path, config, PythonConfig(), developer=True)
    w.save = lambda: None
    w.show()
    deadline = time.monotonic() + 10
    while not w.found and time.monotonic() < deadline:
        w.tick()
        time.sleep(0.01)
    yield w.dev
    w.pipeline = None
    w.close()


@pytest.fixture
def tb(window):
    """The test bench, with stand-in models: a good recognizer and a poor one,
    and translators that answer from a table."""
    from volis.gui.testbench import TestBench

    log: list[str] = []
    gate = threading.Event()  # cleared by a test that wants to look while a model is "loading"
    gate.set()

    def recognizer(e):
        gate.wait(5)
        return Listener(POOR if e.dir_name.endswith("-es") else GOOD, log=log, name=e.dir_name)

    def translator(e):
        gate.wait(5)
        return Scripted(ANSWERS, "cuda" if "gemma" in e.id else "cpu", log, e.id)

    worker = bench.Worker(None, None, None, load_recognizer=recognizer, load_translator=translator,
                          cut_fn=lambda sound: list(PIECES))
    window.test_bench = TestBench(window, worker)
    window.test_bench.log, window.test_bench.gate = log, gate
    window.test_bench.show()
    return window.test_bench


def settle(tb) -> None:
    deadline = time.monotonic() + 5
    while not tb.worker.idle() and time.monotonic() < deadline:
        time.sleep(0.01)
    tb.tick()


def tick_models(box, *names) -> None:
    for i in range(box.count()):
        item = box.item(i)
        item.setCheckState(Qt.CheckState.Checked if any(n in item.text() for n in names) else Qt.CheckState.Unchecked)


def names(parts) -> list[str]:
    return [view.card.name for view in parts["cards"]]


def states(steps) -> list[str]:
    return [step.state for step in steps]


class Running:
    """A conversation in progress, as far as the window can tell."""

    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


# ---------------------------------------------------------------- where it lives


def test_the_page_opens_the_bench_when_first_asked_for(window, monkeypatch):
    from volis.gui import developer

    made = []
    monkeypatch.setattr("volis.gui.testbench.bench.Worker",
                        lambda *a, **k: made.append(1) or SimpleNamespace(busy=False, status="", outcomes=__import__("queue").Queue(),
                                                                         close=lambda: None, cancel=lambda: None))
    assert window.test_bench is None, "nothing is made until it is asked for"
    window.window.rail_buttons[developer.TEST_BENCH].click()
    assert window.test_bench.isVisible() and made == [1]
    assert [window.test_bench.tabs.tabText(i) for i in range(3)] == ["Recognizers", "Translators", "Whole set"]


def test_the_lists_are_the_main_windows_models_and_languages(tb, window):
    assert tb.r_language.currentData() == "es" and tb.t_source.currentData() == "es" and tb.t_target.currentData() == "en"
    assert [tb.r_models.item(i).data(Qt.ItemDataRole.UserRole) for i in range(tb.r_models.count())] == [
        "whisper-large-v3-turbo-es", "whisper-large-v3-turbo"], "the one made for Spanish first"
    assert tb.t_models.count() == 2
    assert tb.t_recognizer.currentData() == window.recognizer.currentData()
    window.fill_pickers()  # a rescan
    assert tb.r_models.count() == 2 and tb.t_models.count() == 2


# ---------------------------------------------------------------- recognizers


def test_the_button_says_why_it_cannot_start_until_it_can(tb):
    assert not tb.r_run.isEnabled() and "Record something" in tb.r_reason.text()
    tb.r_sound.set_audio(CLIP, "a recording")
    assert not tb.r_run.isEnabled() and "at least one recognizer" in tb.r_reason.text()
    tick_models(tb.r_models, "turbo")
    assert tb.r_run.isEnabled() and tb.r_reason.text() == ""
    assert not tb.busy_bar.isVisibleTo(tb) and not tb.cancel_button.isVisibleTo(tb)


def test_recognizers_are_compared_scored_kept_and_one_can_be_used(tb, window, tmp_path):
    tb.r_sound.set_audio(CLIP, "a recording")
    tick_models(tb.r_models, "turbo")
    tb.r_reference.setPlainText(SAID)
    tb.gate.clear()  # the first model takes its time to load
    tb.r_run.click()
    assert tb.busy() and not tb.r_run.isEnabled(), "pressed once: it cannot be pressed again"
    assert tb.busy_bar.isVisibleTo(tb) and tb.cancel_button.isVisibleTo(tb)
    assert tb.busy_label.text().endswith("Nothing more to do: please wait.")
    assert not tb.t_run.isEnabled() and not tb.w_run.isEnabled(), "one job at a time, whichever tab it is on"
    tb.gate.set()
    settle(tb)
    assert not tb.busy() and not tb.busy_bar.isVisibleTo(tb) and tb.r_run.isEnabled()
    good, poor = tb.r["cards"]
    assert good.card.name == tb.r_models.item(1).text(), "the nearest to the correct text comes first"
    assert good.wrote[0].text() == "Buenos días. ¿Dónde le duele?" and good.card.best and not poor.card.best
    assert "Letters wrong 0.0%" in good.score.text() and good.score.isVisibleTo(tb)
    assert tb.log == ["closed whisper-large-v3-turbo-es", "closed whisper-large-v3-turbo"], "one at a time"
    assert "Spanish, a recording, 3.0 s of speech in 2 parts" in tb.r["earlier"].currentItem().text()
    assert "Letters wrong" in tb.r["note"].text() and SAID in tb.r["note"].text()
    assert bench.History.load(tmp_path).of(bench.RECOGNIZERS)[0].ids == ["whisper-large-v3-turbo-es", "whisper-large-v3-turbo"]
    # a card's button makes that model the conversation's recognizer
    window.recognizer.setCurrentIndex(window.recognizer.findData("whisper-large-v3-turbo-es"))
    tb.tick()
    assert poor.use.text() == "In use now" and not poor.use.isEnabled()
    good.use.click()
    assert window.recognizer.currentData() == "whisper-large-v3-turbo"
    assert "is now the conversation's recognizer" in tb.said.text()
    assert good.use.text() == "In use now" and poor.use.isEnabled()


def test_sound_with_no_speech_is_said_plainly(tb):
    tb.worker._cut = lambda sound: []
    tb.r_sound.set_audio(CLIP, "a recording")
    tick_models(tb.r_models, "turbo")
    tb.r_run.click()
    settle(tb)
    assert tb.said.text().startswith("No speech was found") and tb.r["cards"] == []


def test_a_clip_is_recorded_from_the_microphone_or_read_from_a_file(tb, tmp_path):
    stopped = []

    def spawn(device, out):
        out.put(np.full(SAMPLE_RATE, 0.2, np.float32))
        return SimpleNamespace(stop=lambda: stopped.append(True))

    tb.spawn_capture = spawn
    clip = tb.r_sound
    assert clip.record_button.text() == "Record" and not clip.play_button.isEnabled()
    clip.record_button.click()
    assert clip.recording() and clip.record_button.text() == "Stop recording" and not clip.file_button.isEnabled()
    assert "Stop recording" in tb.r_reason.text(), "nothing is compared while it records"
    tb.tick()
    assert clip.label.text().startswith("Recording... 1 s")
    clip.record_button.click()
    assert stopped == [True] and clip.has_sound() and clip.label.text() == "a recording, 1.0 s"
    assert clip.play_button.isEnabled()
    path = tmp_path / "talk.wav"
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((np.sin(np.arange(2 * SAMPLE_RATE) / 20) * 8000).astype("<i2").tobytes())
    clip.load_file(path)
    assert clip.label.text() == "talk.wav, 2.0 s" and len(clip.audio) == 2 * SAMPLE_RATE
    clip.load_file(tmp_path / "missing.wav")
    assert clip.label.text().startswith("That file could not be read")


# ---------------------------------------------------------------- one rule: not while a conversation runs


def test_while_a_conversation_runs_the_bench_says_so_once_and_offers_to_stop_it(tb, window):
    tb.r_sound.set_audio(CLIP, "a recording")
    tick_models(tb.r_models, "turbo")
    tb.t_text.setPlainText(ES)
    tick_models(tb.t_models, "Gemma")
    assert not tb.banner.isVisibleTo(tb) and tb.r_run.isEnabled() and tb.t_run.isEnabled() and tb.w_run.isEnabled()
    window.pipeline = Running()
    tb.tick()
    assert tb.banner.isVisibleTo(tb) and tb.banner.text() == bench.STOP_FIRST
    for button, reason in ((tb.r_run, tb.r_reason), (tb.t_run, tb.t_reason), (tb.w_run, tb.w_reason)):
        assert not button.isEnabled() and reason.text() == bench.STOP_FIRST
    tb.stop_button.click()
    assert window.pipeline.stopped
    window.pipeline = None
    tb.tick()
    assert not tb.banner.isVisibleTo(tb) and tb.r_run.isEnabled()


def test_a_conversation_cannot_start_while_the_bench_is_working(tb, window):
    tb.worker.busy = True
    w = window.window
    assert w.start_problem() == window.BENCH_BUSY
    w.start_button.click()
    assert w.pipeline is None
    w.refresh()
    assert w.start_note.text() == window.BENCH_BUSY and not w.start_button.isEnabled()
    tb.worker.busy = False


# ---------------------------------------------------------------- translators


def test_translators_are_compared_on_typed_text_with_scores(tb, window):
    tb.tabs.setCurrentIndex(1)
    assert tb.t_from_text.isChecked() and tb.t_text.isVisibleTo(tb) and not tb.t_sound_box.isVisibleTo(tb)
    assert "Type or paste" in tb.t_reason.text()
    tb.t_text.setPlainText(ES)
    assert "at least one translator" in tb.t_reason.text()
    tick_models(tb.t_models, "Gemma", "Aya")
    tb.t_reference.setPlainText("Where does it hurt?")
    tb.t_run.click()
    settle(tb)
    cards = tb.t["cards"]
    assert sorted(names(tb.t)) == sorted(tb.t_models.item(i).text() for i in range(2)), "named as in the list"
    assert all(c.wrote[0].text() == "Where does it hurt?" and c.score.text() == "Score 100.0" for c in cards)
    assert tb.t["tested"].text() == ES, "one sentence: said once, above the cards"
    assert not any(c.card.best for c in cards), "equal scores: neither is the closest"
    assert {"graphics card", "processor"} <= {fact for c in cards for fact in c.card.facts}
    assert "Spanish > English, typed, 1 line" in tb.t["earlier"].currentItem().text()
    assert "does not show that a translation is correct" in tb.t["note"].text()
    other = next(c for c in cards if c.use.isEnabled())
    other.use.click()
    assert window.translator.currentData() == other.card.ident
    from PySide6.QtGui import QGuiApplication

    tb.t["copy"].click()
    assert "| Text | Translator | Translation |" in QGuiApplication.clipboard().text()


def test_translators_are_compared_on_what_a_recognizer_hears(tb):
    tb.tabs.setCurrentIndex(1)
    tb.t_from_sound.setChecked(True)
    assert tb.t_sound_box.isVisibleTo(tb) and not tb.t_text.isVisibleTo(tb)
    tick_models(tb.t_models, "Gemma")
    assert "Record something" in tb.t_reason.text()
    tb.t_sound.set_audio(CLIP, "talk.wav")
    tb.t_recognizer.setCurrentIndex(tb.t_recognizer.findData("whisper-large-v3-turbo"))
    assert tb.t_run.isEnabled()
    tb.t_run.click()
    settle(tb)
    assert tb.t["cards"][0].card.lines == [("Buenos días.", "Good morning."), (ES, "Where does it hurt?")]
    assert tb.t["tested"].text() == "", "two sentences: each stays beside its translation"
    assert "talk.wav, as heard by" in tb.t["earlier"].currentItem().text()
    assert tb.log[0] == "closed whisper-large-v3-turbo", "the recognizer is released before a translator is loaded"


def test_cancel_stops_after_the_running_model(tb):
    tb.t_text.setPlainText(ES)
    tick_models(tb.t_models, "Gemma", "Aya")
    tb.gate.clear()
    tb.t_run.click()
    assert tb.busy()
    deadline = time.monotonic() + 5
    while not tb.worker.status.startswith("Loading") and time.monotonic() < deadline:
        time.sleep(0.01)  # the first translator is being loaded when Cancel is pressed
    tb.cancel_button.click()
    assert tb.busy_label.text().startswith("Stopping")
    tb.gate.set()
    settle(tb)
    assert not tb.busy() and tb.t_run.isEnabled()
    assert len(tb.log) == 1, "the translator that was loading finished; the second was never loaded"
    assert tb.busy_label.text() == ""


def test_the_last_comparison_is_there_when_the_bench_is_opened_again(tb, window):
    from volis.gui.testbench import TestBench

    tb.t_text.setPlainText(ES)
    tick_models(tb.t_models, "Gemma")
    tb.t_run.click()
    settle(tb)
    again = TestBench(window, tb.worker)
    assert names(again.t) == names(tb.t) and again.shown[bench.TRANSLATORS] is not None
    assert again.r["none"].isVisibleTo(again) and not again.r["earlier"].isVisibleTo(again)
    assert again.shown[bench.RECOGNIZERS] is None and again.r["stack"].currentIndex() == 0
    again._timer.stop()


# ---------------------------------------------------------------- knowing what to do next


def test_the_step_to_do_next_is_lit_and_the_answer_side_says_the_same(tb):
    assert states(tb.r_steps) == [bench.NOW, bench.LATER, bench.OPTIONAL, bench.LATER]
    assert tb.r["empty"].text() == tb.r_reason.text() and "Record something" in tb.r["empty"].text()
    tb.r_sound.set_audio(CLIP, "a recording")
    assert states(tb.r_steps) == [bench.DONE, bench.NOW, bench.OPTIONAL, bench.LATER]
    tick_models(tb.r_models, "turbo")
    assert states(tb.r_steps) == [bench.DONE, bench.DONE, bench.OPTIONAL, bench.NOW]
    assert tb.r["empty"].text().startswith("Ready.") and not tb.r_reason.isVisibleTo(tb)
    tb.r_reference.setPlainText(SAID)
    assert states(tb.r_steps)[2] == bench.DONE
    tb.tabs.setCurrentIndex(1)
    tb.t_text.setPlainText(ES)
    assert states(tb.t_steps)[:2] == [bench.DONE, bench.NOW]
    tb.t_from_sound.setChecked(True)
    assert states(tb.t_steps)[0] == bench.NOW, "the speech hasn't been given yet"


def test_clicking_anywhere_on_a_models_row_ticks_it(tb):
    from PySide6.QtTest import QTest

    box, item = tb.r_models, tb.r_models.item(0)
    box.resize(400, 200)
    QTest.mouseClick(box.viewport(), Qt.MouseButton.LeftButton, pos=box.visualItemRect(item).center())
    assert item.checkState() == Qt.CheckState.Checked
    QTest.mouseClick(box.viewport(), Qt.MouseButton.LeftButton, pos=box.visualItemRect(item).center())
    assert item.checkState() == Qt.CheckState.Unchecked


# ---------------------------------------------------------------- earlier comparisons


def compared(tb, words) -> None:
    tb.t_text.setPlainText(words)
    tick_models(tb.t_models, "Gemma")
    tb.t_run.click()
    settle(tb)


def test_earlier_comparisons_are_listed_found_and_shown_again(tb):
    compared(tb, ES)
    compared(tb, "Buenos días.")
    listed = tb.t["earlier"]
    assert listed.count() == 2 and listed.currentRow() == 0, "newest first, and it is the one shown"
    assert tb.t["tested"].text() == "Buenos días."
    listed.setCurrentRow(1)
    assert tb.t["tested"].text() == ES
    tb.t["search"].setText("nothing like this")
    assert listed.item(0).isHidden() and listed.item(1).isHidden()
    tb.t["search"].setText("spanish TYPED")
    assert not listed.item(0).isHidden() and not listed.item(1).isHidden()


def test_a_comparison_is_deleted_only_after_asking_and_stays_deleted(tb, tmp_path):
    tb.tabs.setCurrentIndex(1)
    compared(tb, ES)
    compared(tb, "Buenos días.")
    tb.t["delete"].click()
    assert tb.t["confirm"].isVisibleTo(tb) and tb.t["earlier"].count() == 2, "nothing is gone yet"
    tb.t["delete_no"].click()
    assert not tb.t["confirm"].isVisibleTo(tb) and tb.t["earlier"].count() == 2
    tb.t["delete"].click()
    tb.t["delete_yes"].click()
    assert tb.t["earlier"].count() == 1 and tb.t["tested"].text() == ES, "the next one takes its place"
    assert len(bench.History.load(tmp_path).of(bench.TRANSLATORS)) == 1
    tb.t["delete"].click()
    tb.t["delete_yes"].click()
    assert tb.shown[bench.TRANSLATORS] is None and tb.t["stack"].currentIndex() == 0 and tb.t["cards"] == []
    assert tb.t["none"].isVisibleTo(tb) and not tb.t["delete"].isVisibleTo(tb)
    assert bench.History.load(tmp_path).of(bench.TRANSLATORS) == []


# ---------------------------------------------------------------- whole set


def test_the_whole_set_tab_says_whether_a_set_fits_without_loading_it(tb, window):
    tb.sampler.history.append(sample())
    tb.fill_from_window()
    assert tb.w_asr.currentText() == window.recognizer.currentData()
    assert tb.w_mt.currentText() == window.translator.currentData()
    assert tb.verdict_label.text() and "Measuring" not in tb.verdict_label.text()
    assert tb.estimate_table.rowCount() == 2 and tb.log == [], "nothing was loaded"
    assert "have not been measured together" in tb.speed_label.text()
    # a run measured here shows in the table and in the speed line
    window.perf_panel.measured.run(perf.Run("2026-10-09 10:00", tb.w_asr.currentText(), tb.w_mt.currentText(), "turn",
                                            0.2, 400, None, 3, 0))
    tb.refresh_whole()
    assert tb.runs_table.rowCount() == 1 and "Measured in 1 run(s) here" in tb.speed_label.text()


def test_a_set_chosen_in_the_bench_can_be_used_in_the_conversation(tb, window):
    tb.fill_from_window()
    other_asr = next(tb.w_asr.itemText(i) for i in range(tb.w_asr.count()) if tb.w_asr.itemText(i) != tb.w_asr.currentText())
    other_mt = next(tb.w_mt.itemText(i) for i in range(1, tb.w_mt.count()) if tb.w_mt.itemText(i) != tb.w_mt.currentText())
    tb.w_asr.setCurrentText(other_asr)
    tb.w_mt.setCurrentText(other_mt)
    tb.w_apply.click()
    assert (window.recognizer.currentData(), window.translator.currentData()) == (other_asr, other_mt)
    assert tb.said.text().startswith("The conversation now uses: recognizer")
    window.pipeline = Running()
    tb.w_apply.click()
    assert tb.said.text() == bench.STOP_FIRST
