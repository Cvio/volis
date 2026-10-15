"""The export folder of a file run or a live conversation: what a person reads
later, and what model-bench and a colleague read to reproduce and check it.

  conversation.txt  the conversation to read: each sentence with its time, its
                    language and its translation
  transcript.txt    one sentence per line, as recognized
  translation.txt   the same lines, translated (empty where not translated)
  source.srt        subtitles of the transcript, with timings
  translation.srt   subtitles of the translation
  events.jsonl      every event in order; the first line is the full
                    configuration (models with folder names and file hashes,
                    prompt file, every setting), the last the summary.

Default folder: exports\\<file>-<date>\\ inside the app, or
exports\\conversation-<date>\\ for a live conversation.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__, paths, varieties
from .events import Configuration, Event, NotTranslated, SentenceMsg, Translated


def default_folder(root: Path, audio: Path | None) -> Path:
    """`audio` is the recording a file run translated; None for a live conversation."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return root / "exports" / f"{audio.stem if audio is not None else 'conversation'}-{stamp}"


# ---------------------------------------------------------------- hashes


def sha256(path: Path, root: Path) -> str:
    """A file's SHA-256, cached by path, size and modification time in
    cache\\hashes.json inside the app: model files are gigabytes."""
    cache_file = paths.cache_dir(root) / "hashes.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    stat = path.stat()
    key = f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    if key in cache:
        return cache[key]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            digest.update(block)
    cache[key] = digest.hexdigest()
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=0), encoding="utf-8")
    except OSError:
        pass  # a cache that can't be written costs time, not correctness
    return cache[key]


def folder_files(folder: Path, root: Path) -> dict[str, str]:
    """Every file of a model folder (or a single model file), hashed. The
    download bookkeeping in .cache\\ isn't the model and is left out."""
    if folder.is_file():
        return {folder.name: sha256(folder, root)}
    return {
        p.relative_to(folder).as_posix(): sha256(p, root)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and ".cache" not in p.relative_to(folder).parts
    }


def configuration(root: Path, *, audio: Path | None, config, pyconfig, options, recognizer: str, translator: str,
                  prompt_file: Path | None, cli: dict) -> Configuration:
    """The first line of events.jsonl."""
    import importlib.metadata as md

    def version(name):
        try:
            return md.version(name)
        except md.PackageNotFoundError:
            return None

    asr_dir = paths.asr_dir(root) / recognizer
    mt_path = paths.mt_dir(root) / translator if translator else None
    vad = paths.vad_model_file(root)
    settings = {
        "volis": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "libraries": {n: version(n) for n in ("torch", "transformers", "sherpa-onnx", "llama-cpp-python", "av")},
        "audio": ({"path": str(audio.absolute()), "sha256": sha256(audio, root)} if audio is not None
                  else {"source": "microphone", "device": config.audio.input_device}),
        "recognizer": {"folder": recognizer, "files": folder_files(asr_dir, root)} if recognizer else None,
        "translator": {"id": translator, "files": folder_files(mt_path, root)} if mt_path else None,
        "vad": {"file": vad.name, "sha256": sha256(vad, root)},
        "prompt": {"file": prompt_file.name, "text": prompt_file.read_text(encoding="utf-8"),
                   "sha256": sha256(prompt_file, root)} if prompt_file else None,
        "volis.toml": asdict(config),
        "volis-python.toml": asdict(pyconfig),
        "options": asdict(options),
        "command_line": cli,
    }
    return Configuration(settings)


# ---------------------------------------------------------------- files


def srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(cues: list[tuple[float, float, str]]) -> str:
    blocks = []
    for n, (start, end, text) in enumerate(cues, 1):
        end = max(end, start + 0.5)  # a cue too short to read is lengthened
        blocks.append(f"{n}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def conversation_text(sentences: list[SentenceMsg], events: list[Event], translated: dict[str, str]) -> str:
    """The conversation as a person reads it later: each sentence, when it was
    said (or that it was typed), in which language, and its translation."""
    into = {e.id: e.lang for e in events if isinstance(e, Translated)}
    lines = [f"Volis conversation, saved {time.strftime('%Y-%m-%d %H:%M')}", ""]
    for s in sentences:
        when = "typed" if getattr(s, "typed", False) else srt_time(s.start)[:8]
        lines.append(f"[{when}] {varieties.display_name(s.lang)}: {s.text}")
        if translated.get(s.id):
            lines.append(f"{' ' * (len(when) + 3)}{varieties.display_name(into.get(s.id, ''))}: {translated[s.id]}")
        else:
            lines.append(f"{' ' * (len(when) + 3)}(not translated)")
        lines.append("")
    return "\n".join(lines)


def write(folder: Path, events: list[Event], configuration_event: Configuration) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    sentences = [e for e in events if isinstance(e, SentenceMsg)]
    translated = {e.id: e.text for e in events if isinstance(e, Translated)}
    # A later translation of the same sentence (a revision, P8) replaces the earlier.
    for e in events:
        if type(e).__name__ == "Revised":
            translated[e.id] = e.new
    for e in events:
        if isinstance(e, NotTranslated):
            translated.setdefault(e.id, "")
    files = {
        "conversation.txt": conversation_text(sentences, events, translated),
        "transcript.txt": "\n".join(s.text for s in sentences) + "\n",
        "translation.txt": "\n".join(translated.get(s.id, "") for s in sentences) + "\n",
        "source.srt": srt([(s.start, s.end, s.text) for s in sentences]),
        "translation.srt": srt([(s.start, s.end, translated[s.id]) for s in sentences if translated.get(s.id)]),
    }
    written = {}
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8", newline="\n")
        written[name] = folder / name
    # The summary is written last, after the pipeline's Stopped.
    ordered = [e for e in events if type(e).__name__ != "Summary"] + [e for e in events if type(e).__name__ == "Summary"]
    with (folder / "events.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        f.write(configuration_event.to_json() + "\n")
        for event in ordered:
            f.write(event.to_json() + "\n")
    written["events.jsonl"] = folder / "events.jsonl"
    return written
