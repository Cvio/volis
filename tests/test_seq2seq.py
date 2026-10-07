"""Dedicated translation models (P17): the language codes, discovery, and the
backend around a stand-in model. None of this needs a model installed; the
last test runs the real ones when they are there."""

import json

import pytest

from volis import models, paths
from volis import translate as tr
from volis.translate import seq2seq

NLLB_CODES = frozenset({"eng_Latn", "pes_Arab", "arb_Arab", "acm_Arab", "arz_Arab", "spa_Latn", "zho_Hans", "hin_Deva"})
MADLAD_CODES = frozenset({"en", "fa", "ar", "arz", "es", "zh", "hmn"})


# ---------------------------------------------------------------- codes


def test_nllb_codes_for_languages_and_varieties():
    assert seq2seq.code_for("nllb", "fa", NLLB_CODES) == ("pes_Arab", "")
    assert seq2seq.code_for("nllb", "ar", NLLB_CODES) == ("arb_Arab", "")
    assert seq2seq.code_for("nllb", "ar-IQ", NLLB_CODES) == ("acm_Arab", "")
    assert seq2seq.code_for("nllb", "en", NLLB_CODES) == ("eng_Latn", "")
    assert seq2seq.code_for("nllb", "es", NLLB_CODES) == ("spa_Latn", ""), "found by its ISO code, no table entry"


def test_a_variety_the_model_lacks_falls_back_to_its_language_with_a_note():
    without_iraqi = NLLB_CODES - {"acm_Arab"}
    code, note = seq2seq.code_for("nllb", "ar-IQ", without_iraqi)
    assert code == "arb_Arab" and note.startswith("translated as Arabic: this model has no ")
    code, note = seq2seq.code_for("nllb", "es-MX", NLLB_CODES)
    assert code == "spa_Latn" and "translated as Spanish" in note
    code, note = seq2seq.code_for("madlad", "ar-IQ", MADLAD_CODES)
    assert code == "ar" and note
    assert seq2seq.code_for("madlad", "ar-EG", MADLAD_CODES) == ("arz", "")


def test_a_language_the_model_does_not_have_is_refused_by_name():
    with pytest.raises(LookupError, match="Persian"):
        seq2seq.code_for("nllb", "fa", NLLB_CODES - {"pes_Arab"})
    with pytest.raises(LookupError):
        seq2seq.code_for("madlad", "hi", MADLAD_CODES)


def test_codes_are_read_from_a_vocabulary_and_from_tokenizer_json(tmp_path):
    vocab = ["hello", "<2fa>", "<2en>", "<2arz>", "<pad>", "eng_Latn", "pes_Arab", "▁the"]
    assert seq2seq.codes_from_vocab("madlad", vocab) == {"fa", "en", "arz"}
    assert seq2seq.codes_from_vocab("nllb", vocab) == {"eng_Latn", "pes_Arab"}
    (tmp_path / "tokenizer.json").write_text(json.dumps({"added_tokens": [{"content": t} for t in vocab]}), "utf-8")
    assert seq2seq.codes_in(tmp_path, "madlad") == {"fa", "en", "arz"}
    assert seq2seq.codes_in(tmp_path, "nllb") == {"eng_Latn", "pes_Arab"}
    assert seq2seq.codes_in(tmp_path / "absent", "nllb") == frozenset()
    assert seq2seq.languages("nllb", frozenset({"eng_Latn", "pes_Arab", "arb_Arab"})) == ["ar", "en", "fa"]


# ---------------------------------------------------------------- discovery


def folder(root, name, model_type, tokens=(), extra=None):
    d = root / name
    d.mkdir(parents=True)
    (d / "config.json").write_text(json.dumps({"model_type": model_type}), "utf-8")
    (d / "model.safetensors").write_bytes(b"0" * 10)
    if tokens:
        (d / "tokenizer.json").write_text(json.dumps({"added_tokens": [{"content": t} for t in tokens]}), "utf-8")
    (d / "tokenizer_config.json").write_text(json.dumps(extra or {}), "utf-8")
    return d


def test_translation_models_are_found_with_their_family_and_languages(tmp_path):
    folder(tmp_path, "nllb-200-distilled-1.3B", "m2m_100", ["eng_Latn", "pes_Arab", "acm_Arab"])
    folder(tmp_path, "madlad400-3b-mt", "t5", ["<2en>", "<2fa>"])
    folder(tmp_path, "opus-mt-fa-en", "marian")
    found = {t.id: t for t in models.discover_translators(tmp_path)}
    nllb, madlad, marian = found["nllb-200-distilled-1.3B"], found["madlad400-3b-mt"], found["opus-mt-fa-en"]
    for t in (nllb, madlad, marian):
        assert t.backend == "seq2seq" and t.enabled() and not t.has_chat_template, t
    assert (nllb.architecture, madlad.architecture, marian.architecture) == ("m2m_100", "t5", "marian")
    assert nllb.languages == ["ar", "en", "fa"] and madlad.languages == ["en", "fa"] and marian.languages == ["fa", "en"]


def test_gguf_copies_beside_a_translation_model_do_not_hide_it(tmp_path):
    d = folder(tmp_path, "madlad400-3b-mt", "t5", ["<2en>", "<2fa>"])
    (d / "model-q4k.gguf").write_bytes(b"GGUF")
    found = models.discover_translators(tmp_path)
    assert [(t.id, t.backend, t.enabled()) for t in found] == [("madlad400-3b-mt", "seq2seq", True)]


def test_fetching_a_repo_with_the_full_model_and_gguf_copies_takes_the_model():
    import sys

    sys.path.insert(0, str(paths.app_root() / "scripts"))
    import fetch_model

    repo = ["README.md", "config.json", "model.safetensors", "spiece.model", "tokenizer.json", "model-q3k.gguf",
            "model-q4k.gguf"]
    chosen = fetch_model.choose(repo, "mt", [])
    assert "model.safetensors" in chosen and "config.json" in chosen and not any(f.endswith(".gguf") for f in chosen)
    assert fetch_model.choose(repo, "mt", ["model-q4k.gguf"])[0] == "model-q4k.gguf", "asked for by name: still possible"
    with pytest.raises(SystemExit, match="Pick one"):
        fetch_model.choose(["README.md", "a-Q4_K_M.gguf", "a-Q8_0.gguf"], "mt", [])


def test_a_speech_model_and_a_model_with_no_codes_are_not_offered(tmp_path):
    folder(tmp_path, "whisper-small", "whisper")
    folder(tmp_path, "t5-no-codes", "t5", ["<pad>"])
    found = {t.id: t for t in models.discover_translators(tmp_path)}
    assert found["whisper-small"].backend != "seq2seq" and not found["whisper-small"].enabled()
    assert not found["t5-no-codes"].enabled() and "no language codes" in found["t5-no-codes"].unusable


# ---------------------------------------------------------------- the backend, around a stand-in


def stand_in(family, codes, replies, pair=None):
    """A Seq2SeqTranslator with the model replaced: `replies` maps what would
    be sent to what comes back."""
    t = object.__new__(seq2seq.Seq2SeqTranslator)
    t.name, t.device, t.family, t.codes, t.pair, t.note = "stand-in", "cpu", family, frozenset(codes), pair, ""
    t.sent = []

    def run(request):
        text, source, target, t.note = t.plan(request)
        t.sent.append((text, source, target))
        return replies.get(text, "")

    t.run = run
    return t


def test_madlad_prefixes_the_target_and_nllb_names_both_languages():
    madlad = stand_in("madlad", MADLAD_CODES, {"<2en> سلام دنیا": "Hello world"})
    assert madlad.translate(tr.TranslationRequest("سلام دنیا", "fa", "en")).text == "Hello world"
    nllb = stand_in("nllb", NLLB_CODES, {"سلام دنیا": "Hello world"})
    assert nllb.translate(tr.TranslationRequest("سلام دنیا", "fa", "en")).text == "Hello world"
    assert nllb.sent == [("سلام دنیا", "pes_Arab", "eng_Latn")]
    assert "pes_Arab" in nllb.prompt(tr.TranslationRequest("سلام دنیا", "fa", "en"))


def test_context_and_glossary_are_ignored_and_the_fallback_note_reaches_the_result():
    nllb = stand_in("nllb", NLLB_CODES - {"acm_Arab"}, {"Good morning": "صباح الخير"})
    request = tr.TranslationRequest("Good morning", "en", "ar-IQ", [tr.Turn("Hi", "مرحبا")], ["x = y"])
    result = nllb.translate(request)
    assert result.text == "صباح الخير" and nllb.sent == [("Good morning", "eng_Latn", "arb_Arab")]
    assert result.note.startswith("translated as Arabic")


def test_the_guards_still_apply_and_the_recited_guard_does_not():
    nllb = stand_in("nllb", NLLB_CODES, {"Good morning to you all": "Good morning to you all", "Hi": "x " * 400})
    with pytest.raises(tr.Refused) as echo:
        nllb.translate(tr.TranslationRequest("Good morning to you all", "en", "fa"))
    assert echo.value.guard == "echo"
    with pytest.raises(tr.Refused) as long:
        nllb.translate(tr.TranslationRequest("Hi", "en", "fa"))
    assert long.value.guard == "too long"
    assert nllb.translate(tr.TranslationRequest("unknown", "en", "fa")).text == "", "empty: the caller reports it"


def test_a_missing_language_and_the_wrong_marian_pair_are_refused_clearly():
    nllb = stand_in("nllb", NLLB_CODES - {"pes_Arab"}, {})
    with pytest.raises(tr.TranslateError, match="does not have Persian"):
        nllb.translate(tr.TranslationRequest("Hello", "en", "fa"))
    marian = stand_in("marian", (), {"سلام": "Hello"}, pair=("fa", "en"))
    assert marian.translate(tr.TranslationRequest("سلام", "fa", "en")).text == "Hello"
    with pytest.raises(tr.TranslateError, match="translates only Persian into English"):
        marian.translate(tr.TranslationRequest("Hello", "en", "fa"))


# ---------------------------------------------------------------- the real models, when installed


def test_installed_translation_models_translate_persian_with_verified_codes():
    found = [t for t in models.discover_translators(paths.mt_dir(paths.app_root()))
             if isinstance(t, models.Translator) and t.backend == "seq2seq" and t.enabled() and "fa" in t.languages]
    if not found:
        pytest.skip("no MADLAD or NLLB model in models\\mt (fetch-models.ps1)")
    for entry in found:
        translator = tr.load(entry, None)
        try:
            for tag in ("fa", "en", "ar"):
                seq2seq.code_for(translator.family, tag, translator.codes)
            out = translator.translate(tr.TranslationRequest("من یک کتاب می‌خواهم.", "fa", "en")).text
            assert "book" in out.lower(), (entry.id, out)
        finally:
            translator.close()
