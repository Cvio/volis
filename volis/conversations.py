"""Saved conversations (`volis-ui-plan.md`, U4). No Qt in this file.

An ordinary folder inside Volis, one folder per conversation:

    conversations\\2026-10-31 14-05 Menu\\
        conversation.json   everything needed to show it again
        conversation.txt    the same words, for reading anywhere
        audio\\0001-original.wav, 0001-translation.wav, ...

While a conversation runs it is kept up to date in conversations\\in-progress,
so a crash loses at most the last moments. Whatever is found there when Volis
opens is moved to an ordinary conversation, marked as recovered.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import paths
from .clips import Clip, Clips

log = logging.getLogger(__name__)

VERSION = 1
JSON_NAME, TEXT_NAME, AUDIO_DIR = "conversation.json", "conversation.txt", "audio"
ORIGINAL, TRANSLATION = "original", "translation"
RECOVERED_NAME = "Recovered conversation"
LEFT, RIGHT = "left", "right"


class ConversationError(Exception):
    pass


@dataclass
class Conversation:
    folder: Path
    name: str = ""
    created: str = ""
    languages: tuple[str, str] = ("", "")
    way: str = ""
    speakers: dict[str, str] = field(default_factory=dict)  # by side; a side not here shows its language
    lines: list[dict] = field(default_factory=list)  # bubbles.lines_from's
    recovered: bool = False

    def sentences(self) -> list[dict]:
        return [line for line in self.lines if line.get("kind") == "bubble"]

    def has_audio(self) -> bool:
        return any(line.get("audio_original") or line.get("audio_translation") for line in self.lines)

    def speaker(self, line: dict) -> str:
        return self.speakers.get(line.get("side", ""), "") or line.get("speaker", "")

    def text(self) -> str:
        """Speaker, original and translation, for reading anywhere."""
        out = [self.name, self.created, ""]
        for line in self.lines:
            if line.get("kind") != "bubble":
                continue
            out.append(f"{self.speaker(line)}  {line.get('when', '')}".rstrip())
            out.append(line.get("original", ""))
            out.append(line.get("translation", "") or line.get("problem", ""))
            out.append("")
        return "\n".join(out)

    def matches(self, query: str) -> bool:
        """Whether the words, in any case, are in its name or anything said."""
        query = query.strip().casefold()
        if not query:
            return True
        parts = [self.name, *self.speakers.values()]
        for line in self.sentences():
            parts += [line.get("original", ""), line.get("translation", "")]
        return any(query in part.casefold() for part in parts)

    def audio_path(self, line: dict, track: str) -> Path | None:
        """A line's audio file. Only ever a file directly in this conversation's
        audio folder, whatever a conversation.json may say."""
        name = line.get(f"audio_{track}", "")
        return self.folder / AUDIO_DIR / Path(name).name if name else None

    def clip(self, line: dict, track: str) -> Clip | None:
        path = self.audio_path(line, track)
        return read_wav(path) if path is not None and path.is_file() else None

    def write(self) -> None:
        """conversation.json and conversation.txt. Replaced in one step, so a
        crash leaves the old one or the new one, never half of one."""
        data = {"version": VERSION, "name": self.name, "created": self.created, "languages": list(self.languages),
                "way": self.way, "speakers": self.speakers, "recovered": self.recovered, "lines": self.lines}
        _replace(self.folder / JSON_NAME, json.dumps(data, ensure_ascii=False, indent=1))
        _replace(self.folder / TEXT_NAME, self.text())

    def save_names(self) -> None:
        """After renaming it or naming its speakers."""
        self.write()


def _replace(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except OSError as e:
        raise ConversationError(f"cannot write {path.absolute()}: {e}") from e


def write_wav(path: Path, clip: Clip) -> None:
    try:
        with wave.open(str(path), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(clip.rate)
            out.writeframes(clip.samples.astype("<i2").tobytes())
    except OSError as e:
        raise ConversationError(f"cannot write {path.absolute()}: {e}") from e


def read_wav(path: Path) -> Clip:
    try:
        with wave.open(str(path), "rb") as source:
            samples = np.frombuffer(source.readframes(source.getnframes()), "<i2")
            return Clip(samples, source.getframerate())
    except (OSError, EOFError, wave.Error) as e:
        raise ConversationError(f"cannot read {path.absolute()}: {e}") from e


def load(folder: Path) -> Conversation:
    path = folder / JSON_NAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["version"] > VERSION:
            raise ConversationError(f"{path.absolute()} was saved by a newer Volis")
        return Conversation(folder, data["name"], data["created"], tuple(data["languages"]), data.get("way", ""),
                            data.get("speakers", {}), data["lines"], data.get("recovered", False))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ConversationError(f"cannot read {path.absolute()}: {e}") from e


def load_all(root: Path) -> tuple[list[Conversation], list[str]]:
    """Every saved conversation, newest first, and what couldn't be read."""
    base = paths.conversations_dir(root)
    found, problems = [], []
    try:
        folders = [p for p in base.iterdir() if p.is_dir() and p != paths.in_progress_dir(root)]
    except FileNotFoundError:
        return [], []
    except OSError as e:
        return [], [f"cannot read {base.absolute()}: {e}"]
    for folder in folders:
        if not (folder / JSON_NAME).exists():
            continue
        try:
            found.append(load(folder))
        except ConversationError as e:
            log.warning("%s", e)
            problems.append(str(e))
    found.sort(key=lambda c: c.created, reverse=True)
    return found, problems


def default_name(languages: tuple[str, str], created: str, names=lambda tag: tag) -> str:
    return f"{names(languages[0])} and {names(languages[1])}, {created}"


def _folder_for(root: Path, name: str, stamp: str) -> Path:
    """A new folder's name: when it was, and what it is called, as far as
    Windows allows. Renaming later changes the name shown, not the folder."""
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")[:60].strip(" .")
    base = paths.conversations_dir(root)
    stem = f"{stamp} {clean}".strip()
    candidate, n = base / stem, 2
    while candidate.exists():
        candidate, n = base / f"{stem} ({n})", n + 1
    return candidate


def recover(root: Path, now: str | None = None) -> Conversation | None:
    """Volis closed without settling the last conversation: it becomes an
    ordinary saved one, so that it can't be lost or overwritten. None if there
    was nothing to recover."""
    progress = paths.in_progress_dir(root)
    if not (progress / JSON_NAME).exists():
        return None
    conversation = load(progress)
    if not conversation.sentences():
        discard(root)
        return None
    conversation.name, conversation.recovered = RECOVERED_NAME, True
    conversation.write()
    folder = _folder_for(root, RECOVERED_NAME, _stamp(conversation.created or now))
    _move(progress, folder)
    conversation.folder = folder
    log.info("recovered an unsaved conversation into %s", folder)
    return conversation


def _stamp(created: str | None) -> str:
    return (created or time.strftime("%Y-%m-%d %H:%M")).replace(":", "-")


def _move(source: Path, target: Path) -> None:
    try:
        os.replace(source, target)
    except OSError as e:
        raise ConversationError(f"cannot move {source.absolute()} to {target.absolute()}: {e}") from e


def discard(root: Path) -> None:
    """Delete the conversation in progress."""
    remove(paths.in_progress_dir(root))


def remove(folder: Path) -> None:
    """Delete one conversation's folder, and only one that is a conversation."""
    if not folder.exists():
        return
    if not (folder / JSON_NAME).exists():
        raise ConversationError(f"not deleting {folder.absolute()}: it isn't a saved conversation")
    try:
        shutil.rmtree(folder)
    except OSError as e:
        raise ConversationError(f"cannot delete {folder.absolute()}: {e}") from e


class Keeper:
    """The conversation in progress, kept up to date on disk as it goes."""

    def __init__(self, root: Path, languages: tuple[str, str], way: str, clips: Clips, created: str = "") -> None:
        self.root, self.clips = root, clips
        self.written: dict[tuple[str, str], str] = {}  # (line key, track) -> file name
        self.numbers: dict[str, int] = {}
        self.conversation = Conversation(paths.in_progress_dir(root), "", created or time.strftime("%Y-%m-%d %H:%M"),
                                         languages, way)
        try:
            (self.conversation.folder / AUDIO_DIR).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ConversationError(f"cannot create {self.conversation.folder.absolute()}: {e}") from e

    def _audio(self, line: dict, track: str, clip: Clip | None) -> str:
        """The line's file for this track, written the first time there is audio for it."""
        done = self.written.get((line["key"], track), "")
        if done or clip is None:
            return done
        number = self.numbers.setdefault(line["key"], len(self.numbers) + 1)
        name = f"{number:04d}-{track}.wav"
        write_wav(self.conversation.folder / AUDIO_DIR / name, clip)
        self.written[(line["key"], track)] = name
        return name

    def update(self, lines: list[dict]) -> None:
        for line in lines:
            if line.get("kind") != "bubble":
                continue
            heard = None
            if line.get("utterance", -1) >= 0:
                heard = self.clips.original(line["utterance"], line.get("start", 0.0), line.get("end", 0.0))
            line["audio_original"] = self._audio(line, ORIGINAL, heard)
            speech = self.clips.spoken(line["speech"]) if line.get("speech") else None
            line["audio_translation"] = self._audio(line, TRANSLATION, speech)
        self.conversation.lines = lines
        self.conversation.write()

    def save(self, name: str, keep_audio: bool = True, speakers: dict[str, str] | None = None) -> Conversation:
        """Settle it: a saved conversation, in a folder of its own."""
        c = self.conversation
        c.name = name.strip() or c.created
        c.speakers = {side: who.strip() for side, who in (speakers or {}).items() if who.strip()}
        if not keep_audio:
            for line in c.lines:
                line["audio_original"] = line["audio_translation"] = ""
            try:
                shutil.rmtree(c.folder / AUDIO_DIR, ignore_errors=False)
            except OSError as e:
                raise ConversationError(f"cannot delete {(c.folder / AUDIO_DIR).absolute()}: {e}") from e
        c.write()
        folder = _folder_for(self.root, c.name, _stamp(c.created))
        _move(c.folder, folder)
        c.folder = folder
        return c
