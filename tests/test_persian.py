"""The Persian clean-up step (P16): each rule of volis/persian.py on real
examples, then where it runs. The half-space (U+200C) is written | in the
expected strings, so it can be seen."""

import queue
import time

import pytest

from volis import events as ev
from volis import paths, persian, typed
from volis.config import PythonConfig

VERBS = persian.load_verbs(paths.persian_verbs_file(paths.app_root()))


def clean(text: str, verbs=VERBS) -> str:
    return persian.clean(text, verbs).text.replace(persian.ZWNJ, "|")


# ---------------------------------------------------------------- 1. look-alike letters


def test_arabic_yeh_and_kaf_become_the_persian_letters():
    arabic = "علي يك كتاب دارد"  # typed with Arabic yeh (U+064A) and kaf (U+0643)
    assert "ي" in arabic and "ك" in arabic
    cleaned = persian.clean(arabic).text
    assert cleaned == "علی یک کتاب دارد"
    assert "ي" not in cleaned and "ك" not in cleaned and "ی" in cleaned and "ک" in cleaned


def test_alef_maksura_and_presentation_forms_become_ordinary_persian_letters():
    assert persian.letters("موسى") == "موسی"  # final alef maksura
    assert persian.letters("ﻓﺎﺭﺳی") == "فارسی"  # isolated presentation forms


def test_heh_with_yeh_above_becomes_heh_and_hamza():
    assert persian.letters("نامۀ من") == "نامهٔ من"


def test_teh_marbuta_is_left_alone():
    assert persian.letters("مدرسة") == "مدرسة", "Persian writes it two ways; no table can say which"


def test_text_already_in_persian_letters_is_unchanged():
    text = "این یک کتاب است."
    cleaned = persian.clean(text, VERBS)
    assert cleaned.text == text and not cleaned.changed and cleaned.original == text


# ---------------------------------------------------------------- 2. the half-space


def test_mi_and_nemi_written_apart_are_joined_to_their_verb():
    assert clean("من می خواهم به مدرسه بروم") == "من می|خواهم به مدرسه بروم"
    assert clean("که کار نمی کنم مطالعه می کنم") == "که کار نمی|کنم مطالعه می|کنم"
    assert clean("می روم") == "می|روم"


def test_mi_written_joined_on_is_separated_only_for_a_verb():
    assert clean("میخواهم بروم") == "می|خواهم بروم"
    assert clean("نمیدانم چه میگفت") == "نمی|دانم چه می|گفت"
    assert clean("میز") == "میز", "a table, not a verb"
    assert clean("میدان") == "میدان", "a square"
    assert clean("میوه میخورم") == "میوه می|خورم", "fruit; I eat"


def test_the_month_of_may_is_not_joined_to_the_next_word():
    assert clean("ماه می سال جدید") == "ماه می سال جدید"


def test_the_plural_ending_is_joined():
    assert clean("کتاب ها") == "کتاب|ها"
    assert clean("کتاب های من") == "کتاب|های من"
    assert clean("جمعهها") == "جمعه|ها", "written with nothing between"


def test_the_comparative_endings_are_joined():
    assert clean("بزرگ تر") == "بزرگ|تر"
    assert clean("بزرگ ترین شهر") == "بزرگ|ترین شهر"
    assert clean("کار گر") == "کار|گر"


def test_the_endings_after_a_word_that_ends_in_heh_are_joined():
    assert clean("خانه ام") == "خانه|ام"
    assert clean("خانه اش بزرگ است") == "خانه|اش بزرگ است"
    assert clean("خانه ی من") == "خانه|ی من"
    assert clean("نامه اید.") == "نامه|اید."


def test_what_is_already_right_and_what_is_not_a_suffix_stay():
    assert clean("من می|خواهم".replace("|", persian.ZWNJ)) == "من می|خواهم"
    assert clean("تر و خشک") == "تر و خشک", "the word 'wet', at the start"
    assert clean("و ها") == "و ها", "one letter is too short a word to carry the plural (hazm's rule: two)"


def test_spaces_stray_half_spaces_and_tatweel_are_tidied():
    assert clean("سلام   دنیـــا") == "سلام دنیا"
    assert clean(f"کاروان{persian.ZWNJ}{persian.ZWNJ}سرا") == "کاروان|سرا"
    assert clean(f" {persian.ZWNJ}سلام{persian.ZWNJ} به همه ") == "سلام به همه"


def test_without_the_verb_list_a_joined_mi_is_left_and_one_apart_is_joined_as_hazm_does():
    assert clean("میخواهم", verbs=frozenset()) == "میخواهم"
    assert clean("می خواهم", verbs=frozenset()) == "می|خواهم"


# ---------------------------------------------------------------- 3. digits and punctuation


def test_arabic_indic_digits_become_persian_ones_and_western_digits_stay():
    assert persian.letters("شماره ٤٥٦") == "شماره ۴۵۶"
    assert persian.letters("سال 1967 و ۱۳۴۶") == "سال 1967 و ۱۳۴۶"


def test_punctuation_and_vowel_marks_are_not_restyled():
    text = 'او گفت: "سلام"، 10.5 درصد... کِتاب'
    assert persian.clean(text, VERBS).text == text


# ---------------------------------------------------------------- the verb list


def test_the_verb_forms_come_from_the_list_in_config():
    assert len(VERBS) > 5000
    for form in ("خواهم", "دانم", "گفت", "کنم", "رود", "آیند", "گوید"):
        assert form in VERBS, form
    assert persian.verb_forms(["; a comment", "", "رفت#رو"]) == frozenset(
        {"رفتم", "رفتی", "رفت", "رفتیم", "رفتید", "رفتند", "روم", "روی", "رود", "رویم", "روید", "روند"})


def test_a_missing_verb_list_is_reported_and_the_rest_still_runs(tmp_path, caplog):
    verbs = persian.load_verbs(tmp_path / "config" / "persian_verbs.txt")
    assert verbs == frozenset() and str(tmp_path) in caplog.text
    assert clean("كتاب ها", verbs) == "کتاب|ها"


# ---------------------------------------------------------------- where it runs


def test_only_persian_is_cleaned_and_only_when_the_setting_is_on():
    on, off = persian.cleaner(paths.app_root(), True), persian.cleaner(paths.app_root(), False)
    text = "علي می خواهد"
    assert on(text, "fa").text == "علی می‌خواهد" and on(text, "fa").original == text
    assert on(text, "ar").text == text, "Arabic keeps its own letters"
    assert on("Hello", "en").text == "Hello"
    assert off(text, "fa").text == text
    assert PythonConfig().text.persian_cleanup is True, "on by default"


def test_a_recognized_persian_sentence_is_cleaned_before_it_is_translated(monkeypatch):
    import numpy as np

    import installed
    from test_typed import Scripted
    from volis import asr
    from volis.asr import AsrResult
    from volis.config import Config
    from volis.pipeline import ArraySource, Options, Pipeline, run_to_end

    heard = "من می خواهم يك كتاب بخرم و به خانه بروم."  # as a recognizer writes it: a space, Arabic yeh and kaf
    cleaned = "من می‌خواهم یک کتاب بخرم و به خانه بروم."

    class Heard:
        name = "scripted"

        def transcribe(self, audio, language, timestamps=True):
            return AsrResult(heard, None, None, language, 0.01)

        def prepare(self, language):
            pass

        def memory(self):
            return asr.Memory()

        def close(self):
            pass

    fixture = paths.app_root() / "tests" / "fixtures" / "fleurs" / "fa_ir"
    clips = sorted(fixture.glob("*.wav")) if fixture.is_dir() else []
    if not clips:
        pytest.skip("needs a Persian test clip (tests/fetch-fixtures.ps1)")
    from volis.filesource import read_16k_mono

    monkeypatch.setattr(asr, "load", lambda engine: Heard())
    translator = Scripted({cleaned: "I want to buy a book and go home."})
    monkeypatch.setattr(Pipeline, "_translator", lambda self: translator)
    config = Config.parse(f'[asr]\nengine = "{installed.recognizer("fa")}"\n[languages]\nsource = "fa"\ntarget = "en"\n')
    silence = np.zeros(16_000, np.float32)
    source = ArraySource(np.concatenate([silence, read_16k_mono(clips[0]), silence]))
    events: queue.Queue = queue.Queue()
    out = run_to_end(Pipeline(paths.app_root(), config, Options(translate=True, speak=False, streaming=False), events,
                              source, PythonConfig()), events)
    assert not out.errors, out.errors
    sentences = out.of(ev.SentenceMsg)
    # The clip may be cut into more than one utterance; the stand-in recognizer says the same for each.
    assert sentences and {s.text for s in sentences} == {cleaned}, "the cleaned text is what is shown"
    assert sentences[0].original == heard, "and what was heard is kept for the tooltip"
    assert {r.text for r in translator.requests} == {cleaned}, "the cleaned text is what is translated"
    assert out.of(ev.Translated)[0].text == "I want to buy a book and go home."


def test_typed_persian_is_cleaned_too(tmp_path):
    from test_typed import Scripted

    events: queue.Queue = queue.Queue()
    translator = Scripted({"علی می‌خواهد": "Ali wants"})
    worker = typed.Worker(paths.app_root(), PythonConfig(), events, load=lambda entry: translator)
    try:
        from types import SimpleNamespace

        worker.translate("علي می خواهد", "fa", "en", SimpleNamespace(id="m", name="m"), [], False)
        deadline = time.monotonic() + 5
        while not worker.idle() and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        worker.close()
    got = []
    while not events.empty():
        got.append(events.get())
    sentence = next(e for e in got if isinstance(e, ev.SentenceMsg))
    assert sentence.text == "علی می‌خواهد" and sentence.original == "علي می خواهد" and sentence.typed
    assert any(isinstance(e, ev.Translated) and e.text == "Ali wants" for e in got)
