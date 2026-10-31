"""What the Talk page offers and says (`volis-ui-plan.md`, U2). No Qt in this
file: app_window.py draws these, and the tests check the words and the rules."""

from __future__ import annotations

from dataclasses import dataclass

from .. import models, varieties
from ..config import Config, PythonConfig
from . import bubbles
from . import session as ses

TOGETHER, TWO_COMPUTERS, HANDS_FREE = "together", "two-computers", "hands-free"


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


def choose(config: Config, way: str, first: str, second: str) -> None:
    """Put a way and its two languages in the settings the pipeline reads."""
    config.mode.kind = {TOGETHER: "shared", HANDS_FREE: "continuous"}.get(way, "turn")
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


# ---------------------------------------------------------------- two computers


@dataclass(frozen=True)
class Link:
    words: str
    good: bool = False
    bad: bool = False
    can_connect: bool = False  # the address box and Connect are for now
    connected: bool = False


def link(s: ses.Session) -> Link:
    """The connection, in words. A dropped one must never look like a quiet one."""
    state = s.peer
    if state is None:
        return Link("Getting ready...")
    if state.kind == "waiting":
        return Link("Waiting for the other computer. Type its address here, or type this computer's address there.",
                    can_connect=True)
    if state.kind == "connecting":
        return Link("Connecting...")
    if state.kind == "connected":
        return Link(f"Connected to {state.name}", good=True, connected=True)
    if state.kind == "disconnected":
        return Link(f"Not connected. {state.reason}", bad=True, can_connect=True)
    return Link(f"Volis can't connect to another computer. {state.reason}", bad=True)


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
