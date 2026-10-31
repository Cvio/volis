"""What the conversation shows (U1): plain rules, no Qt."""

from volis import events as ev
from volis.gui import bubbles, sample
from volis.gui import session as ses


def session(source="fa", target="en", paired=False):
    s = ses.Session()
    s.begin(source, target, False, True, paired)
    s.apply(ev.Listening())
    return s


def say(s, sid="1.1", text="سلام", lang="fa", **kwargs):
    n = int(sid.split(".")[0])
    s.apply(ev.SentenceMsg(sid, n, text, lang, 5.0, 6.0, **kwargs))


def test_a_sentence_waits_for_its_translation():
    s = session()
    say(s)
    b = bubbles.items(s)[0]
    assert (b.original, b.translation, b.status) == ("سلام", "", bubbles.TRANSLATING)
    s.apply(ev.Translated("1.1", "Hello", "en", 400, "cuda", "m"))
    b = bubbles.items(s)[0]
    assert (b.translation, b.status, b.speaker, b.when) == ("Hello", "", "فارسی", "0:05")


def test_a_refused_sentence_says_why_and_stops_waiting():
    s = session()
    say(s)
    s.apply(ev.NotTranslated("1.1", "it repeated the sentence"))
    b = bubbles.items(s)[0]
    assert (b.problem, b.status) == ("it repeated the sentence", "")


def test_a_shared_machine_keeps_each_person_on_their_side():
    s = session()
    s.apply(ev.TurnStarted("right"))
    say(s, lang="fa")  # the side says whose words these are, whatever the language
    assert bubbles.items(s)[0].side == bubbles.RIGHT


def test_typed_sentences_sit_with_their_language():
    s = session("fa-IR", "en-US")
    say(s, "1.1", lang="fa", typed=True)
    say(s, "2.1", "Hello", lang="en", typed=True)
    assert [b.side for b in bubbles.items(s)] == [bubbles.LEFT, bubbles.RIGHT]


def test_paired_my_words_are_on_the_right_and_theirs_on_the_left():
    s = session(paired=True)
    say(s)
    s.apply(ev.Remote("Front desk", "fa", "سلام", "en", "Hello"))
    mine, theirs = bubbles.items(s)
    assert mine.side == bubbles.RIGHT
    assert (theirs.side, theirs.speaker, theirs.original, theirs.translation) == (bubbles.LEFT, "English", "Hello", "سلام")


def test_only_the_sentence_being_spoken_is_outlined():
    s = session()
    for sid in ("1.1", "2.1"):
        say(s, sid)
        s.apply(ev.Translated(sid, "Hello", "en", 400, "cuda", "m"))
    s.apply(ev.SpeakingStarted("2.1", 900))
    assert [b.speaking for b in bubbles.items(s)] == [False, True]
    s.apply(ev.SpeakingEnded())
    assert [b.speaking for b in bubbles.items(s)] == [False, False]


def test_nothing_heard_and_dropped_text_are_notes_without_the_dropped_words():
    s = session()
    s.apply(ev.NothingRecognized(1, 800))
    s.apply(ev.Dropped(2, "thanks for watching", ["stock phrase"]))
    notes = bubbles.items(s)
    assert [(n.kind, n.text) for n in notes] == [("note", bubbles.NO_WORDS), ("note", bubbles.UNSURE)]


def test_words_still_being_spoken_join_the_end():
    s = session()
    s.apply(ev.TurnStarted("right"))
    s.apply(ev.Partial(1, "there", pending="hello"))
    live = bubbles.items(s)[-1]
    assert (live.key, live.side, live.original, live.status, live.speaker) == ("live", "right", "hello there",
                                                                               bubbles.HEARING, "English")


def test_a_held_fragment_says_it_is_waiting():
    s = session()
    s.apply(ev.Held("1.1", "وقتی"))
    assert bubbles.items(s)[0].status == bubbles.WAITING_FOR_MORE


def test_keys_stay_the_same_as_a_conversation_grows():
    s = session()
    say(s)
    before = [b.key for b in bubbles.items(s)]
    s.apply(ev.Translated("1.1", "Hello", "en", 400, "cuda", "m"))
    say(s, "2.1")
    assert [b.key for b in bubbles.items(s)][: len(before)] == before


def test_each_language_is_named_in_its_own_script():
    assert bubbles.native_name("fa-IR") == "فارسی"
    assert bubbles.native_name("ar-IQ") == "العربية"
    assert bubbles.native_name("xx") == "xx"
    assert bubbles.languages_title("fa", "en") == "‎فارسی  /  English"


def test_the_sample_is_a_real_stream_of_events():
    s = session()
    for event in sample.events():
        s.apply(event)
    shown = bubbles.items(s)
    assert len(shown) == len(sample.LINES) + 2
    assert shown[-1].status == bubbles.TRANSLATING
    assert [b.side for b in shown[:4]] == ["left", "right", "left", "right"]
