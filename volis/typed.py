"""Text typed or pasted in, translated without speaking (P15).

For a noisy room, a name, an address or a number; and for trying a translator
directly, against another translator or against a reference such as Google's.

Two things live here, with no Qt:

* `compare`: the same text through two or three translators, one after the
  other, each timed, each scored against a reference when there is one.
  A translator is loaded when its turn comes and released after it, so two
  that would not fit in memory together can still be compared (as `--compare`
  does for recognizers).
* `Worker`: a thread that translates typed lines with one translator while no
  conversation is running (during one, the running pipeline does it, so the
  translator isn't loaded twice), and runs comparisons.

The score against a reference is chrF, the same as file mode (`scoring.py`).
It says how close a translation is to that reference. It does not say the
translation is right: a good translation worded differently scores low, and
the reference itself may be wrong.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import events as ev
from . import scoring
from . import translate as tr

log = logging.getLogger(__name__)

MAX_COMPARED = 3
SCORE_NOTE = ("The score (chrF, 0 to 100) shows how close each translation is to the reference you typed. "
              "It does not show that a translation is correct: a good one worded differently scores lower.")


def lines_of(text: str) -> list[str]:
    """The lines to translate: each non-empty line is its own sentence."""
    return [line.strip() for line in text.replace("\r\n", "\n").split("\n") if line.strip()]


def reference_for(reference: str, index: int, count: int) -> str:
    """The part of a reference that belongs to line `index` of `count`: the
    same line of the reference when it has as many lines, else all of it for a
    single line, else nothing (there is no telling which part belongs where)."""
    lines = lines_of(reference)
    if len(lines) == count:
        return lines[index]
    return " ".join(lines) if count == 1 else ""


@dataclass
class Result:
    """One translator's translation of one line."""

    model: str  # the translator's id
    name: str  # as the window shows it
    text: str = ""
    ms: int = 0
    device: str = ""  # "cuda" or "cpu"
    chrf: float | None = None  # against the reference, when there is one for this line
    problem: str = ""  # why there is no translation


@dataclass
class Compared:
    """One line, through every translator compared."""

    text: str
    reference: str
    results: list[Result] = field(default_factory=list)


def compare(lines: list[str], source: str, target: str, entries: list, load, reference: str = "",
            glossary: list[str] | None = None, on_status=lambda text: None, name=lambda entry: entry.name) -> list[Compared]:
    """Each line through each translator in `entries` (two or three). `load`
    opens a translator from its entry; each is closed before the next is
    loaded. A translator that can't be loaded, or refuses a line, is reported
    in its place and the rest go on."""
    out = [Compared(line, reference_for(reference, i, len(lines))) for i, line in enumerate(lines)]
    for entry in entries[:MAX_COMPARED]:
        label = name(entry)
        on_status(f"Loading {label}...")
        try:
            translator = load(entry)
        except Exception as e:  # the reason is this translator's result
            log.warning("compare: %s could not be loaded: %s", entry.id, e)
            for row in out:
                row.results.append(Result(entry.id, label, problem=f"could not be loaded: {e}"))
            continue
        try:
            for n, row in enumerate(out, 1):
                on_status(f"{label}: translating {n} of {len(out)}...")
                row.results.append(one(translator, entry.id, label, row.text, source, target, row.reference,
                                       glossary or []))
        finally:
            translator.close()
    return out


def one(translator, model: str, label: str, text: str, source: str, target: str, reference: str = "",
        glossary: list[str] | None = None, context: list | None = None) -> Result:
    """One line through one loaded translator, scored when there is a reference."""
    request = tr.TranslationRequest(text, source, target, list(context or []), list(glossary or []))
    try:
        result = translator.translate(request)
    except tr.Refused as e:
        return Result(model, label, problem=f"refused ({e.guard}): {e}")
    except tr.TranslateError as e:
        return Result(model, label, problem=str(e))
    if not result.text:
        return Result(model, label, problem="the translation came back empty", device=result.device)
    score = round(scoring.chrf(reference, result.text, target), 1) if reference else None
    return Result(model, label, result.text, int(result.seconds * 1000), result.device, score)


def table(compared: list[Compared]) -> str:
    """A comparison as text, for the terminal and the log."""
    out = []
    for row in compared:
        out.append(row.text)
        if row.reference:
            out.append(f"  reference: {row.reference}")
        for r in row.results:
            if r.problem:
                out.append(f"  {r.name}: {r.problem}")
                continue
            score = f", chrF {r.chrf:.1f}" if r.chrf is not None else ""
            out.append(f"  {r.name}: {r.text}\n      ({r.ms} ms on the {r.device.upper()}{score})")
    if any(row.reference for row in compared):
        out.append("\n" + SCORE_NOTE)
    return "\n".join(out)


# ---------------------------------------------------------------- the window's worker


class Worker:
    """Typed text while no conversation runs, and comparisons: one thread,
    one job at a time. What happens is put on `events`, as the pipeline does,
    so the window shows a typed line exactly as it shows a spoken one."""

    def __init__(self, root: Path, pyconfig, events: queue.Queue, load=None, speak=None) -> None:
        self.root, self.pyconfig, self.events = root, pyconfig, events
        self._load = load or self._load_translator
        self._speak = speak  # speak(text, language) or None
        self._jobs: queue.Queue = queue.Queue()
        self._loaded = None  # (id, translator): kept between lines, released at Start
        self._count = 0
        self.busy = False
        self.status = ""
        self._thread = threading.Thread(target=self._run, name="volis-typed", daemon=True)
        self._thread.start()

    def _load_translator(self, entry):
        from .translate import prompts
        from . import paths

        prompt = prompts.load(paths.prompts_dir(self.root), self.pyconfig.translate.prompt)
        return tr.load(entry, prompt, self.pyconfig.translate.device)

    # ---- what the window asks for

    def translate(self, text: str, source: str, target: str, entry, glossary: list[str], speak: bool,
                  name: str = "") -> int:
        """Translate each line with `entry`; returns how many lines."""
        lines = lines_of(text)
        if lines:
            self._jobs.put(("translate", lines, source, target, entry, glossary, speak, name or entry.name))
        return len(lines)

    def compare(self, text: str, source: str, target: str, entries: list, reference: str, glossary: list[str],
                names: dict[str, str] | None = None) -> int:
        lines = lines_of(text)
        if lines and entries:
            self._jobs.put(("compare", lines, source, target, list(entries), reference, glossary, names or {}))
        return len(lines)

    def release(self) -> None:
        """Close the translator kept loaded (a conversation is about to load
        its own; two copies would not fit)."""
        self._jobs.put(("release",))

    def close(self) -> None:
        self._jobs.put(None)
        self._thread.join(10)

    def idle(self) -> bool:
        return not self.busy and self._jobs.empty()

    # ---- the thread

    def _say(self, text: str) -> None:
        self.status = text

    def _unload(self) -> None:
        if self._loaded is not None:
            try:
                self._loaded[1].close()
            except Exception as e:  # closing must never stop the next job
                log.debug("closing %s: %s", self._loaded[0], e)
            self._loaded = None

    def _run(self) -> None:
        while (job := self._jobs.get()) is not None:
            self.busy = True
            try:
                if job[0] == "release":
                    self._unload()
                elif job[0] == "translate":
                    self._translate(*job[1:])
                else:
                    self._compare(*job[1:])
            except Exception as e:  # a failed job is reported; the worker lives on
                log.exception("typed text failed")
                self.events.put(ev.Error(f"the typed text could not be translated: {e}"))
            finally:
                self.busy, self.status = False, ""
        self._unload()

    def _translate(self, lines, source, target, entry, glossary, speak, label) -> None:
        if self._loaded is None or self._loaded[0] != entry.id:
            self._unload()
            self._say(f"Loading {label}...")
            self._loaded = (entry.id, self._load(entry))
        translator = self._loaded[1]
        self._count += 1
        for k, line in enumerate(lines, 1):
            sid = f"t{self._count}.{k}"
            self._say(f"Translating {k} of {len(lines)}...")
            self.events.put(ev.SentenceMsg(sid, 0, line, source, 0.0, 0.0, False, True))
            result = one(translator, entry.id, label, line, source, target, "", glossary)
            if result.problem:
                log.warning("typed %s: not translated: %s", sid, result.problem)
                self.events.put(ev.NotTranslated(sid, result.problem))
                continue
            log.info("typed %s\n  [%s] %s\n  [%s] %s\n  (%d ms to translate on the %s)", sid, source, line,
                     target, result.text, result.ms, result.device.upper())
            self.events.put(ev.Translated(sid, result.text, target, result.ms, result.device, entry.id))
            if speak and self._speak is not None:
                try:
                    self._say("Speaking...")
                    self._speak(result.text, target)
                except Exception as e:
                    self.events.put(ev.Error(f"the typed translation was not spoken: {e}"))

    def _compare(self, lines, source, target, entries, reference, glossary, names) -> None:
        self._unload()  # the compared translators need the room
        began = time.perf_counter()
        compared = compare(lines, source, target, entries, self._load, reference, glossary, self._say,
                           name=lambda entry: names.get(entry.id, entry.name))
        log.info("compared %d translator(s) on %d line(s) in %.1f s:\n%s", len(entries), len(lines),
                 time.perf_counter() - began, table(compared))
        self.events.put(ev.MtComparison(source, target, [
            {"text": row.text, "reference": row.reference,
             "results": [vars(r) for r in row.results]} for row in compared]))
