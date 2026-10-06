"""The Test buttons (P14): volis/gui/devicetest.py with a fake microphone,
fake speakers and a fake recognizer. No device is opened and no model loaded."""

from types import SimpleNamespace

import numpy as np

from volis.gui import devicetest

RATE = 16_000


def voice_like(seconds: float = 3.0, level: float = 0.2) -> np.ndarray:
    t = np.arange(int(seconds * RATE)) / RATE
    return (level * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


class Log:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str) -> None:
        self.lines.append(text)

    @property
    def last(self) -> str:
        return self.lines[-1]


def recognizer(text: str):
    closed = []
    return SimpleNamespace(transcribe=lambda audio, language, timestamps=True: SimpleNamespace(text=text),
                           close=lambda: closed.append(True), closed=closed)


ENGINE = SimpleNamespace(name="Whisper turbo", dir_name="whisper")


def test_the_level_of_silence_and_of_a_voice():
    assert devicetest.level_db(np.zeros(100, np.float32)) == -120.0
    assert -15 < devicetest.level_db(voice_like()) < -13
    assert devicetest.level_db(np.zeros(0, np.float32)) == -120.0


def test_the_microphone_test_records_plays_back_and_says_what_was_heard():
    log, played, levels = Log(), [], []
    fake = recognizer("  Hello, can you hear me?  ")

    def record(device, seconds, on_level):
        on_level(-14.0, 2.0)
        return voice_like(seconds)

    heard = devicetest.microphone(ENGINE, "en", "Mic", "Speakers", log, lambda db, left: levels.append((db, left)),
                                  record_fn=record, play=lambda s, r, d: played.append((len(s), r, d)),
                                  load=lambda engine: fake)
    assert heard == "Hello, can you hear me?"
    assert log.lines[0].startswith("Recording for 3 seconds")
    assert log.last == 'The recognizer heard: "Hello, can you hear me?"'
    assert played == [(3 * RATE, RATE, "Speakers")] and levels == [(-14.0, 2.0)]
    assert fake.closed == [True], "the recognizer is released afterwards"


def test_a_silent_recording_says_so_and_loads_nothing():
    log, loaded = Log(), []
    heard = devicetest.microphone(ENGINE, "en", "", "", log, record_fn=lambda d, s, on: voice_like(s, level=0.0001),
                                  play=lambda *a: loaded.append("played"), load=lambda e: loaded.append("loaded"))
    assert heard == "" and loaded == []
    assert "Nothing was heard" in log.last and "dBFS" in log.last and "muted" in log.last


def test_a_microphone_that_cannot_be_opened_is_reported_not_raised():
    log = Log()

    def broken(device, seconds, on_level):
        raise OSError("device unplugged")

    assert devicetest.microphone(ENGINE, "en", "", "", log, record_fn=broken) == ""
    assert log.last == "The microphone could not be opened: device unplugged"


def test_a_recognizer_that_hears_no_words_or_fails_is_explained():
    log = Log()
    kwargs = dict(record_fn=lambda d, s, on: voice_like(s), play=lambda *a: None)
    assert devicetest.microphone(ENGINE, "en", "", "", log, load=lambda e: recognizer(""), **kwargs) == ""
    assert "heard no words" in log.last

    def cannot_load(engine):
        raise RuntimeError("not enough memory")

    devicetest.microphone(ENGINE, "en", "", "", log, load=cannot_load, **kwargs)
    assert log.last == "Recorded and played back, but the recognizer failed: not enough memory"
    devicetest.microphone(None, "en", "", "", log, **kwargs)
    assert "Choose a recognizer" in log.last


def test_recording_stops_at_three_seconds_and_reports_the_level(monkeypatch):
    stopped = []

    def spawn(device, out):
        for _ in range(40):  # 4 seconds, in 100 ms chunks: more than is wanted
            out.put(voice_like(0.1))
        return SimpleNamespace(stop=lambda: stopped.append(True))

    levels = []
    samples = devicetest.record("Mic", 3.0, lambda db, left: levels.append(left), spawn=spawn)
    assert len(samples) == 3 * RATE and stopped == [True]
    assert levels[0] > 2.5 and levels[-1] == 0.0


def test_the_speakers_test_says_a_sentence_in_the_target_language(monkeypatch):
    from volis import tts

    log, played = Log(), []
    engine = SimpleNamespace(name="Piper es_MX", dir_name="voice-es")
    monkeypatch.setattr(tts, "for_language", lambda voices, language: engine)
    monkeypatch.setattr(tts, "Voice", lambda e: SimpleNamespace(
        speak=lambda text: SimpleNamespace(samples=np.zeros(100, np.float32), sample_rate=22_050)))
    assert devicetest.speakers([engine], "es-MX", "Headset", log, play=lambda s, r, d: played.append((r, d)))
    assert played == [(22_050, "Headset")]
    assert "Esta es una prueba de los altavoces." in log.last and "Piper es_MX" in log.last


def test_no_voice_for_the_language_is_said_plainly(monkeypatch):
    from volis import tts

    def none(voices, language):
        raise tts.TtsError("no installed voice")

    monkeypatch.setattr(tts, "for_language", none)
    log = Log()
    assert not devicetest.speakers([], "fa", "", log, play=lambda *a: None)
    assert log.last.startswith("No voice is installed for Persian") and "shown but not spoken" in log.last
