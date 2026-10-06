"""What the window says, worked out without Qt (P14): a model's plain name
and its details, the big Start/Stop control, why a control is greyed out, the
warning before a choice won't fit, and the bar shown while a conversation
runs. The window draws these; the tests check the words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import session as ses

# ---------------------------------------------------------------- plain model names

# Parts of a published file or folder name that mean nothing to a person:
# the container, the level of compression, the number format.
_NOISE = re.compile(
    r"(?i)(?:^|[-_. ])(?:gguf|onnx|safetensors|int8|fp16|f16|f32|bf16|imatrix|"
    r"i?q\d(?:_[0-9a-z]+)*|\d+bit)(?=$|[-_. ])")


def clean_name(ident: str) -> str:
    """A readable name from a folder or file name: no `-GGUF`, no
    quantization tag, no extension, spaces for dashes. For a translator id
    ("folder/file.gguf") the folder is the model's name."""
    ident = ident.replace("\\", "/").rstrip("/")
    name = ident.split("/")[0] if "/" in ident else ident
    name = re.sub(r"(?i)\.(gguf|onnx|safetensors|bin)$", "", name)
    previous = None
    while previous != name:  # tags can follow one another: -Q4_K_M-GGUF
        previous = name
        name = _NOISE.sub("", name)
    name = re.sub(r"[-_]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:1].upper() + name[1:] if name else ident


def plain_name(named: bool, name: str, ident: str) -> str:
    """The name a list shows: the one a settings file gives the model, else
    the cleaned-up folder name. (P20's recommendations file comes between.)"""
    return name if named and name.strip() else clean_name(ident)


def size_text(n: int) -> str:
    return f"{n / 1e9:.1f} GB" if n >= 1e8 else f"{n / 1e6:.0f} MB"


def details(rows: list[tuple[str, str]]) -> str:
    """A tooltip: one "label: value" line each, empty values left out."""
    return "\n".join(f"{label}: {value}" for label, value in rows if value)


def quantization(file_name: str) -> str:
    found = re.search(r"(?i)(?:^|[-_.])(i?q\d(?:_[0-9a-z]+)*|int8|f16|fp16|bf16|f32)(?=$|[-_.])", file_name)
    return found.group(1).upper() if found else ""


# ---------------------------------------------------------------- the big control

START_SHORTCUT = "Ctrl+Enter"


@dataclass(frozen=True)
class Control:
    label: str  # the state, in the button's large letters
    hint: str  # what pressing it does, and its key, in small letters under it
    colour: str


def start_control(s: ses.Session, key: str, hold: bool, paused: bool = False, file_mode: bool = False) -> Control:
    """The Start/Stop button: one large control whose label and colour are
    the state (it replaces a small Start button beside a state banner)."""
    if s.state == ses.STOPPED:
        what = "translate the file" if file_mode else "start a conversation"
        return Control("START", f"Press to {what}  ·  {START_SHORTCUT}", "#268246")
    text, colour = ses.indicator(s, key, hold, paused, file_mode)
    if s.state == ses.STARTING:
        return Control(text, f"Press to cancel  ·  {START_SHORTCUT}", colour)
    return Control(text, f"Press to stop  ·  {START_SHORTCUT}", colour)


# ---------------------------------------------------------------- why a control is greyed out


@dataclass(frozen=True)
class Situation:
    """What decides which controls can be used."""

    running: bool = False
    file_mode: bool = False
    shared: bool = False  # shared machine mode
    turn_mode: bool = True
    pair: bool = False  # "Pair with another PC" is ticked
    context: bool = True
    revise: bool = False
    speak: bool = True


RUNNING = "Stop the conversation to change this."
LOCKED_WHILE_RUNNING = ("source_lang", "target_lang", "swap", "recognizer", "translator", "input_device",
                        "output_device", "speak", "half_duplex", "compare", "streaming", "use_context", "revise",
                        "hold_speech", "hold_fragments", "pair", "diacritize", "test_speakers", "test_microphone",
                        "source_live", "source_file", "open_file", "speed")


def disabled_reasons(x: Situation) -> dict[str, str]:
    """Each control that can't be used now, with the one line that says why.
    A control not in the result is usable."""
    why: dict[str, str] = {}

    def block(name: str, reason: str) -> None:
        why.setdefault(name, reason)  # the first reason is the one to act on

    if x.running:
        for name in LOCKED_WHILE_RUNNING:
            block(name, RUNNING)
    if x.file_mode:
        for name in ("input_device", "half_duplex", "test_microphone"):
            block(name, "Not used when translating a file.")
        block("mode", "Not used when translating a file.")
        block("pair", "Only with the microphone, not with a file.")
    if x.shared and not x.file_mode:
        for name in ("source_lang", "target_lang", "swap"):
            block(name, "In Shared machine mode each side has its own language, set in its column.")
        block("streaming", "Not in Shared machine mode.")
        block("pair", "Not in Shared machine mode: choose another mode first.")
    if x.pair:
        block("mode_shared", 'Not while pairing: untick "Pair with another PC" first.')
    if not x.context:
        block("revise", 'Needs "Translate with the earlier sentences as context".')
    pairing = x.pair and not x.file_mode and not x.shared
    if pairing:
        block("revise", "Not while pairing: what the other PC has shown can't be taken back.")
        block("hold_speech", "Not while pairing with another PC.")
    if not (x.context and x.revise):
        block("hold_speech", 'Needs "Revise earlier translations".')
    if not x.speak:
        block("hold_speech", 'Needs "Speak translations".')
    if not x.turn_mode or x.file_mode:
        block("turn_style", "Only when taking turns.")
    return why


# ---------------------------------------------------------------- the warning before it won't fit

TOO_SLOW_RTF = 1.0  # recognition slower than the speech itself
TOO_SLOW_TRANSLATE_MS = 3000  # a pause this long before every reply stops a conversation


@dataclass(frozen=True)
class Warning:
    text: str  # one plain sentence, or "" when there is nothing to warn about
    detail: str  # the numbers, for the tooltip


def fit_warning(verdict, speed: dict | None = None) -> Warning:
    """Before Start: will this recognizer and translator fit, and are they
    fast enough for a conversation? `verdict` is perf.verdict's; `speed` is
    what was measured for the pair on this machine, when it has been run."""
    gb = 1e9
    numbers = [f"Needs about {verdict.gpu_need / gb:.1f} GB of graphics memory; {verdict.gpu_room / gb:.1f} GB is "
               f"free for it.", f"Needs about {verdict.ram_need / gb:.1f} GB of ordinary memory; "
               f"{verdict.ram_room / gb:.1f} GB is free."]
    if speed and speed.get("runs"):
        numbers.append(f"Measured here in {speed['runs']} run(s): recognition takes {speed.get('asr_rtf')} s per "
                       f"second of speech, translation {speed.get('translate_ms')} ms a sentence.")
    else:
        numbers.append("Speed: this pair hasn't been run on this computer yet.")
    detail = "\n".join(numbers)
    if verdict.level == "no":
        if verdict.gpu_need and not verdict.gpu_room:
            return Warning("These models need an NVIDIA graphics card, and none was found.", detail)
        return Warning("These two models won't fit in this computer's memory together. They will still run, "
                       "but several times slower. Choose a smaller translator.", detail)
    if speed and speed.get("runs"):
        rtf, ms = speed.get("asr_rtf"), speed.get("translate_ms")
        if rtf is not None and rtf > TOO_SLOW_RTF:
            return Warning("This recognizer was slower than the speech itself on this computer: too slow for a "
                           "conversation.", detail)
        if ms is not None and ms > TOO_SLOW_TRANSLATE_MS:
            return Warning(f"This translator took about {ms / 1000:.0f} seconds a sentence on this computer: slow "
                           "for a conversation.", detail)
    if verdict.level == "tight":
        return Warning("These models only just fit. Close other programs that use the graphics card.", detail)
    return Warning("", detail)


# ---------------------------------------------------------------- while a conversation runs


def conversation_bar(source: str, target: str, recognizer: str, translator: str, shared: bool = False,
                     sides: tuple[str, str] = ("", "")) -> str:
    """The slim bar that takes the settings' place while running: the two
    languages and the two models."""
    languages = f"{sides[0]}  ⇄  {sides[1]}" if shared else f"{source}  →  {target}"
    models = "  ·  ".join(x for x in (recognizer, translator) if x)
    return f"{languages}      {models}" if models else languages


TEXT_SIZES = (9, 10, 11, 12, 14, 16, 18, 22, 26, 32)


def text_size_step(current: int, up: bool) -> int:
    """The next transcript text size, larger or smaller, within the list."""
    sizes = sorted(set(TEXT_SIZES) | {current})
    index = sizes.index(current) + (1 if up else -1)
    return sizes[max(0, min(index, len(sizes) - 1))]


# ---------------------------------------------------------------- test sentences

TEST_SENTENCES = {
    "en": "This is a test of the speakers.",
    "es": "Esta es una prueba de los altavoces.",
    "ar": "هذا اختبار لمكبرات الصوت.",
    "fa": "این آزمایش بلندگوها است.",
    "de": "Dies ist ein Test der Lautsprecher.",
    "fr": "Ceci est un test des haut-parleurs.",
    "it": "Questa è una prova degli altoparlanti.",
    "pt": "Este é um teste dos alto-falantes.",
    "ru": "Это проверка динамиков.",
}


def test_sentence(language: str) -> str:
    """A short sentence in the language (its base, for a variety) for Test
    speakers; "" when there is none for it."""
    return TEST_SENTENCES.get(language.split("-")[0], "")
