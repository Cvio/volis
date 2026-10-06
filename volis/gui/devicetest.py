"""The Test buttons (P14): does the user hear Volis, and does Volis hear the
user? No Qt here; the window runs these on a thread and shows what `say`
reports.

Test speakers says one short sentence in the target language through the
chosen speakers and the voice that would speak it. Test microphone records
three seconds, plays them back, and shows what the chosen recognizer heard.
"""

from __future__ import annotations

import queue
import time

import numpy as np

from .. import audio, models
from ..audio import SAMPLE_RATE
from . import view

RECORD_SECONDS = 3.0
QUIET_DBFS = -50.0  # a recording whose loudest moment is below this has no voice in it


def _name(engine) -> str:
    return view.plain_name(getattr(engine, "named", True), engine.name, engine.dir_name)


def level_db(samples: np.ndarray) -> float:
    """The loudest moment of some audio, in dBFS (0 = as loud as it can be)."""
    peak = float(np.abs(samples).max()) if len(samples) else 0.0
    return 20 * float(np.log10(peak)) if peak > 0 else -120.0


def _play(samples: np.ndarray, rate: int, device: str) -> None:
    from .. import playback

    player = playback.Player(device, playback.Gate(enabled=False))
    try:
        player.play(samples, rate)
        deadline = time.monotonic() + len(samples) / rate + 3
        while player.queued() > 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.15)  # the sound card's own buffer
    finally:
        player.close()


def speakers(voices: list[models.Engine], language: str, device: str, say, play=_play) -> bool:
    """Say a test sentence. `say(text)` is told what is happening and how it
    ended. True when a sentence was played."""
    from .. import tts, varieties

    sentence = view.test_sentence(language)
    if not sentence:
        say(f"There is no test sentence for {varieties.display_name(language)} yet. Start a conversation to "
            "hear its voice.")
        return False
    try:
        engine = tts.for_language(voices, language)
    except tts.TtsError:
        say(f"No voice is installed for {varieties.display_name(language)}, so translations into it can be shown "
            "but not spoken.")
        return False
    try:
        say(f"Loading the voice {_name(engine)}...")
        speech = tts.Voice(engine).speak(sentence)
        say(f"Playing: \"{sentence}\"")
        play(speech.samples, speech.sample_rate, device)
    except Exception as e:  # the reason is the result
        say(f"The speakers test failed: {e}")
        return False
    say(f"Played \"{sentence}\" with the voice {_name(engine)}. If you didn't hear it, choose other speakers.")
    return True


def record(device: str, seconds: float, on_level, spawn=audio.spawn_capture) -> np.ndarray:
    """`seconds` of the microphone, as 16 kHz mono. `on_level(db, left)` is
    called with each chunk's level and the seconds still to go."""
    chunks: queue.Queue = queue.Queue()
    wanted, got, parts = int(seconds * SAMPLE_RATE), 0, []
    handle = spawn(device, chunks)
    try:
        deadline = time.monotonic() + seconds + 5
        while got < wanted and time.monotonic() < deadline:
            try:
                chunk = chunks.get(timeout=0.5)
            except queue.Empty:
                continue
            parts.append(chunk)
            got += len(chunk)
            on_level(level_db(chunk), max(0.0, (wanted - got) / SAMPLE_RATE))
    finally:
        handle.stop()
    return np.concatenate(parts)[:wanted] if parts else np.zeros(0, np.float32)


def microphone(engine: models.Engine | None, language: str, input_device: str, output_device: str, say,
               on_level=lambda db, left: None, record_fn=record, play=_play, load=None) -> str:
    """Record three seconds, play them back, and report what the recognizer
    heard. Returns the text heard ("" when nothing was)."""
    from .. import asr as asr_pkg

    try:
        say("Recording for 3 seconds: say something now.")
        samples = record_fn(input_device, RECORD_SECONDS, on_level)
    except Exception as e:
        say(f"The microphone could not be opened: {e}")
        return ""
    loudest = level_db(samples)
    if len(samples) == 0 or loudest < QUIET_DBFS:
        say(f"Nothing was heard: the loudest sound was {loudest:.0f} dBFS, which is near silence. Is the "
            "microphone muted, or is another microphone the one you are speaking into?")
        return ""
    try:
        say("Playing it back...")
        play(samples, SAMPLE_RATE, output_device)
    except Exception as e:
        say(f"Recorded, but it could not be played back: {e}")
    if engine is None:
        say(f"Recorded and played back (loudest sound {loudest:.0f} dBFS). Choose a recognizer to see what it hears.")
        return ""
    recognizer = None
    try:
        say(f"Loading the recognizer {_name(engine)}...")
        recognizer = (load or asr_pkg.load)(engine)
        heard = recognizer.transcribe(samples, language, False).text.strip()
    except Exception as e:
        say(f"Recorded and played back, but the recognizer failed: {e}")
        return ""
    finally:
        if recognizer is not None and hasattr(recognizer, "close"):
            recognizer.close()
    if any(c.isalnum() for c in heard):  # a lone full stop is not something heard
        say(f"The recognizer heard: \"{heard}\"")
        return heard
    say(f"Recorded and played back (loudest sound {loudest:.0f} dBFS), but the recognizer heard no words. "
        "Speak closer to the microphone.")
    return ""
