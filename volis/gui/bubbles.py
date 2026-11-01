"""What the conversation shows: `Session`'s lines as bubbles and notes. No Qt in
this file: `chat.py` only draws what `items` returns."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..clips import remote_key
from . import session as ses

LEFT, RIGHT = "left", "right"

# Each language's name in its own script, so each person can find their own.
NATIVE = {"ar": "العربية", "de": "Deutsch", "en": "English", "es": "Español", "fa": "فارسی", "fr": "Français",
          "it": "Italiano", "pt": "Português", "ru": "Русский"}

TRANSLATING = "Translating ● ● ●"
HEARING = "Listening..."
WAITING_FOR_MORE = "Waiting for the rest of the sentence..."
NO_WORDS = "Volis heard something, but no words. Please say it again."
UNSURE = "Volis wasn't sure what it heard. Please say it again."
REVISED = "Corrected after hearing what followed."


@dataclass(frozen=True)
class Bubble:
    key: str
    side: str
    speaker: str
    when: str = ""
    original: str = ""
    translation: str = ""
    status: str = ""  # what is happening to it, until there is a translation
    problem: str = ""  # why there won't be a translation
    note: str = ""
    speaking: bool = False  # being spoken or replayed now: outlined
    speech: str = ""  # its spoken translation, in clips.Clips
    utterance: int = -1
    start: float = 0.0
    end: float = 0.0
    heard: str = ""  # as heard, when a clean-up step changed it
    earlier: str = ""  # the wordings a revised translation replaced

    kind = "bubble"


@dataclass(frozen=True)
class Note:
    """Something that isn't anybody's sentence, shown across the middle."""

    key: str
    text: str

    kind = "note"


def base(tag: str) -> str:
    return tag.split("-")[0].lower()


def native_name(tag: str) -> str:
    """A language tag as its speakers write it; a tag we have no name for as it is."""
    return NATIVE.get(base(tag), tag)


def _side(s: ses.Session, row: ses.Row) -> str:
    """A shared machine says whose words these are. Paired, this PC's own are
    on the right. Otherwise the language decides, so typed sentences sit with
    their speaker's."""
    if row.side in (LEFT, RIGHT):
        return row.side
    if s.paired:
        return RIGHT
    return RIGHT if base(row.source_lang) == base(s.languages[1]) else LEFT


def _row_bubble(s: ses.Session, row: ses.Row, playing: str) -> Bubble:
    status = ""
    if row.held:
        status = WAITING_FOR_MORE
    elif row.target is None and row.problem is None:
        status = TRANSLATING
    return Bubble(row.id, _side(s, row), native_name(row.source_lang), ses.clock(row.wall if row.typed else row.start),
                  row.source, row.target or "", status, row.problem or "",
                  " ".join(n for n in (row.note, REVISED if row.revised else "") if n),
                  (s.speaking and s.speaking_id == row.id) or playing == row.id, row.id if row.target else "",
                  -1 if row.typed else row.utterance, row.start, row.end, row.original or "", " | ".join(row.history))


def _live_bubble(s: ses.Session) -> Bubble:
    """The words of the sentence still being spoken."""
    _, pending, guess = s.provisional
    side = s.active_side or (RIGHT if s.paired else LEFT)
    speaker = s.languages[0] if side == LEFT or s.paired else s.languages[1]
    return Bubble("live", side, native_name(speaker), original=" ".join(p for p in (pending, guess) if p), status=HEARING)


def items(s: ses.Session, playing: str = "") -> list:
    """Everything to show, oldest first. `playing` is the speech being replayed."""
    shown: list = []
    for line in s.lines:
        if isinstance(line, ses.Row):
            shown.append(_row_bubble(s, line, playing))
        elif isinstance(line, ses.RemoteLine):
            speech = remote_key(line.lang, line.text)
            shown.append(Bubble(f"remote-{id(line)}", LEFT, native_name(line.source_lang), ses.clock(line.wall),
                                line.source_text, line.text, speaking=playing == speech, speech=speech))
        elif isinstance(line, ses.Nothing):
            shown.append(Note(f"nothing-{line.index}", NO_WORDS))
        elif isinstance(line, ses.DroppedLine):
            shown.append(Note(f"dropped-{line.index}", UNSURE))
    if s.provisional is not None:
        shown.append(_live_bubble(s))
    return shown


def lines_from(s: ses.Session) -> list[dict]:
    """What to keep of a conversation, as plain data. Nothing still being
    spoken, and no word of how far along each sentence was."""
    lines = []
    for item in items(s):
        if item.key == "live":
            continue
        data = asdict(item)
        data["kind"] = item.kind
        data.pop("status", None)
        data.pop("speaking", None)
        lines.append(data)
    return lines


def saved_items(conversation, playing: str = "") -> list:
    """A saved conversation, the way it looked."""
    shown: list = []
    for line in conversation.lines:
        if line.get("kind") == "note":
            shown.append(Note(line["key"], line["text"]))
        else:
            shown.append(Bubble(line["key"], line.get("side", LEFT), conversation.speaker(line), line.get("when", ""),
                                line.get("original", ""), line.get("translation", ""),
                                problem=line.get("problem", ""), note=line.get("note", ""),
                                speaking=playing == line["key"], heard=line.get("heard", ""),
                                earlier=line.get("earlier", "")))
    return shown


def languages_title(source: str, target: str) -> str:
    """The top bar's languages, in this order even when the first is written
    right to left (the mark at the start keeps the line reading left to right)."""
    return f"‎{native_name(source)}  /  {native_name(target)}"
