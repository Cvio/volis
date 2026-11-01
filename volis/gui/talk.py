"""What the Talk page offers and says. No Qt in this
file: app_window.py draws these, and the tests check the words and the rules."""

from __future__ import annotations

from dataclasses import dataclass

from .. import models, varieties
from ..config import Config, PythonConfig
from ..conversations import FILE_SUFFIX
from . import bubbles
from . import session as ses

TOGETHER, TWO_COMPUTERS, HANDS_FREE = "together", "two-computers", "hands-free"
RECORDING = "recording"  # not a way of talking: a saved conversation may have come from a file


@dataclass(frozen=True)
class Way:
    """A way of talking, and which pipeline mode it is."""

    name: str
    title: str
    blurb: str
    first: str  # the label over the first language
    second: str
    swap: bool = True


WAYS = {
    TOGETHER: Way(TOGETHER, "Two people, this computer", "Each person has a button.", "One person speaks",
                  "The other person speaks"),
    TWO_COMPUTERS: Way(TWO_COMPUTERS, "Two computers", "Each person has their own computer.", "I speak", "They speak"),
    HANDS_FREE: Way(HANDS_FREE, "Hands-free", "One person speaks; Volis listens for the pauses.", "The speaker speaks",
                    "Translate into"),
}


def offered_ways(pyconfig: PythonConfig) -> list[Way]:
    """The ways of talking this customer's copy includes."""
    wanted = pyconfig.setup.ways or list(WAYS)
    return [WAYS[name] for name in WAYS if name in wanted]


def saved_way(config: Config, offered: list[Way]) -> Way:
    """The way last used, as volis.toml has it; the first offered if that one isn't."""
    if config.mode.kind == "shared":
        name = TOGETHER
    elif config.mode.kind == "continuous":
        name = HANDS_FREE
    else:
        name = TWO_COMPUTERS if config.peer.enabled else TOGETHER
    return next((w for w in offered if w.name == name), offered[0])


def languages_offered(pyconfig: PythonConfig, engines: list) -> list[str]:
    """The languages Volis can hear here, limited to what the setup includes."""
    wanted = {t.lower() for t in pyconfig.setup.languages}
    return [v.tag for v in varieties.TABLE
            if (not wanted or v.tag.lower() in wanted) and models.rank(v.tag, engines)]


def language_choice(tag: str) -> str:
    """A language in a list: as its speakers write it, and in English."""
    display, native = varieties.display_name(tag), bubbles.native_name(tag)
    return display if display.split(" (")[0] == native else f"‎{native}  -  {display}"


def languages_of(config: Config, way: str) -> tuple[str, str]:
    if way == TOGETHER:
        return config.shared.left_language, config.shared.right_language
    return config.languages.source, config.languages.target


def choose(config: Config, way: str, first: str, second: str, keep_style: bool = False) -> None:
    """Put a way and its two languages in the settings the pipeline reads."""
    config.mode.kind = {TOGETHER: "shared", HANDS_FREE: "continuous"}.get(way, "turn")
    if not keep_style:  # developer mode can hold the key while speaking
        config.mode.turn_style = "toggle"  # press to start, press again to finish
    config.peer.enabled = way == TWO_COMPUTERS
    config.languages.source, config.languages.target = first, second
    if way == TOGETHER:
        s = config.shared
        # A recognizer or voice chosen for the old language doesn't carry over.
        if s.left_language != first:
            s.left_asr, s.right_voice = "", ""
        if s.right_language != second:
            s.right_asr, s.left_voice = "", ""
        s.left_language, s.right_language = first, second


# ---------------------------------------------------------------- what a setup can offer in Settings


FASTER, ACCURATE = "faster", "accurate"


def speed_offered(pyconfig: PythonConfig) -> bool:
    """Whether this setup names a recognizer and a translator for each of Faster and More accurate."""
    return len(pyconfig.setup.faster) == 2 and len(pyconfig.setup.accurate) == 2


def speed_models(pyconfig: PythonConfig) -> tuple[str, str]:
    """(recognizer, translator) for the choice made; ("", "") with no such choice: the settings say."""
    if not speed_offered(pyconfig):
        return "", ""
    first, second = pyconfig.setup.faster if pyconfig.window.speed == FASTER else pyconfig.setup.accurate
    return first, second


def voice_choices(pyconfig: PythonConfig, voices: list) -> dict[str, list]:
    """For each language the setup includes, the voices it offers, where there is a choice."""
    named = [v for v in voices if v.dir_name in pyconfig.setup.voices and v.enabled()]
    choices = {tag: [r.engine for r in models.rank(tag, named)] for tag in pyconfig.setup.languages}
    return {tag: found for tag, found in choices.items() if len(found) > 1}


def chosen_voice(pyconfig: PythonConfig, tag: str, voices: list) -> str:
    """The voice chosen for a language; "" when there is no choice to make."""
    offered = voice_choices(pyconfig, voices).get(tag, [])
    names = [v.dir_name for v in offered]
    return next((n for n in pyconfig.window.voices if n in names), names[0] if names else "")


def apply_voices(shared, pyconfig: PythonConfig, voices: list) -> None:
    """Two people, one computer: each person's words are spoken in a voice of the other's language."""
    left, right = chosen_voice(pyconfig, shared.right_language, voices), chosen_voice(pyconfig, shared.left_language, voices)
    if left:
        shared.left_voice = left
    if right:
        shared.right_voice = right


def recognizer_choice(tag: str, engines: list, configured: str) -> str:
    """The recognizer for one language: the configured one if it covers the
    language, else the best fit. "" when none does."""
    ranked = models.rank(tag, engines)
    if any(r.engine.dir_name == configured for r in ranked):
        return configured
    return ranked[0].engine.dir_name if ranked else ""


def can_start(way: str, first: str, second: str, offered: list[str]) -> str:
    """Why Start can't be pressed; "" when it can."""
    if not offered:
        return "No speech recognition is installed, so Volis can't hear anyone yet."
    if first == second:
        return "Choose two different languages."
    if way != HANDS_FREE and second not in offered:
        return f"Volis can't hear {varieties.display_name(second)} on this computer."
    if first not in offered:
        return f"Volis can't hear {varieties.display_name(first)} on this computer."
    return ""


# ---------------------------------------------------------------- the moments


READY, LISTENING, WAIT = "ready", "listening", "wait"
PRESS, FINISH, PLEASE_WAIT, VOLIS_SPEAKING = "Press to speak", "Press when finished", "Please wait", "Volis is speaking"


@dataclass(frozen=True)
class Speak:
    """One big speak button."""

    label: str
    hint: str
    tone: str
    enabled: bool


def _busy_hint(s: ses.Session) -> str:
    return VOLIS_SPEAKING if s.speaking else PLEASE_WAIT


def side_button(s: ses.Session, side: str, name: str, key: str = "") -> Speak:
    """Two people, one computer: one person's button."""
    if s.state != ses.LISTENING:
        return Speak(name, PLEASE_WAIT, WAIT, False)
    if s.turn == ses.RECORDING:
        if s.active_side == side:
            return Speak(f"● {name}", FINISH, LISTENING, True)
        return Speak(name, "Wait", WAIT, False)
    if s.turn != ses.IDLE or s.speaking:
        return Speak(name, _busy_hint(s), WAIT, False)
    return Speak(name, f"{PRESS}  {key}".strip(), READY, True)


def talk_button(s: ses.Session) -> Speak:
    """Two computers: the one Talk button."""
    connected = s.peer is not None and s.peer.kind == "connected"
    if s.state != ses.LISTENING or not connected:
        return Speak("Talk", "Connect to the other computer first", WAIT, False)
    if s.turn == ses.RECORDING:
        return Speak("● Talk", FINISH, LISTENING, True)
    if s.turn == ses.WAITING:
        return Speak("Talk", "Asking the other computer... press to take it back", LISTENING, True)
    if s.turn != ses.IDLE or s.speaking:
        return Speak("Talk", _busy_hint(s), WAIT, False)
    if s.floor is not None and s.floor[0] == "them":
        return Speak("Talk", f"{s.floor[1]} is talking", WAIT, False)
    return Speak("Talk", f"{PRESS}  Space", READY, True)


def hands_free_words(s: ses.Session) -> str:
    if s.speaking:
        return VOLIS_SPEAKING
    return "Listening. Speak, and pause at the end of each sentence." if s.state == ses.LISTENING else PLEASE_WAIT


LOADING_WORDS = {"models": "Getting started...", "recognizer": "Loading speech recognition...",
                 "translator": "Loading the translator...", "voice": "Loading the voice..."}


def loading_words(what: str) -> str:
    return LOADING_WORDS.get(what.split(" ")[0], "Getting ready...")


def one_speaker(way: str) -> bool:
    """Whether a conversation had only the one person to name."""
    return way in (HANDS_FREE, RECORDING)


# ---------------------------------------------------------------- opening files


RECORDINGS = ("wav", "mp3", "m4a", "flac", "ogg", "opus", "aac", "mp4", "mka", "webm")
OPEN_FILTER = (f"Recordings and Volis conversations ({' '.join(f'*.{s}' for s in RECORDINGS)} *{FILE_SUFFIX})"
               ";;All files (*)")
NO_SPEECH = "Volis found no speech in that recording."
FINISH_FIRST = "Save or delete the conversation on the Talk page first."
END_FIRST = "End the conversation to open a recording."


def is_conversation_file(path) -> bool:
    return path.suffix.lower() == FILE_SUFFIX


def reading_words(progress: tuple[float, float] | None) -> str:
    """How far through a recording Volis is."""
    if progress is None:
        return "Reading the recording..."
    position, duration = progress
    if position >= duration:
        return "Finishing the last sentences..."
    return f"Reading the recording: {ses.clock(position)} of {ses.clock(duration)}"


def reading_share(progress: tuple[float, float] | None) -> int:
    """How far, out of 1000, for the bar."""
    if progress is None or progress[1] <= 0:
        return 0
    return min(1000, int(1000 * progress[0] / progress[1]))


# ---------------------------------------------------------------- the shared bar


WAIT_TO_LISTEN = "You can listen again when the turn has finished."
SPOKEN_ELSEWHERE = "This translation was spoken on the other computer."
NOTHING_TO_PLAY = "There's no spoken translation of this sentence."


def can_replay(s: ses.Session) -> bool:
    """Not while anyone is speaking, and not while Volis is working on a turn."""
    return s.turn == ses.IDLE and not s.speaking


def no_clip_words(s: ses.Session, side: str) -> str:
    """Why a sentence has nothing to play. Your own words on two computers
    were spoken on the other one."""
    return SPOKEN_ELSEWHERE if s.paired and side == bubbles.RIGHT else NOTHING_TO_PLAY


def no_saved_audio(track: str) -> str:
    if track == "original":
        return "There's no recording of the original of this sentence."
    return "There's no spoken translation of this sentence."


SAVING_WORDS = {
    "ask": "When a conversation ends, Volis asks whether to save it.",
    "always": "Every conversation is saved when it ends, with its audio.",
    "never": "Nothing is saved, and nothing of a conversation reaches the disk.",
}


def bar_time(position: float, duration: float) -> str:
    return f"{ses.clock(position)} / {ses.clock(duration)}"


# ---------------------------------------------------------------- two computers


@dataclass(frozen=True)
class Link:
    words: str
    good: bool = False
    bad: bool = False
    can_connect: bool = False  # the address box and Connect are for now
    connected: bool = False
    asking: bool = False  # the person here is to say yes or no
    button: str = ""  # Cancel or Disconnect


def link(s: ses.Session) -> Link:
    """The connection, in words. A dropped one must never look like a quiet one."""
    state = s.peer
    if state is None:
        return Link("Getting ready...")
    if state.kind == "waiting":
        words = "Choose the other computer, type its address here, or type this computer's address there."
        return Link(words if s.discovered else "Waiting for the other computer. Type its address here, or type this "
                    "computer's address there.", can_connect=True)
    if state.kind == "connecting":
        return Link("Waiting for the other computer to accept...", button="Cancel")
    if state.kind == "asking":
        return Link(f"{state.name} wants to connect. They speak {varieties.display_name(state.speaks)}.", asking=True)
    if state.kind == "connected":
        return Link(f"Connected to {state.name}", good=True, connected=True, button="Disconnect")
    if state.kind == "disconnected":
        return Link(f"Not connected. {state.reason}", bad=True, can_connect=True)
    return Link(f"Volis can't connect to another computer. {state.reason}", bad=True)


def swap_words(progress: tuple[int, int] | None) -> str:
    words = "Sharing the conversation's audio with the other computer"
    return f"{words}: {progress[0]} of {progress[1]} sentences..." if progress and progress[1] else f"{words}..."


THEY_ENDED = "The other person ended the conversation."
SWAP_FAILED = ("The other computer's audio didn't arrive. To add it later, ask them to save this conversation and "
               "share it as a Volis conversation file, then open that file here.")


def addresses_to_show(found: list[tuple[str, str]]) -> list[str]:
    """This computer's addresses, as (interface, address). A self-assigned one
    (169.254...) is only worth showing when there is nothing else: two computers
    joined by a cable and no router."""
    addresses = [address for _, address in found]
    return [a for a in addresses if not a.startswith("169.254.")] or addresses


# ---------------------------------------------------------------- problems


@dataclass(frozen=True)
class Problem:
    title: str
    advice: str
    fix: str = ""  # the button's words, when a setting can put it right
    details: str = ""


CHOOSE_MICROPHONE, CHOOSE_SPEAKERS = "Choose microphone", "Choose speakers"
MIC_SILENT = Problem("We can't hear your microphone", "Check that it's plugged in, or choose another one.",
                     CHOOSE_MICROPHONE)

_PATTERNS = (
    (("no voice is installed", "without vowel marks"), "One language won't be spoken",
     "Its translations are still shown on the screen.", ""),
    (("was not spoken", "no audio"), "A sentence wasn't spoken", "Its translation is still shown on the screen. "
     "Click on through, or check the speakers.", CHOOSE_SPEAKERS),
    (("fell behind",), "Volis fell behind", "A sentence wasn't spoken. Its translation is still shown on the screen.", ""),
    (("microphone", "start a turn", "input device", "capture"), "We can't use your microphone",
     "Check that it's plugged in, or choose another one.", CHOOSE_MICROPHONE),
    (("output device", "speakers", "playback"), "We can't use your speakers", "Check that they're on, or choose others.",
     CHOOSE_SPEAKERS),
    (("transcription", "recognition failed", "recognizer", "[asr]"), "Volis couldn't listen",
     "Try again. If it happens again, tell whoever set up Volis.", ""),
    (("translator", "translat"), "Volis couldn't translate", "Try again. If it happens again, tell whoever set up Volis.",
     ""),
)


def problem_for(error: str) -> Problem:
    """A technical message as plain words and one thing to do. The message
    itself stays available behind Details."""
    lowered = error.lower()
    for needles, title, advice, fix in _PATTERNS:
        if any(n in lowered for n in needles):
            return Problem(title, advice, fix, error)
    return Problem("Something went wrong", "Try again. If it happens again, tell whoever set up Volis.", "", error)


SILENT_DB = -75.0  # quieter than any open microphone in a real room
SILENT_SECONDS = 4.0


class MicWatch:
    """Whether the microphone has been open for a while without hearing
    anything. Counted from what it reports, so one that has stopped reporting
    altogether counts as silent too."""

    def __init__(self) -> None:
        self._since: float | None = None

    def heard(self, db: float | None, now: float) -> None:
        if db is not None and db > SILENT_DB:
            self._since = now

    def silent(self, listening: bool, now: float) -> bool:
        if not listening:
            self._since = None
            return False
        if self._since is None:
            self._since = now
        return now - self._since >= SILENT_SECONDS


def microphone_open(s: ses.Session) -> bool:
    """Whether the microphone should be hearing something now."""
    if s.state != ses.LISTENING or s.speaking:
        return False
    return s.turn == ses.RECORDING or s.mode == "continuous"


def level_share(db: float | None) -> int:
    """A level as a percentage of the meter."""
    return 0 if db is None else max(0, min(100, int((db + 60) * 100 / 60)))
