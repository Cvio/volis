"""A conversation's audio: what each person said and what Volis spoke. The
pipeline's threads add to it; the window reads it. No Qt and no sound device.

Kept as 16-bit samples, half the size of the 32-bit ones the pipeline works in:
an hour of speech is about 115 MB.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .audio import SAMPLE_RATE


@dataclass(frozen=True)
class Clip:
    samples: np.ndarray  # int16, mono
    rate: int

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate

    def floats(self, start: float = 0.0) -> np.ndarray:
        """From `start` seconds on, as the player wants it."""
        return self.samples[int(start * self.rate):].astype(np.float32) / 32767.0


ORIGINAL, TRANSLATION = "original", "translation"


def _compact(samples: np.ndarray) -> np.ndarray:
    return (np.clip(np.asarray(samples, np.float32), -1.0, 1.0) * 32767.0).astype(np.int16)


def _same_words(text: str) -> str:
    """The wire tidies the spaces in what it carries."""
    return " ".join(text.split())


def remote_key(language: str, text: str) -> str:
    """What the other computer sent has no sentence id here: its words name it.
    The same words twice are the same speech, so that loses nothing."""
    return f"remote:{language}:{text}"


class Clips:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spoken: dict[str, Clip] = {}
        self._heard: dict[int, tuple[float, Clip]] = {}  # utterance -> where it starts, its audio
        self._received: dict[tuple[str, str], Clip] = {}  # from the other computer: (track, translation's words)

    def put_spoken(self, key: str, samples: np.ndarray, rate: int) -> None:
        clip = Clip(_compact(samples), rate)
        with self._lock:
            self._spoken[key] = clip

    def put_heard(self, utterance: int, start: float, samples: np.ndarray) -> None:
        """An utterance, `start` seconds into the conversation's timeline."""
        clip = Clip(_compact(samples), SAMPLE_RATE)
        with self._lock:
            self._heard[utterance] = (start, clip)

    def put_received(self, track: str, text: str, raw: bytes, rate: int) -> None:
        """What the other computer has and this one doesn't, when a conversation ends."""
        clip = Clip(np.frombuffer(raw, "<i2"), rate)
        with self._lock:
            self._received[(track, _same_words(text))] = clip

    def received(self, track: str, text: str) -> Clip | None:
        with self._lock:
            return self._received.get((track, _same_words(text)))

    def spoken(self, key: str) -> Clip | None:
        with self._lock:
            return self._spoken.get(key)

    def original(self, utterance: int, start: float, end: float) -> Clip | None:
        """One sentence's part of what was heard. The times are the sentence's,
        on the same timeline as the utterance's start."""
        with self._lock:
            found = self._heard.get(utterance)
        if found is None:
            return None
        begins, clip = found
        first, last = (int(max(0.0, t - begins) * clip.rate) for t in (start, end))
        part = clip.samples[first:last]
        return Clip(part, clip.rate) if len(part) else clip


class Replay:
    """Playing one clip through a `playback.Player`, for the shared bar. How far
    it has got comes from how much the player has left.

    During a conversation the player is the conversation's own, so this never
    holds its queue. Pausing takes the clip back out and remembers the place:
    held audio would hold up the next sentence too."""

    def __init__(self) -> None:
        self.key = ""
        self.clip: Clip | None = None
        self.player = None
        self.paused_at: float | None = None
        self.finished = False  # played to its end; play starts it again

    def active(self) -> bool:
        return self.clip is not None

    @property
    def paused(self) -> bool:
        return self.paused_at is not None

    def playing(self) -> bool:
        return self.clip is not None and not self.paused and not self.finished

    def play(self, key: str, clip: Clip, player) -> None:
        self.stop()
        self.key, self.clip, self.player = key, clip, player
        self._from(0.0)

    def _from(self, start: float) -> None:
        self.player.clear()
        self.paused_at, self.finished = None, False
        self.player.play(self.clip.floats(start), self.clip.rate)

    def position(self) -> float:
        if self.clip is None:
            return 0.0
        if self.paused_at is not None:
            return self.paused_at
        if self.finished:
            return self.clip.seconds
        left = self.player.queued() / self.player.device_rate
        return max(0.0, self.clip.seconds - left)

    def toggle(self) -> None:
        """The bar's play and pause button."""
        if self.clip is None:
            return
        if self.finished:
            self._from(0.0)
        elif self.paused_at is not None:
            self._from(self.paused_at)
        else:
            self.paused_at = self.position()
            self.player.clear()

    def seek(self, seconds: float) -> None:
        if self.clip is None:
            return
        place = min(max(0.0, seconds), self.clip.seconds)
        if self.paused_at is not None:
            self.paused_at = place
        else:
            self._from(place)

    def update(self) -> None:
        """Every so often: has it played to its end?"""
        if self.playing() and self.player.queued() == 0:
            self.finished = True

    def stop(self) -> None:
        """Stop it and forget it. What it had queued goes; the player carries on."""
        if self.playing():
            self.player.clear()
        self.forget()

    def forget(self) -> None:
        """Stop following it, leaving the player alone: a new sentence has just
        been queued behind it, and must not be cleared with it."""
        self.key, self.clip, self.player, self.paused_at, self.finished = "", None, None, None, False
