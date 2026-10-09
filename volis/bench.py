"""The test bench's work: try recognizers and translators against each other
and keep what was measured. No Qt here; the window is `gui/testbench.py`.

It is for whoever is deciding which model to use, or checking a change:

- `hear`: one clip through each chosen recognizer. The clip is cut into
  utterances once, by the same detector a conversation uses, so every
  recognizer hears exactly the same pieces. With the text that was really
  said, each is scored against it.
- translators are compared by `typed.compare`, on typed text or on what one
  recognizer heard in a clip (`lines_heard`).
- `Recorder`: a clip from the microphone.
- `History`: every comparison, kept in `logs\\test-bench.json`.
- `Worker`: the one thread that does it all, one job at a time.
- `ready`: whether a comparison can start, and the one line that says why not.

Models are loaded one at a time and released before the next: on a small
graphics card they don't fit together, and a time measured with another model
running beside it measures the crowding, not the model.
"""

from __future__ import annotations

import json
import logging
import math
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from . import paths, scoring, sentences, typed
from .audio import SAMPLE_RATE

log = logging.getLogger(__name__)

KEPT = 200  # comparisons kept in the history file
MAX_RECORD_S = 300  # a recording stops itself here
RECOGNIZERS, TRANSLATORS = "recognizers", "translators"
RECOGNIZER_COLUMNS = ["Recognizer", "What it heard", "Time", "Speed", "Runs on", "Memory", "Letters wrong",
                      "Words wrong", "Notes"]
TRANSLATOR_COLUMNS = ["Text", "Translator", "Translation", "Time", "Runs on", "Score", "Notes"]
ERROR_NOTE = ("Letters wrong and Words wrong compare what each recognizer heard with the correct text you gave "
              "(punctuation and capitals ignored). Lower is better. For Arabic and Persian read Letters wrong: "
              "one wrong letter there makes a whole word count as wrong.")
RUNS_ON = {"cuda": "graphics card", "cpu": "processor"}


# ---------------------------------------------------------------- sound


def level_db(samples: np.ndarray) -> float:
    if len(samples) == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    return 20 * math.log10(max(rms, 1e-6))


def cut(audio: np.ndarray, root: Path, config, pyconfig) -> list[np.ndarray]:
    """The utterances in a clip, cut as a conversation would cut them."""
    from .filesource import chunks
    from .vad import Segmenter, VadSettings

    segmenter = Segmenter(VadSettings(
        model=paths.vad_model_file(root), threshold=config.vad.threshold, min_silence_ms=config.vad.min_silence_ms,
        min_speech_ms=config.vad.min_speech_ms, pre_roll_ms=pyconfig.vad.pre_roll_ms))
    segments = []
    for chunk in chunks(audio):
        segments += segmenter.push(chunk)
    return [s.samples for s in segments + segmenter.flush() if len(s.samples)]


class Recorder:
    """A clip from the microphone: `start`, `poll` now and then for the
    level, `stop` for the audio (16 kHz mono)."""

    def __init__(self, spawn=None) -> None:
        self._spawn = spawn
        self._chunks: queue.Queue = queue.Queue()
        self._parts: list[np.ndarray] = []
        self._handle = None
        self.samples = 0

    def start(self, device: str) -> None:
        from . import audio

        self._handle = (self._spawn or audio.spawn_capture)(device, self._chunks)

    def recording(self) -> bool:
        return self._handle is not None

    def seconds(self) -> float:
        return self.samples / SAMPLE_RATE

    def poll(self) -> float:
        """Take in what has arrived; the level of the newest audio, in dB."""
        level = -120.0
        while True:
            try:
                chunk = self._chunks.get_nowait()
            except queue.Empty:
                return level
            self._parts.append(chunk)
            self.samples += len(chunk)
            level = level_db(chunk)

    def stop(self) -> np.ndarray:
        if self._handle is not None:
            self._handle.stop()
            self._handle = None
        self.poll()
        return np.concatenate(self._parts).astype(np.float32) if self._parts else np.zeros(0, np.float32)


# ---------------------------------------------------------------- recognizers


@dataclass
class Heard:
    """One recognizer's account of a clip."""

    engine: str  # its folder
    name: str  # as the window shows it
    text: str = ""
    parts: list[str] = field(default_factory=list)  # the text of each utterance
    ms: int = 0  # recognition only, not loading
    rtf: float | None = None  # time taken / length of the speech
    device: str = ""
    gpu_bytes: int = 0
    cpu_bytes: int = 0
    cer: float | None = None  # against the correct text, when given
    wer: float | None = None
    note: str = ""
    problem: str = ""  # why there is no text


def hear(pieces: list[np.ndarray], language: str, engines: list, load, reference: str = "",
         on_status=lambda text: None, cancelled=lambda: False, name=lambda engine: engine.name) -> list[Heard]:
    """Each utterance in `pieces` through each recognizer in `engines`, one
    recognizer loaded at a time. One that can't be loaded or fails is reported
    in its place and the rest go on."""
    out: list[Heard] = []
    speech = sum(len(p) for p in pieces) / SAMPLE_RATE
    for engine in engines:
        if cancelled():
            break
        label = name(engine)
        on_status(f"Loading {label}...")
        try:
            recognizer = load(engine)
        except Exception as e:  # the reason is this recognizer's result
            log.warning("test bench: %s could not be loaded: %s", engine.dir_name, e)
            out.append(Heard(engine.dir_name, label, problem=f"could not be loaded: {e}"))
            continue
        heard = Heard(engine.dir_name, label)
        try:
            memory = recognizer.memory()
            heard.device, heard.gpu_bytes, heard.cpu_bytes = memory.device, memory.gpu_bytes, memory.cpu_bytes
            seconds = 0.0
            for n, piece in enumerate(pieces, 1):
                if cancelled():
                    heard.note = "stopped early"
                    break
                on_status(f"{label}: listening to part {n} of {len(pieces)}...")
                began = time.perf_counter()
                text = recognizer.transcribe(piece, language, False).text.strip()
                seconds += time.perf_counter() - began
                heard.parts.append(text)
            heard.text = " ".join(p for p in heard.parts if p)
            heard.ms = int(seconds * 1000)
            heard.rtf = round(seconds / speech, 3) if speech else None
            if not heard.text and not heard.note:
                heard.problem = "it heard no words"
            elif reference.strip() and not heard.note:
                heard.cer = round(scoring.cer(reference, heard.text, language), 1)
                heard.wer = round(scoring.wer(reference, heard.text, language), 1)
        except Exception as e:
            log.warning("test bench: %s failed: %s", engine.dir_name, e)
            heard.problem = f"failed: {e}"
        finally:
            recognizer.close()
        out.append(heard)
    return out


def lines_heard(heard: Heard) -> list[str]:
    """What a recognizer heard, as the sentences a translator would be given."""
    return [s for part in heard.parts for s in sentences.split_text(part)]


def heard_rows(results: list[Heard]) -> list[list[str]]:
    rows = []
    for h in results:
        memory = h.gpu_bytes or h.cpu_bytes
        rows.append([
            h.name, h.problem or h.text, f"{h.ms} ms" if not h.problem else "",
            f"{1 / h.rtf:.1f}x faster than speech" if h.rtf and h.rtf < 1 else
            f"{h.rtf:.1f}x slower than speech" if h.rtf else "",
            RUNS_ON.get(h.device, ""), f"{memory / 1e9:.1f} GB" if memory else "",
            "" if h.cer is None else f"{h.cer:.1f}%", "" if h.wer is None else f"{h.wer:.1f}%", h.note])
    return rows


def translated_rows(compared: list) -> tuple[list[list[str]], list[str]]:
    """`typed.compare`'s result as table rows, and the translator of each row."""
    rows, ids = [], []
    for line in compared:
        for r in line.results:
            rows.append([line.text, r.name, r.problem or r.text, "" if r.problem else f"{r.ms} ms",
                         RUNS_ON.get(r.device, ""), "" if r.chrf is None else f"{r.chrf:.1f}", r.note])
            ids.append(r.model)
    return rows, ids


# ---------------------------------------------------------------- what was measured, kept


@dataclass
class Record:
    """One comparison, as it is shown and kept."""

    when: str
    kind: str  # RECOGNIZERS | TRANSLATORS
    title: str  # what was compared on: "Persian, talk.wav (42 s)"
    columns: list[str]
    rows: list[list[str]]
    ids: list[str] = field(default_factory=list)  # the model of each row, for "Use in conversation"
    note: str = ""
    reference: str = ""

    def label(self) -> str:
        models = len(dict.fromkeys(self.ids))
        return f"{self.when}  {self.title}  ({models} {'model' if models == 1 else 'models'})"


def markdown(record: Record) -> str:
    """A comparison as a Markdown table, to paste into notes or MODELS.md."""
    def cell(text: str) -> str:
        return " ".join(str(text).split()).replace("|", "\\|")

    lines = [f"{record.title} ({record.when})", "",
             "| " + " | ".join(record.columns) + " |", "|" + "---|" * len(record.columns)]
    lines += ["| " + " | ".join(cell(c) for c in row) + " |" for row in record.rows]
    if record.reference:
        lines += ["", f"Reference: {cell(record.reference)}"]
    return "\n".join(lines) + "\n"


class History:
    """`logs\\test-bench.json`: the comparisons made on this machine, newest last."""

    def __init__(self, path: Path, records: list[Record] | None = None) -> None:
        self.path = path
        self.records = records or []

    @classmethod
    def load(cls, root: Path) -> History:
        path = paths.test_bench_file(root)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(path, [Record(**r) for r in data.get("comparisons", [])])
        except FileNotFoundError:
            return cls(path)
        except (OSError, ValueError, TypeError) as e:
            log.warning("cannot read %s: %s; starting an empty history", path.absolute(), e)
            return cls(path)

    def add(self, record: Record) -> None:
        self.records = (self.records + [record])[-KEPT:]
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"comparisons": [asdict(r) for r in self.records]}, ensure_ascii=False,
                                            indent=1), encoding="utf-8")
        except OSError as e:
            log.warning("cannot write %s: %s", self.path.absolute(), e)

    def of(self, kind: str) -> list[Record]:
        """This kind's comparisons, newest first."""
        return [r for r in reversed(self.records) if r.kind == kind]


# ---------------------------------------------------------------- can it start?


@dataclass(frozen=True)
class Ready:
    enabled: bool
    message: str  # why not, in one line; "" when it can start


STOP_FIRST = "Stop the conversation first: the test bench needs the memory it is using."


def ready(kind: str, running: bool = False, busy: bool = False, recording: bool = False, ticked: int = 0,
          has_sound: bool = False, has_text: bool = False, from_sound: bool = True,
          has_recognizer: bool = True) -> Ready:
    """Whether a comparison can start. The reason is shown beside the button
    before it is pressed, never after a press that did nothing."""
    if busy:
        return Ready(False, "")  # the line at the top of the bench says what is happening
    if recording:
        return Ready(False, "Recording: press Stop recording when you have finished speaking.")
    if running:
        return Ready(False, STOP_FIRST)
    if kind == "whole":
        return Ready(True, "")
    if kind == RECOGNIZERS or from_sound:
        if not has_sound:
            return Ready(False, "Record something, or choose an audio file, first.")
        if kind == TRANSLATORS and not has_recognizer:
            return Ready(False, "Choose the recognizer that will turn the sound into text.")
    elif not has_text:
        return Ready(False, "Type or paste the text to translate first.")
    if ticked < 1:
        return Ready(False, f"Tick at least one {'recognizer' if kind == RECOGNIZERS else 'translator'} in the list.")
    return Ready(True, "")


# ---------------------------------------------------------------- the thread


@dataclass
class Outcome:
    """What a job ended with: a record to show and keep, or why there is none."""

    kind: str
    record: Record | None = None
    problem: str = ""
    heard: list[Heard] = field(default_factory=list)  # a recognizer comparison's results, with their memory


def seconds_text(seconds: float) -> str:
    return f"{seconds:.1f} s" if seconds < 60 else f"{int(seconds // 60)} min {int(seconds % 60)} s"


class Worker:
    """The test bench's one thread. Jobs are queued and run one at a time;
    each ends with an `Outcome` on `outcomes`. `status` is what it is doing
    now, in plain words."""

    def __init__(self, root: Path, config, pyconfig, load_recognizer=None, load_translator=None, cut_fn=None,
                 clean=None) -> None:
        self.root, self.config, self.pyconfig = root, config, pyconfig
        self._load_recognizer = load_recognizer or self._recognizer
        self._load_translator = load_translator or self._translator
        self._cut = cut_fn or (lambda audio: cut(audio, self.root, self.config, self.pyconfig))
        self._clean = clean or self._cleaner()
        self.outcomes: queue.Queue = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()
        self._cancel = threading.Event()
        self.busy = False
        self._working = False  # the thread is inside a job
        self.status = ""
        self._thread = threading.Thread(target=self._run, name="volis-test-bench", daemon=True)
        self._thread.start()

    # ---- the real loaders

    def _recognizer(self, engine):
        from . import asr

        return asr.load(engine)

    def _translator(self, entry):
        from . import translate as tr
        from .translate import prompts

        prompt = prompts.load(paths.prompts_dir(self.root), self.pyconfig.translate.prompt)
        return tr.load(entry, prompt, self.pyconfig.translate.device)

    def _cleaner(self):
        from . import persian

        if self.root is None or self.pyconfig is None:
            return lambda text, language: text
        cleaner = persian.cleaner(self.root, self.pyconfig.text.persian_cleanup)
        return lambda text, language: cleaner(text, language).text

    # ---- what the window asks for

    def recognizers(self, audio: np.ndarray, described: str, language: str, engines: list, reference: str = "",
                    names: dict[str, str] | None = None) -> None:
        self._put((RECOGNIZERS, audio, described, language, list(engines), reference, names or {}))

    def translators(self, lines: list[str], described: str, source: str, target: str, entries: list,
                    reference: str = "", glossary: list[str] | None = None, names: dict[str, str] | None = None,
                    audio: np.ndarray | None = None, recognizer=None) -> None:
        """Typed `lines`, or `audio` through `recognizer` first."""
        self._put((TRANSLATORS, lines, described, source, target, list(entries), reference, list(glossary or []),
                   names or {}, audio, recognizer))

    def _put(self, job) -> None:
        self._cancel.clear()
        self.busy = True  # from the press, not from when the thread gets to it
        self._jobs.put(job)

    def cancel(self) -> None:
        """Stop after the model that is running now; nothing more is loaded."""
        self._cancel.set()
        while True:
            try:
                self._jobs.get_nowait()
            except queue.Empty:
                break
        if not self._working:
            self.busy = False  # nothing had started

    def idle(self) -> bool:
        return not self.busy and self._jobs.empty()

    def close(self) -> None:
        self.cancel()
        self._jobs.put(None)
        self._thread.join(10)

    # ---- the thread

    def _say(self, text: str) -> None:
        self.status = text

    def _run(self) -> None:
        while (job := self._jobs.get()) is not None:
            self.busy = self._working = True
            try:
                outcome = self._hear(*job[1:]) if job[0] == RECOGNIZERS else self._translate(*job[1:])
            except Exception as e:  # shown in the bench, never raised into the window
                log.warning("test bench: %s", e)
                outcome = Outcome(job[0], problem=str(e))
            if self._cancel.is_set() and outcome.record is None and not outcome.problem:
                outcome.problem = "Stopped."
            self.outcomes.put(outcome)
            self.status = ""
            self._working = False
            self.busy = not self._jobs.empty()

    def _pieces(self, audio: np.ndarray) -> list[np.ndarray]:
        self._say("Finding the speech in the sound...")
        return self._cut(audio)

    def _hear(self, audio, described, language, engines, reference, names) -> Outcome:
        pieces = self._pieces(audio)
        if not pieces:
            return Outcome(RECOGNIZERS, problem="No speech was found in the sound. Was the microphone on?")
        results = hear(pieces, language, engines, self._load_recognizer, reference, self._say, self._cancel.is_set,
                       name=lambda engine: names.get(engine.dir_name, engine.name))
        if not results:
            return Outcome(RECOGNIZERS, problem="Stopped.")
        speech = sum(len(p) for p in pieces) / SAMPLE_RATE
        record = Record(time.strftime("%Y-%m-%d %H:%M"), RECOGNIZERS,
                        f"{described}, {seconds_text(speech)} of speech in {len(pieces)} "
                        f"{'part' if len(pieces) == 1 else 'parts'}",
                        RECOGNIZER_COLUMNS, heard_rows(results), [h.engine for h in results],
                        ERROR_NOTE if reference.strip() else "", " ".join(reference.split()))
        log.info("test bench: compared %d recognizer(s):\n%s", len(results), markdown(record))
        return Outcome(RECOGNIZERS, record, heard=results)

    def _translate(self, lines, described, source, target, entries, reference, glossary, names, audio,
                   recognizer) -> Outcome:
        if audio is not None:
            pieces = self._pieces(audio)
            if not pieces:
                return Outcome(TRANSLATORS, problem="No speech was found in the sound. Was the microphone on?")
            heard = hear(pieces, source, [recognizer], self._load_recognizer, "", self._say, self._cancel.is_set,
                         name=lambda engine: names.get(engine.dir_name, engine.name))
            if not heard or heard[0].problem:
                why = heard[0].problem if heard else "stopped"
                return Outcome(TRANSLATORS, problem=f"The sound could not be turned into text: {why}.")
            lines = lines_heard(heard[0])
            described = f"{described}, as heard by {heard[0].name}"
        lines = [self._clean(line, source) for line in lines]
        if self._cancel.is_set():
            return Outcome(TRANSLATORS, problem="Stopped.")
        compared = typed.compare(lines, source, target, entries, self._load_translator, reference, glossary, self._say,
                                 name=lambda entry: names.get(entry.id, entry.name), most=None,
                                 cancelled=self._cancel.is_set)
        rows, ids = translated_rows(compared)
        if not rows:
            return Outcome(TRANSLATORS, problem="Stopped.")
        scored = any(r.chrf is not None for line in compared for r in line.results)
        record = Record(time.strftime("%Y-%m-%d %H:%M"), TRANSLATORS,
                        f"{described}, {len(lines)} {'line' if len(lines) == 1 else 'lines'}",
                        TRANSLATOR_COLUMNS, rows, ids, typed.SCORE_NOTE if scored else "",
                        " / ".join(typed.lines_of(reference)))
        log.info("test bench: compared %d translator(s):\n%s", len(entries), markdown(record))
        return Outcome(TRANSLATORS, record)
