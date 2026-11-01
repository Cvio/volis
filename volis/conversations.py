"""Saved conversations. No Qt in this file.

An ordinary folder inside Volis, one folder per conversation:

    conversations\\2026-10-31 14-05 Menu\\
        conversation.json   everything needed to show it again
        conversation.txt    the same words, for reading anywhere
        audio\\0001-original.wav, 0001-translation.wav, ...

Sharing makes one file of a conversation (a zip, named .volis) that another
Volis opens, or its text, or all its audio in the order it was heard.

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
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import audio, paths
from .clips import ORIGINAL, TRANSLATION, Clip, Clips

log = logging.getLogger(__name__)

VERSION = 1
JSON_NAME, TEXT_NAME, AUDIO_DIR = "conversation.json", "conversation.txt", "audio"
RECOVERED_NAME = "Recovered conversation"
LEFT, RIGHT = "left", "right"
TWO_COMPUTERS = "two-computers"  # talk.TWO_COMPUTERS, as a conversation.json says it
FILE_SUFFIX = ".volis"
_AUDIO_NAME = re.compile(r"audio/\d+-(original|translation)\.wav")  # the only names a Keeper gives
BETWEEN_PARTS, BETWEEN_SENTENCES = 0.4, 0.8  # seconds of silence in a conversation's whole audio
_TEXT_FIELDS = ("key", "side", "speaker", "when", "original", "translation", "problem", "note", "text", "speech",
                "audio_original", "audio_translation", "heard", "earlier")


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
            if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() <= 0:
                raise wave.Error("not 16-bit mono")
            samples = np.frombuffer(source.readframes(source.getnframes()), "<i2")
            return Clip(samples, source.getframerate())
    except (OSError, EOFError, ValueError, wave.Error) as e:
        raise ConversationError(f"cannot read {path.absolute()}: {e}") from e


def _is_text(value) -> bool:
    return isinstance(value, str)


def _parse(text: str, folder: Path) -> Conversation:
    """A conversation.json's words. One from another computer can say anything,
    so everything is checked here rather than where it would later go wrong.
    Raises ValueError, KeyError or TypeError."""
    data = json.loads(text)
    if not isinstance(data["version"], int):
        raise ValueError("its version is not a number")
    if data["version"] > VERSION:
        raise ValueError("it was saved by a newer Volis")
    languages, speakers, lines = data["languages"], data.get("speakers", {}), data["lines"]
    if not (isinstance(languages, list) and len(languages) == 2 and all(map(_is_text, languages))):
        raise ValueError("its languages are not two names")
    if not (isinstance(speakers, dict) and all(map(_is_text, speakers.values()))):
        raise ValueError("its speakers are not names")
    if not isinstance(lines, list):
        raise ValueError("its lines are not a list")
    for line in lines:
        if not (isinstance(line, dict) and _is_text(line["key"]) and all(_is_text(line.get(f, "")) for f in _TEXT_FIELDS)):
            raise ValueError("one of its lines is not readable")
        if line.get("kind") == "note" and "text" not in line:
            raise ValueError("one of its notes has no words")
    name, created, way = data["name"], data["created"], data.get("way", "")
    if not all(map(_is_text, (name, created, way))):
        raise ValueError("its name or date is not text")
    return Conversation(folder, name, created, tuple(languages), way, speakers, lines, bool(data.get("recovered", False)))


def load(folder: Path) -> Conversation:
    path = folder / JSON_NAME
    try:
        return _parse(path.read_text(encoding="utf-8"), folder)
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


def safe_name(name: str) -> str:
    """A name, as far as Windows allows it in a file or folder's name."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")[:60].strip(" .")


def _folder_for(root: Path, name: str, stamp: str) -> Path:
    """A new folder's name: when it was, and what it is called. Renaming later
    changes the name shown, not the folder."""
    base = paths.conversations_dir(root)
    stem = f"{safe_name(stamp)} {safe_name(name)}".strip() or "conversation"
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


# ---------------------------------------------------------------- sharing


def _with_suffix(path: Path, suffix: str) -> Path:
    return path if path.suffix.lower() == suffix else path.with_name(path.name + suffix)


def _audio_files(c: Conversation) -> list[Path]:
    found = {}
    for line in c.sentences():
        for track in (ORIGINAL, TRANSLATION):
            path = c.audio_path(line, track)
            if path is not None and path.is_file():
                found[path.name] = path
    return list(found.values())


def share_file(c: Conversation, target: Path) -> Path:
    """One file with everything, which another Volis can open. The audio is
    stored as it is: squeezing speech takes long and saves little. A failure
    leaves no half-written file under the name asked for."""
    target = _with_suffix(target, FILE_SUFFIX)
    temporary = target.with_name(target.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as out:
            out.write(c.folder / JSON_NAME, JSON_NAME)
            for path in _audio_files(c):
                out.write(path, f"{AUDIO_DIR}/{path.name}", zipfile.ZIP_STORED)
        os.replace(temporary, target)
    except OSError as e:
        temporary.unlink(missing_ok=True)
        raise ConversationError(f"cannot write {target.absolute()}: {e}") from e
    return target


def share_text(c: Conversation, target: Path) -> Path:
    """The words: speaker, original, translation. With the mark and line ends
    that Word and Notepad recognise, so Farsi and Arabic arrive intact."""
    target = _with_suffix(target, ".txt")
    try:
        target.write_text(c.text(), encoding="utf-8-sig", newline="\r\n")
    except OSError as e:
        raise ConversationError(f"cannot write {target.absolute()}: {e}") from e
    return target


def whole_audio(c: Conversation) -> Clip | None:
    """Everything in the order it was heard, each original followed by its
    translation, at the rate the originals have. None if no audio was kept."""
    pieces: list[np.ndarray] = []

    def silence(seconds: float) -> None:
        pieces.append(np.zeros(int(seconds * audio.SAMPLE_RATE), np.int16))

    for line in c.sentences():
        said = False
        for track in (ORIGINAL, TRANSLATION):
            clip = c.clip(line, track)
            if clip is None or not len(clip.samples):
                continue
            if said:
                silence(BETWEEN_PARTS)
            samples = clip.samples
            if clip.rate != audio.SAMPLE_RATE:
                samples = np.clip(audio.resample(clip.floats(), clip.rate) * 32767.0, -32768, 32767).astype(np.int16)
            pieces.append(samples)
            said = True
        if said:
            silence(BETWEEN_SENTENCES)
    return Clip(np.concatenate(pieces), audio.SAMPLE_RATE) if pieces else None


def share_audio(c: Conversation, target: Path) -> Path:
    target = _with_suffix(target, ".wav")
    whole = whole_audio(c)
    if whole is None:
        raise ConversationError(f"{c.name} has no audio to share")
    temporary = target.with_name(target.name + ".tmp")
    try:
        write_wav(temporary, whole)
        os.replace(temporary, target)
    except OSError as e:
        temporary.unlink(missing_ok=True)
        raise ConversationError(f"cannot write {target.absolute()}: {e}") from e
    return target


def _other_half(known: list[Conversation], incoming: Conversation) -> Conversation | None:
    """The saved conversation that a file is the other computer's copy of: both
    were on two computers on the same day, and at least half of the sentences of
    the shorter one are the same words seen from the other side."""
    if incoming.way != TWO_COMPUTERS:
        return None
    theirs = {(line.get("side"), line.get("translation")) for line in incoming.sentences() if line.get("translation")}
    for c in known:
        if c.way != TWO_COMPUTERS or c.created[:10] != incoming.created[:10]:
            continue
        ours = [line for line in c.sentences() if line.get("translation")]
        flipped = sum((RIGHT if line.get("side") == LEFT else LEFT, line["translation"]) in theirs for line in ours)
        if flipped and flipped * 2 >= min(len(ours), len(theirs)):
            return c
    return None


def _combine(c: Conversation, incoming: Conversation, zipped: zipfile.ZipFile) -> None:
    """The audio this copy lacks, from the other computer's copy of it."""
    by_words = {}
    for line in incoming.sentences():
        by_words[(line.get("side"), line.get("translation"))] = line
    names = set(zipped.namelist())
    (c.folder / AUDIO_DIR).mkdir(exist_ok=True)
    for number, line in enumerate(c.sentences(), 1):
        other = by_words.get((RIGHT if line.get("side") == LEFT else LEFT, line.get("translation")))
        if other is None:
            continue
        for track in (ORIGINAL, TRANSLATION):
            source = incoming.audio_path(other, track)
            member = f"{AUDIO_DIR}/{source.name}" if source is not None else ""
            if line.get(f"audio_{track}") or member not in names or not _AUDIO_NAME.fullmatch(member):
                continue
            name = f"{number:04d}-{track}.wav"
            (c.folder / AUDIO_DIR / name).write_bytes(zipped.read(member))
            line[f"audio_{track}"] = name
    c.write()


NEW, ALREADY, COMBINED = "new", "already", "combined"


def open_file(root: Path, path: Path) -> tuple[Conversation, str]:
    """A shared conversation, into this Volis's Saved: the conversation, and
    what became of it: NEW, ALREADY there, or COMBINED with this computer's own
    copy, the other computer's audio joining it. Only the two kinds of file a
    conversation has are read out of the zip, each under a name decided here, so
    a file from elsewhere can't write anywhere else."""
    source = path.absolute()
    try:
        with zipfile.ZipFile(path) as zipped:
            try:
                info = zipped.getinfo(JSON_NAME)
            except KeyError:
                raise ConversationError(f"{source} isn't a Volis conversation file") from None
            incoming = _parse(zipped.read(info).decode("utf-8"), Path())
            known, _ = load_all(root)
            same = next((c for c in known if (c.created, c.lines) == (incoming.created, incoming.lines)), None)
            if same is not None:
                return same, ALREADY
            half = _other_half(known, incoming)
            if half is not None:
                _combine(half, incoming, zipped)
                return half, COMBINED
            members = {f"{AUDIO_DIR}/{p.name}" for line in incoming.sentences() for p in
                       (incoming.audio_path(line, ORIGINAL), incoming.audio_path(line, TRANSLATION)) if p is not None}
            wanted = [i for i in zipped.infolist() if i.filename in members and _AUDIO_NAME.fullmatch(i.filename)]
            folder = _folder_for(root, incoming.name, _stamp(incoming.created))
            folder.parent.mkdir(parents=True, exist_ok=True)
            needed = info.file_size + sum(i.file_size for i in wanted)
            if needed > shutil.disk_usage(folder.parent).free:
                raise ConversationError(f"not enough room on the disk for {source} in {folder.parent.absolute()}")
            try:
                (folder / AUDIO_DIR).mkdir(parents=True)
                for member in wanted:
                    (folder / AUDIO_DIR / Path(member.filename).name).write_bytes(zipped.read(member))
                incoming.folder = folder
                incoming.write()  # last: without it, what is there isn't a conversation yet
            except (OSError, zipfile.BadZipFile, ConversationError):
                shutil.rmtree(folder, ignore_errors=True)
                raise
    except ConversationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as e:
        raise ConversationError(f"cannot open {source}: {e}") from e
    return incoming, NEW


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
            words = line.get("translation", "")
            if line.get("utterance", -1) >= 0:
                heard = self.clips.original(line["utterance"], line.get("start", 0.0), line.get("end", 0.0))
            else:
                heard = self.clips.received(ORIGINAL, words) if words else None
            line["audio_original"] = self._audio(line, ORIGINAL, heard)
            speech = self.clips.spoken(line["speech"]) if line.get("speech") else None
            if speech is None and words:
                speech = self.clips.received(TRANSLATION, words)
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
