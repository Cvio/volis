"""Translation by a dedicated translation model: text in one language in, its
translation out, with no chat format and no instructions (MADLAD-400, NLLB-200,
Marian / OPUS-MT), through transformers' `AutoModelForSeq2SeqLM`.

New in volis (P17). The language is chosen by a code, differently per family:

- `t5` (MADLAD-400): a prefix token on the input, `<2fa>` for "into Persian".
  The source language is not stated.
- `m2m_100` (NLLB-200): the tokenizer is told the source (`pes_Arab`), and the
  target's code is forced as the first output token.
- `marian` (OPUS-MT): one model per language pair; no code at all.

Every code is checked against the model's own vocabulary before it is used: a
language the model doesn't have is refused by name, and a variety it lacks
falls back to its base language with a note ("translated as Arabic: this
model has no Iraqi Arabic").

What these models can't do: take earlier sentences as context, a glossary, or
a dialect instruction. Each sentence is translated on its own. Outputs pass the
same cleaning and the empty, echo and too-long guards as any translator's; the
"recited the prompt" guard has no prompt to compare against.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from .. import varieties
from ..models import Translator as TranslatorEntry
from . import TranslateError, TranslationRequest, TranslationResult, translate_checked

log = logging.getLogger(__name__)

MAX_OUTPUT_TOKENS = 256  # as the other translators
MAX_INPUT_TOKENS = 512
BEAMS = 4  # what these models were evaluated with; greedy output is noticeably worse

# model_type -> how its languages are chosen
FAMILIES = {"t5": "madlad", "mt5": "madlad", "umt5": "madlad", "m2m_100": "nllb", "marian": "marian"}

LIMITS = ("Translates each sentence on its own: it can't use earlier sentences, a glossary, "
          "or a dialect instruction.")

# NLLB-200 codes where the model's code is not simply the language's ISO 639-3
# code with its usual script. Varieties first: a tag is looked up whole, then
# by its language. Each is verified against the tokenizer when a model loads.
NLLB = {
    "ar": "arb_Arab", "ar-iq": "acm_Arab", "ar-eg": "arz_Arab", "ar-sa": "ars_Arab", "ar-ma": "ary_Arab",
    "ar-tn": "aeb_Arab", "ar-sy": "apc_Arab", "ar-lb": "apc_Arab", "ar-jo": "ajp_Arab", "ar-ps": "ajp_Arab",
    "ar-ye": "acq_Arab", "fa": "pes_Arab", "fa-af": "prs_Arab", "ps": "pbt_Arab", "ku": "kmr_Latn",
    "ckb": "ckb_Arab", "zh": "zho_Hans", "zh-tw": "zho_Hant", "zh-hk": "yue_Hant", "sw": "swh_Latn",
    "ms": "zsm_Latn", "az": "azj_Latn", "uz": "uzn_Latn", "sq": "als_Latn", "et": "est_Latn", "lv": "lvs_Latn",
    "no": "nob_Latn", "nb": "nob_Latn", "mn": "khk_Cyrl", "ne": "npi_Deva", "or": "ory_Orya", "om": "gaz_Latn",
    "mg": "plt_Latn", "yi": "ydd_Hebr", "qu": "quy_Latn", "ay": "ayr_Latn", "gn": "grn_Latn", "ff": "fuv_Latn",
    "sr": "srp_Cyrl", "kk": "kaz_Cyrl", "ky": "kir_Cyrl", "tg": "tgk_Cyrl", "ks": "kas_Arab",
}
# MADLAD-400: `<2xx>` with the language's two-letter code where it has one.
# These are the varieties it has a token of their own for.
MADLAD = {"ar-eg": "arz", "ar-iq": "acm", "ar-ma": "ary", "ar-tn": "aeb", "ar-sa": "ars", "ar-sy": "apc",
          "ar-lb": "apc", "fa-af": "prs", "zh-hk": "yue", "pt-br": "pt", "zh-tw": "zh"}

_NLLB_CODE = re.compile(r"^[a-z]{3}_[A-Z][a-z]{3}$")
_MADLAD_CODE = re.compile(r"^<2([A-Za-z_-]+)>$")


def kind(model_type: str) -> str:
    return FAMILIES.get(model_type, "")


def codes_from_vocab(family: str, tokens) -> frozenset[str]:
    """The language codes among a vocabulary's tokens: NLLB's as they are,
    MADLAD's without the `<2` and `>`."""
    if family == "nllb":
        return frozenset(t for t in tokens if _NLLB_CODE.match(t))
    if family == "madlad":
        return frozenset(m.group(1) for m in map(_MADLAD_CODE.match, tokens) if m)
    return frozenset()


def codes_in(directory: Path, family: str) -> frozenset[str]:
    """The codes in a model folder, read from its `tokenizer.json` without
    loading the tokenizer (for the model list). Empty when there is none; the
    loaded tokenizer is what a translation is checked against."""
    path = directory / "tokenizer.json"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return frozenset()
    if family == "nllb":
        return frozenset(re.findall(r'"([a-z]{3}_[A-Z][a-z]{3})"', text))
    if family == "madlad":
        return frozenset(re.findall(r'"<2([A-Za-z_-]+)>"', text))
    return frozenset()


def marian_pair(directory: Path) -> tuple[str, str] | None:
    """The one pair a Marian model translates: from its tokenizer settings, or
    else from a folder named like `opus-mt-fa-en`."""
    try:
        settings = json.loads((directory / "tokenizer_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        settings = {}
    source, target = settings.get("source_lang"), settings.get("target_lang")
    if not (isinstance(source, str) and isinstance(target, str)):
        named = re.search(r"(?i)opus-mt(?:-tc-big|-tc-base)?-([a-z]{2,3})-([a-z]{2,3})$", directory.name)
        if not named:
            return None
        source, target = named.group(1), named.group(2)
    return varieties.from_iso639_3(source.lower()), varieties.from_iso639_3(target.lower())


def _candidates(family: str, tag: str) -> list[str]:
    """Codes to try for one tag, the most exact first."""
    tag = tag.lower()
    language = varieties.language_of(tag).lower()
    three = varieties.iso639_3(tag)
    if family == "nllb":
        return [c for c in (NLLB.get(tag), NLLB.get(language)) if c] + ([three] if three else []) + [language]
    return [c for c in (MADLAD.get(tag), language, three) if c]


def code_for(family: str, tag: str, codes: frozenset[str]) -> tuple[str, str]:
    """`(code, note)`: the model's code for a language or variety tag, and a
    note when a variety fell back to its language. Raises `LookupError` when
    the model has neither."""
    variety_code = (NLLB if family == "nllb" else MADLAD).get(tag.lower())
    for candidate in _candidates(family, tag):
        if family == "nllb" and not _NLLB_CODE.match(candidate):
            # A bare ISO code: the model's entry for it, in whichever script it has.
            matches = sorted(c for c in codes if c.startswith(candidate + "_"))
            candidate = matches[0] if matches else ""
        if candidate and candidate in codes:
            fell_back = varieties.has_variety(tag) and candidate != variety_code
            note = (f"translated as {varieties.display_name(varieties.language_of(tag))}: this model has no "
                    f"{varieties.display_name(tag)}") if fell_back else ""
            return candidate, note
    raise LookupError(varieties.display_name(tag))


def languages(family: str, codes: frozenset[str]) -> list[str]:
    """volis's language tags for a model's codes, for the model list."""
    if family == "nllb":
        back = {code: varieties.language_of(tag).lower() for tag, code in NLLB.items()}
        found = {back.get(c) or varieties.from_iso639_3(c[:3]) for c in codes}
    else:
        back = {code: varieties.language_of(tag).lower() for tag, code in MADLAD.items()}
        found = {back.get(c) or varieties.from_iso639_3(c.lower()) for c in codes}
    return sorted(t for t in found if varieties.lookup(t) is not None)


class Seq2SeqTranslator:
    prompt_file = None  # there is no prompt
    uses_context = False  # the pipeline turns carry-forward context and revision off

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False))

    def __init__(self, entry: TranslatorEntry, device: str = "auto") -> None:
        import torch
        import transformers

        transformers.utils.logging.disable_progress_bar()
        transformers.utils.logging.set_verbosity_error()
        self.name = entry.id
        self.entry = entry
        self.family = kind(entry.architecture)
        if not self.family:
            raise TranslateError(f'translator "{entry.id}" is a {entry.architecture} model, which volis has no '
                                 "language codes for")
        wanted = entry.settings.get("device") or device
        if wanted == "cuda" and not torch.cuda.is_available():
            raise TranslateError(f'translator "{entry.id}" asks for the GPU, but torch sees none')
        self.device = "cuda" if wanted == "cuda" or (wanted == "auto" and torch.cuda.is_available()) else "cpu"
        dtype_name = entry.settings.get("dtype") or ("float16" if self.device == "cuda" else "float32")
        try:
            dtype = getattr(torch, dtype_name)
        except AttributeError:
            raise TranslateError(f'translator "{entry.id}": unknown dtype "{dtype_name}" in '
                                 f'{entry.path / "volis-python.toml"}') from None
        if self.device == "cuda":
            free, _total = torch.cuda.mem_get_info()
            # The files are float32; half precision takes half, plus working room for the beams.
            need = int(entry.size_bytes * (0.6 if dtype_name == "float16" else 1.2))
            if need > free:
                if entry.settings.get("device") == "cuda" or device == "cuda":
                    raise TranslateError(
                        f'translator "{entry.id}" needs about {need / 1e9:.1f} GB of GPU memory and '
                        f"{free / 1e9:.1f} GB is free. Close another model, or set [translate] device = \"cpu\".")
                log.warning('translator "%s" needs about %.1f GB of GPU memory and %.1f GB is free: on the CPU',
                            entry.id, need / 1e9, free / 1e9)
                self.device, dtype_name, dtype = "cpu", "float32", torch.float32
        began = time.perf_counter()
        try:
            self._tokenizer = transformers.AutoTokenizer.from_pretrained(str(entry.path), local_files_only=True)
            self._model = transformers.AutoModelForSeq2SeqLM.from_pretrained(
                str(entry.path), dtype=dtype, local_files_only=True).to(self.device).eval()
        except Exception as e:
            raise TranslateError(f"cannot load the translation model in {entry.path.absolute()}: {e}") from e
        self.architecture = entry.architecture
        self.codes = codes_from_vocab(self.family, self._tokenizer.get_vocab())
        self.pair = marian_pair(entry.path) if self.family == "marian" else None
        self.note = ""  # about the last translation: a variety that fell back to its language
        self._torch = torch
        log.info("loaded translation model %s (%s through transformers, %s, %d language codes) on the %s in %d ms",
                 entry.path, self.architecture, dtype_name, len(self.codes), self.device.upper(),
                 (time.perf_counter() - began) * 1000)

    def _code(self, tag: str, role: str) -> tuple[str, str]:
        try:
            return code_for(self.family, tag, self.codes)
        except LookupError as e:
            raise TranslateError(f'translator "{self.name}" does not have {e} (the {role} language). '
                                 "Pick another translator for this pair.") from None

    def plan(self, request: TranslationRequest) -> tuple[str, str, str, str]:
        """`(input text, source code, target code, note)` for a request, with
        every code checked against the model's vocabulary."""
        if self.family == "marian":
            pair = (varieties.language_of(request.source).lower(), varieties.language_of(request.target).lower())
            if self.pair is None:
                raise TranslateError(f'translator "{self.name}": volis can\'t tell which language pair it translates. '
                                     f'Name its folder like "opus-mt-fa-en" ({self.entry.path.absolute()}).')
            if pair != self.pair:
                raise TranslateError(f'translator "{self.name}" translates only {varieties.display_name(self.pair[0])} '
                                     f"into {varieties.display_name(self.pair[1])}.")
            return request.text, "", "", ""
        target, note = self._code(request.target, "target")
        if self.family == "madlad":
            return f"<2{target}> {request.text}", "", target, note
        source, _ = self._code(request.source, "source")
        return request.text, source, target, note

    def prompt(self, request: TranslationRequest) -> str:
        """What is sent (--print-prompt): the text, with the codes used."""
        text, source, target, _note = self.plan(request)
        if self.family == "nllb":
            return f"[source {source}, first output token {target}]\n{text}"
        return text

    def translate(self, request: TranslationRequest) -> TranslationResult:
        result = translate_checked(self, request, self.run, prompted=False)
        result.note = self.note
        return result

    def run(self, request: TranslationRequest) -> str:
        torch = self._torch
        text, source, target, self.note = self.plan(request)
        extra = {}
        if self.family == "nllb":
            self._tokenizer.src_lang = source
            extra["forced_bos_token_id"] = self._tokenizer.convert_tokens_to_ids(target)
        inputs = self._tokenizer(text, return_tensors="pt").to(self.device)
        length = inputs["input_ids"].shape[1]
        if length >= MAX_INPUT_TOKENS:
            raise TranslateError(f"the utterance is too long to translate: {length} tokens against a "
                                 f"{MAX_INPUT_TOKENS} token limit")
        try:
            with torch.inference_mode():
                output = self._model.generate(**inputs, max_new_tokens=MAX_OUTPUT_TOKENS, num_beams=BEAMS,
                                              do_sample=False, **extra)
        except torch.cuda.OutOfMemoryError as e:
            raise TranslateError(f'translator "{self.name}" ran out of GPU memory: {e}') from e
        return self._tokenizer.decode(output[0], skip_special_tokens=True)

    def close(self) -> None:
        import gc

        self._model = None
        self._tokenizer = None
        gc.collect()
        if self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
