"""Typed text (P15): volis/typed.py with scripted translators. No model."""

import queue
import time
from types import SimpleNamespace

import pytest

from volis import events as ev
from volis import translate as tr
from volis import typed


class Scripted:
    """A translator that answers from a table, and says when it is closed."""

    def __init__(self, answers: dict[str, str], device: str = "cuda", log: list | None = None, name: str = "") -> None:
        self.answers, self.device, self.log, self.name = answers, device, log if log is not None else [], name
        self.requests: list[tr.TranslationRequest] = []

    def translate(self, request: tr.TranslationRequest) -> tr.TranslationResult:
        self.requests.append(request)
        if request.text not in self.answers:
            raise tr.Refused("echo", "the output is the input")
        return tr.TranslationResult(self.answers[request.text], "", 0.25, self.device)

    def close(self) -> None:
        self.log.append(f"closed {self.name}")


def entry(ident: str, name: str = ""):
    return SimpleNamespace(id=ident, name=name or ident)


FA = "کجا درد می‌کند؟"
ES = "¿Dónde le duele?"


def test_each_non_empty_line_is_a_sentence():
    assert typed.lines_of("  one \r\n\r\n two\n   \nthree") == ["one", "two", "three"]
    assert typed.lines_of("   \n") == []


def test_the_reference_is_matched_line_by_line_only_when_the_counts_agree():
    assert typed.reference_for("A\nB", 1, 2) == "B"
    assert typed.reference_for("A\nB", 0, 1) == "A B", "one line, a longer reference: all of it"
    assert typed.reference_for("A\nB", 0, 3) == "", "no telling which part belongs to which line"
    assert typed.reference_for("", 0, 1) == ""


def test_two_translators_side_by_side_with_times_devices_and_scores():
    log = []
    loaders = {"a": Scripted({ES: "Where does it hurt?"}, "cuda", log, "a"),
               "b": Scripted({ES: "Where is your pain?"}, "cpu", log, "b")}

    def load(e):
        log.append(f"loaded {e.id}")
        return loaders[e.id]

    statuses = []
    out = typed.compare([ES], "es", "en", [entry("a", "Gemma"), entry("b", "Aya")], load,
                        reference="Where does it hurt?", on_status=statuses.append)
    assert log == ["loaded a", "closed a", "loaded b", "closed b"], "one at a time: each released before the next"
    first, second = out[0].results
    assert (first.name, first.text, first.ms, first.device, first.chrf) == ("Gemma", "Where does it hurt?", 250, "cuda", 100.0)
    assert second.device == "cpu" and 0 < second.chrf < 100
    assert statuses[0] == "Loading Gemma..." and "translating 1 of 1" in statuses[1]


def test_without_a_reference_there_is_no_score():
    out = typed.compare([ES], "es", "en", [entry("a")], lambda e: Scripted({ES: "Where does it hurt?"}))
    assert out[0].results[0].chrf is None and out[0].reference == ""
    assert typed.SCORE_NOTE not in typed.table(out)


def test_a_translator_that_cannot_load_or_refuses_is_reported_and_the_rest_go_on():
    def load(e):
        if e.id == "broken":
            raise RuntimeError("not enough memory")
        return Scripted({ES: "Where does it hurt?"})

    out = typed.compare([ES, "no está en la tabla"], "es", "en", [entry("broken"), entry("ok")], load)
    assert [r.problem for r in out[0].results] == ["could not be loaded: not enough memory", ""]
    assert out[1].results[1].problem.startswith("refused (echo)")
    assert out[0].results[1].text == "Where does it hurt?"


def test_no_more_than_three_translators_are_compared():
    loaded = []

    def load(e):
        loaded.append(e.id)
        return Scripted({ES: "x y z"})

    typed.compare([ES], "es", "en", [entry(c) for c in "abcd"], load)
    assert loaded == ["a", "b", "c"]


def test_the_table_for_the_terminal_says_what_the_score_means():
    out = typed.compare([FA], "fa", "en", [entry("a", "Gemma")], lambda e: Scripted({FA: "Where does it hurt?"}),
                        reference="Where does it hurt?")
    text = typed.table(out)
    assert FA in text and "reference: Where does it hurt?" in text
    assert "Gemma: Where does it hurt?" in text and "250 ms on the CUDA, chrF 100.0" in text
    assert "does not show that a translation is correct" in text


# ---------------------------------------------------------------- the worker


@pytest.fixture
def worker():
    made = []

    def make(answers, speak=None, loads=None):
        events: queue.Queue = queue.Queue()

        def load(e):
            (loads if loads is not None else []).append(e.id)
            return Scripted(answers, name=e.id)

        w = typed.Worker(None, None, events, load=load, speak=speak)
        made.append(w)
        return w, events

    yield make
    for w in made:
        w.close()


def drain(w, events) -> list:
    deadline = time.monotonic() + 5
    while not w.idle() and time.monotonic() < deadline:
        time.sleep(0.01)
    out = []
    while not events.empty():
        out.append(events.get())
    return out


def test_typed_lines_arrive_as_sentences_marked_typed_then_their_translations(worker):
    loads, spoken = [], []
    w, events = worker({"Hola.": "Hello.", "Adiós.": "Goodbye."}, speak=lambda text, lang: spoken.append((text, lang)),
                       loads=loads)
    assert w.translate("Hola.\n\nAdiós.", "es", "en", entry("m"), [], speak=True) == 2
    got = drain(w, events)
    sentences = [e for e in got if isinstance(e, ev.SentenceMsg)]
    assert [(e.id, e.text, e.typed, e.lang) for e in sentences] == [("t1.1", "Hola.", True, "es"), ("t1.2", "Adiós.", True, "es")]
    assert [(e.id, e.text, e.lang) for e in got if isinstance(e, ev.Translated)] == [
        ("t1.1", "Hello.", "en"), ("t1.2", "Goodbye.", "en")]
    assert spoken == [("Hello.", "en"), ("Goodbye.", "en")], "Speak translations applies"
    w.translate("Hola.", "es", "en", entry("m"), [], speak=False)
    drain(w, events)
    assert loads == ["m"], "the translator stays loaded between lines"
    assert len(spoken) == 2


def test_a_line_that_is_refused_says_why_and_the_next_still_goes(worker):
    w, events = worker({"Hola.": "Hello."})
    w.translate("???\nHola.", "es", "en", entry("m"), [], speak=False)
    got = drain(w, events)
    assert [type(e).__name__ for e in got] == ["SentenceMsg", "NotTranslated", "SentenceMsg", "Translated"]
    assert "refused" in got[1].reason


def test_release_closes_the_translator_and_a_comparison_reports_one_event(worker):
    loads = []
    w, events = worker({ES: "Where does it hurt?"}, loads=loads)
    w.translate(ES, "es", "en", entry("m"), [], speak=False)
    drain(w, events)
    w.release()
    w.translate(ES, "es", "en", entry("m"), [], speak=False)
    drain(w, events)
    assert loads == ["m", "m"], "loaded again after a release"
    w.compare(ES, "es", "en", [entry("a"), entry("b")], "Where does it hurt?", [], names={"a": "Gemma"})
    got = [e for e in drain(w, events) if isinstance(e, ev.MtComparison)]
    assert len(got) == 1 and got[0].lines[0]["text"] == ES
    assert [r["name"] for r in got[0].lines[0]["results"]] == ["Gemma", "b"]
    assert got[0].lines[0]["results"][0]["chrf"] == 100.0


# ---------------------------------------------------------------- through a running conversation


def test_a_running_pipeline_translates_typed_lines_as_sentences_of_their_own(monkeypatch):
    """Typed while a conversation runs: no second translator is loaded; the
    pipeline's own takes each line, behind whatever is already waiting."""
    import numpy as np

    import installed
    from volis import asr, paths
    from volis.asr import AsrResult
    from volis.config import Config, PythonConfig
    from volis.pipeline import ArraySource, Options, Pipeline

    class Silent:
        name = "silent"

        def transcribe(self, audio, language, timestamps=True):
            return AsrResult("", None, None, language, 0.01)

        def prepare(self, language):
            pass

        def memory(self):
            return asr.Memory()

        def close(self):
            pass

    monkeypatch.setattr(asr, "load", lambda engine: Silent())
    translator = Scripted({"Hola.": "Hello.", "Adiós.": "Goodbye."})
    monkeypatch.setattr(Pipeline, "_translator", lambda self: translator)
    config = Config.parse(f'[asr]\nengine = "{installed.recognizer("es")}"\n[languages]\nsource = "es"\ntarget = "en"\n')
    events: queue.Queue = queue.Queue()
    source = ArraySource(np.zeros(16_000 * 3, np.float32), realtime=True)  # three quiet seconds to type in
    pipeline = Pipeline(paths.app_root(), config, Options(translate=True, speak=False, streaming=False), events,
                        source, PythonConfig()).start()
    seen, sent, deadline = [], False, time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            event = events.get(timeout=0.1)
        except queue.Empty:
            continue
        seen.append(event)
        if isinstance(event, ev.Listening) and not sent:
            pipeline.translate_typed(["Hola.", "Adiós."])
            sent = True
        if isinstance(event, ev.Stopped):
            break
    pipeline.join(5)
    assert not [e for e in seen if isinstance(e, ev.Error)], [e for e in seen if isinstance(e, ev.Error)]
    sentences = [e for e in seen if isinstance(e, ev.SentenceMsg)]
    assert [(e.id, e.text, e.typed, e.lang) for e in sentences] == [("t1.1", "Hola.", True, "es"), ("t1.2", "Adiós.", True, "es")]
    assert [(e.id, e.text) for e in seen if isinstance(e, ev.Translated)] == [("t1.1", "Hello."), ("t1.2", "Goodbye.")]
    assert [r.context for r in translator.requests][1], "the second line has the first as context, like speech"
