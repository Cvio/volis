"""A short conversation, as the pipeline would report it, with no model loaded:
what the new window shows until it can hold a real one (U2), and what its
pictures show after that."""

from __future__ import annotations

from .. import events as ev

FA, EN = "fa", "en"
LINES = [
    ("left", FA, "سلام، میشه منو رو ببینم لطفا؟", EN, "Hello, can I look at the menu, please?"),
    ("right", EN, "Of course, here you are. Today's soup is lentil.", FA, "البته، بفرمایید. سوپ امروز عدس است."),
    ("left", FA, "ممنون. آیا این غذا گوشت دارد؟ من به خاطر مشکل سلامتی نمی‌توانم گوشت بخورم و باید خیلی مراقب باشم.", EN,
     "Thank you. Does this dish have meat? I can't eat meat because of a health problem, and I have to be very careful."),
    ("right", EN, "No, it's completely vegetarian.", FA, "نه، کاملاً گیاهی است."),
]


def events() -> list:
    """The conversation, then one sentence refused and one still on its way."""
    out: list = [ev.Mode("shared"), ev.Listening()]
    for n, (side, lang, text, to, translation) in enumerate(LINES, 1):
        sid = f"{n}.1"
        start = float(n * 12)
        out += [ev.TurnStarted(side), ev.TurnEnded(), ev.Final(n, text, lang, 2400, 300),
                ev.SentenceMsg(sid, n, text, lang, start, start + 2.4),
                ev.Translated(sid, translation, to, 450, "cuda", "sample"),
                ev.SpeakingStarted(sid, 900)]
        if n < len(LINES):
            out.append(ev.SpeakingEnded())
    out += [ev.SpeakingEnded(), ev.NothingRecognized(5, 800, 60.0)]
    out += [ev.TurnStarted("left"), ev.TurnEnded(), ev.Final(6, "خیلی خوب است.", FA, 1500, 300),
            ev.SentenceMsg("6.1", 6, "خیلی خوب است.", FA, 72.0, 73.5)]
    return out
