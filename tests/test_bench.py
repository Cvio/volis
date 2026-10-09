"""The test bench's work (volis/bench.py), with stand-in models: nothing is
loaded and no sound device is opened."""

import queue
import time
from types import SimpleNamespace

import numpy as np
import pytest

from volis import asr, bench
from volis.audio import SAMPLE_RATE

from test_typed import Scripted, entry

ES = "¿Dónde le duele?"
SAID = "buenos días dónde le duele"


class Listener:
    """A recognizer that answers by the length of what it is given."""

    def __init__(self, answers: dict[int, str], device: str = "cuda", log: list | None = None, name: str = "") -> None:
        self.answers, self.device, self.log, self.name = answers, device, log if log is not None else [], name
        self.asked: list[tuple[int, str, bool]] = []

    def transcribe(self, audio, language, timestamps=True):
        self.asked.append((len(audio), language, timestamps))
        if len(audio) not in self.answers:
            raise asr.AsrError("this one cannot")
        return asr.AsrResult(self.answers[len(audio)], None, None, language, 0.1)

    def memory(self):
        return asr.Memory(gpu_bytes=2_000_000_000 if self.device == "cuda" else 0,
                          cpu_bytes=0 if self.device == "cuda" else 500_000_000, device=self.device)

    def close(self) -> None:
        self.log.append(f"closed {self.name}")


def engine(folder: str, name: str = ""):
    return SimpleNamespace(dir_name=folder, name=name or folder)


PIECES = [np.zeros(SAMPLE_RATE, np.float32), np.zeros(2 * SAMPLE_RATE, np.float32)]  # 1 s and 2 s of "speech"
GOOD = {SAMPLE_RATE: "Buenos días.", 2 * SAMPLE_RATE: "¿Dónde le duele?"}
POOR = {SAMPLE_RATE: "Buenos tías.", 2 * SAMPLE_RATE: "¿Dónde duele?"}


# ---------------------------------------------------------------- recognizers


def test_each_recognizer_hears_the_same_pieces_one_loaded_at_a_time():
    log: list[str] = []

    def load(e):
        log.append(f"loaded {e.dir_name}")
        return Listener(GOOD if e.dir_name == "good" else POOR, "cuda" if e.dir_name == "good" else "cpu", log, e.dir_name)

    out = bench.hear(PIECES, "es", [engine("good", "Whisper"), engine("poor", "Small")], load, SAID)
    assert log == ["loaded good", "closed good", "loaded poor", "closed poor"], "never two at once"
    good, poor = out
    assert (good.name, good.text, good.device) == ("Whisper", "Buenos días. ¿Dónde le duele?", "cuda")
    assert good.parts == ["Buenos días.", "¿Dónde le duele?"]
    assert good.cer == 0.0 and good.wer == 0.0, "punctuation and capitals don't count"
    assert poor.cer > 0 and poor.wer > poor.cer, "a wrong letter is a whole wrong word"
    assert good.gpu_bytes == 2_000_000_000 and poor.cpu_bytes == 500_000_000
    assert good.rtf is not None and good.rtf < 1, "three seconds of speech, heard at once"


def test_without_the_correct_text_there_are_no_error_rates():
    out = bench.hear(PIECES, "es", [engine("a")], lambda e: Listener(GOOD))
    assert out[0].cer is None and out[0].wer is None and out[0].text


def test_a_recognizer_that_cannot_load_or_fails_is_reported_and_the_rest_go_on():
    def load(e):
        if e.dir_name == "broken":
            raise asr.AsrError("no such file")
        return Listener(GOOD if e.dir_name == "ok" else {})

    broken, failing, ok, silent = bench.hear(
        PIECES, "es", [engine("broken"), engine("failing"), engine("ok"), engine("silent")],
        lambda e: Listener({SAMPLE_RATE: "", 2 * SAMPLE_RATE: " "}) if e.dir_name == "silent" else load(e))
    assert broken.problem == "could not be loaded: no such file"
    assert failing.problem == "failed: this one cannot"
    assert ok.text and not ok.problem
    assert silent.problem == "it heard no words"


def test_stopping_loads_nothing_more():
    loaded = []

    def load(e):
        loaded.append(e.dir_name)
        return Listener(GOOD)

    out = bench.hear(PIECES, "es", [engine(c) for c in "abc"], load, cancelled=lambda: len(loaded) >= 1)
    assert loaded == ["a"] and len(out) == 1 and out[0].note == "stopped early"


def test_the_rows_say_speed_and_memory_in_plain_words():
    fast = bench.Heard("a", "Whisper", "hola", ms=500, rtf=0.25, device="cuda", gpu_bytes=1_600_000_000, cer=4.24, wer=12.0)
    slow = bench.Heard("b", "Big", "hola", ms=9000, rtf=1.5, device="cpu", cpu_bytes=700_000_000)
    bad = bench.Heard("c", "Broken", problem="could not be loaded: no")
    rows = bench.heard_rows([fast, slow, bad])
    assert rows[0] == ["Whisper", "hola", "500 ms", "4.0x faster than speech", "graphics card", "1.6 GB", "4.2%", "12.0%", ""]
    assert rows[1][3:6] == ["1.5x slower than speech", "processor", "0.7 GB"]
    assert rows[2][1] == "could not be loaded: no" and rows[2][2] == ""


def test_what_was_heard_becomes_the_sentences_a_translator_is_given():
    heard = bench.Heard("a", "A", parts=["Buenos días. ¿Dónde le duele?", "", "Aquí."])
    assert bench.lines_heard(heard) == ["Buenos días.", "¿Dónde le duele?", "Aquí."]


# ---------------------------------------------------------------- a recording


def test_a_recording_is_what_arrived_between_start_and_stop():
    stopped = []

    def spawn(device, out):
        out.put(np.full(1600, 0.1, np.float32))
        out.put(np.full(1600, 0.2, np.float32))
        return SimpleNamespace(stop=lambda: stopped.append(device))

    recorder = bench.Recorder(spawn)
    assert not recorder.recording()
    recorder.start("Headset")
    assert recorder.recording()
    level = recorder.poll()
    assert -15 < level < -13, "the level of the newest audio (0.2 is about -14 dB)"
    assert recorder.seconds() == pytest.approx(0.2)
    audio = recorder.stop()
    assert stopped == ["Headset"] and not recorder.recording()
    assert len(audio) == 3200 and audio.dtype == np.float32
    assert bench.level_db(np.zeros(0, np.float32)) == -120.0


# ---------------------------------------------------------------- can it start?


def test_the_reason_a_comparison_cannot_start_is_known_before_the_button_is_pressed():
    R, T = bench.RECOGNIZERS, bench.TRANSLATORS
    assert bench.ready(R, ticked=2, has_sound=True) == bench.Ready(True, "")
    assert "Record something" in bench.ready(R, ticked=2).message
    assert "at least one recognizer" in bench.ready(R, has_sound=True).message
    assert bench.ready(R, running=True, ticked=2, has_sound=True) == bench.Ready(False, bench.STOP_FIRST)
    assert "Stop recording" in bench.ready(R, recording=True, ticked=2).message
    assert bench.ready(R, busy=True, ticked=2, has_sound=True) == bench.Ready(False, ""), "the top line says what it is doing"
    # translators: from text, or from sound through a recognizer
    assert bench.ready(T, ticked=1, has_text=True, from_sound=False).enabled
    assert "Type or paste" in bench.ready(T, ticked=1, from_sound=False).message
    assert "at least one translator" in bench.ready(T, has_text=True, from_sound=False).message
    assert "Record something" in bench.ready(T, ticked=1, has_text=True, from_sound=True).message
    assert "Choose the recognizer" in bench.ready(T, ticked=1, has_sound=True, has_recognizer=False).message
    assert bench.ready(T, ticked=1, has_sound=True).enabled
    assert bench.ready("whole").enabled and not bench.ready("whole", running=True).enabled


# ---------------------------------------------------------------- kept


def test_comparisons_are_kept_newest_first_by_kind_and_survive_a_restart(tmp_path):
    history = bench.History.load(tmp_path)
    assert history.records == []
    a = bench.Record("2026-10-09 10:00", bench.RECOGNIZERS, "Spanish, a recording", ["Recognizer", "What it heard"],
                     [["Whisper", "hola"], ["MMS", "ola"]], ["whisper", "mms"])
    b = bench.Record("2026-10-09 10:05", bench.TRANSLATORS, "es > en, typed, 1 line", ["Text", "Translator"],
                     [["hola", "Gemma"]], ["gemma"], "note", "hello")
    history.add(a)
    history.add(b)
    again = bench.History.load(tmp_path)
    assert again.of(bench.RECOGNIZERS) == [a] and again.of(bench.TRANSLATORS) == [b]
    assert a.label() == "2026-10-09 10:00  Spanish, a recording  (2 models)"
    assert b.label().endswith("(1 model)")
    for n in range(bench.KEPT + 5):
        again.add(a)
    assert len(bench.History.load(tmp_path).records) == bench.KEPT


def test_a_damaged_history_file_is_reported_and_started_again(tmp_path, caplog):
    from volis import paths

    path = paths.test_bench_file(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert bench.History.load(tmp_path).records == [] and str(path.absolute()) in caplog.text


def test_a_comparison_as_a_table_to_paste():
    record = bench.Record("2026-10-09 10:00", bench.TRANSLATORS, "fa > en, typed, 1 line", ["Text", "Translation"],
                          [["a | b", "two\nlines"]], ["m"], reference="the reference")
    assert bench.markdown(record) == ("fa > en, typed, 1 line (2026-10-09 10:00)\n\n| Text | Translation |\n|---|---|\n"
                                      "| a \\| b | two lines |\n\nReference: the reference\n")


# ---------------------------------------------------------------- the thread


@pytest.fixture
def worker():
    made = []

    def make(recognizers=None, translators=None, pieces=PIECES, log=None):
        w = bench.Worker(None, None, None,
                         load_recognizer=lambda e: Listener((recognizers or {}).get(e.dir_name, GOOD), log=log, name=e.dir_name),
                         load_translator=lambda e: Scripted((translators or {}).get(e.id, {}), log=log, name=e.id),
                         cut_fn=lambda audio: list(pieces))
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()


def finish(w) -> bench.Outcome:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            return w.outcomes.get(timeout=0.05)
        except queue.Empty:
            continue
    raise AssertionError("the test bench never finished")


def test_the_worker_compares_recognizers_and_says_what_it_was_given(worker):
    w = worker({"poor": POOR})
    w.recognizers(np.zeros(10, np.float32), "Spanish, a recording", "es", [engine("good"), engine("poor")], SAID,
                  names={"good": "Whisper"})
    assert w.busy, "busy from the press"
    outcome = finish(w)
    record = outcome.record
    assert record.kind == bench.RECOGNIZERS and record.ids == ["good", "poor"]
    assert record.title == "Spanish, a recording, 3.0 s of speech in 2 parts"
    assert [row[0] for row in record.rows] == ["Whisper", "poor"]
    assert record.rows[0][6] == "0.0%" and record.note == bench.ERROR_NOTE and record.reference == SAID
    assert [h.engine for h in outcome.heard] == ["good", "poor"]
    assert w.idle() and w.status == ""


def test_sound_with_no_speech_in_it_is_said_plainly(worker):
    w = worker(pieces=[])
    w.recognizers(np.zeros(10, np.float32), "a recording", "es", [engine("good")])
    outcome = finish(w)
    assert outcome.record is None and outcome.problem.startswith("No speech was found")


def test_the_worker_compares_translators_on_typed_text(worker):
    w = worker(translators={"a": {ES: "Where does it hurt?"}, "b": {ES: "Where it hurts?"}})
    w.translators([ES], "Spanish > English, typed", "es", "en", [entry("a", "Gemma"), entry("b", "Aya")],
                  "Where does it hurt?", names={"a": "Gemma 3"})
    record = finish(w).record
    assert record.kind == bench.TRANSLATORS and record.ids == ["a", "b"]
    assert record.title == "Spanish > English, typed, 1 line"
    assert record.rows[0][:3] == [ES, "Gemma 3", "Where does it hurt?"] and record.rows[0][5] == "100.0"
    assert float(record.rows[1][5]) < 100 and record.note, "scored, so the note about the score is there"


def test_the_worker_compares_translators_on_what_a_recognizer_heard(worker):
    log: list[str] = []
    w = worker(translators={"a": {"Buenos días.": "Good morning.", ES: "Where does it hurt?"}}, log=log)
    w.translators([], "Spanish > English, a recording", "es", "en", [entry("a", "Gemma")],
                  audio=np.zeros(10, np.float32), recognizer=engine("good", "Whisper"))
    record = finish(w).record
    assert record.title == "Spanish > English, a recording, as heard by Whisper, 2 lines"
    assert [row[0] for row in record.rows] == ["Buenos días.", ES]
    assert [row[2] for row in record.rows] == ["Good morning.", "Where does it hurt?"]
    assert log == ["closed good", "closed a"], "the recognizer is released before the translator is loaded"


def test_cancelling_ends_the_job_and_empties_the_queue(worker):
    w = worker()
    w.recognizers(np.zeros(10, np.float32), "one", "es", [engine("good")])
    w.recognizers(np.zeros(10, np.float32), "two", "es", [engine("good")])
    w.cancel()
    deadline = time.monotonic() + 5
    while not w.idle() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert w.idle()
    outcomes = []
    while not w.outcomes.empty():
        outcomes.append(w.outcomes.get())
    assert len(outcomes) <= 1, "the second job never ran"
