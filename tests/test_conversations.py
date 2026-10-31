"""Saved conversations (U4). No Qt and no sound device."""

import numpy as np
import pytest

from volis import clips, conversations, paths
from volis import events as ev
from volis.conversations import ConversationError, Keeper
from volis.gui import bubbles
from volis.gui import session as ses


def a_session():
    s = ses.Session()
    s.begin("fa", "en", False, True)
    s.apply(ev.Listening())
    s.apply(ev.TurnStarted("left"))
    s.apply(ev.SentenceMsg("1.1", 1, "سلام", "fa", 10.0, 11.0))
    s.apply(ev.Translated("1.1", "Hello", "en", 300, "cuda", "m"))
    s.apply(ev.TurnCancelled())
    s.apply(ev.TurnStarted("right"))
    s.apply(ev.SentenceMsg("2.1", 2, "Welcome", "en", 20.0, 21.0))
    s.apply(ev.NotTranslated("2.1", "it repeated the sentence"))
    s.apply(ev.NothingRecognized(3, 800, 30.0))
    return s


def a_keeper(tmp_path):
    store = clips.Clips()
    store.put_heard(1, 10.0, np.ones(16000, np.float32) / 2)
    store.put_spoken("1.1", np.ones(2205, np.float32) / 2, 22050)
    keeper = Keeper(tmp_path, ("fa", "en"), "together", store, "2026-10-31 14:05")
    keeper.update(bubbles.lines_from(a_session()))
    return keeper


def test_a_conversation_comes_back_looking_the_same(tmp_path):
    saved = a_keeper(tmp_path).save("Menu", True, {"left": "Sara", "right": " "})
    again = conversations.load(saved.folder)
    assert (again.name, again.created, again.languages, again.way) == ("Menu", "2026-10-31 14:05", ("fa", "en"), "together")
    assert again.speakers == {"left": "Sara"}
    first, second, note = bubbles.saved_items(again)
    assert (first.side, first.speaker, first.when, first.original, first.translation) == ("left", "Sara", "0:10", "سلام", "Hello")
    assert (second.side, second.speaker, second.problem) == ("right", "English", "it repeated the sentence")
    assert note.kind == "note" and note.text == bubbles.NO_WORDS


def test_the_text_has_speaker_original_and_translation(tmp_path):
    saved = a_keeper(tmp_path).save("Menu", True, {"left": "Sara"})
    text = (saved.folder / "conversation.txt").read_text(encoding="utf-8")
    assert text.index("Sara") < text.index("سلام") < text.index("Hello")


def test_each_sentences_audio_is_saved_and_reads_back(tmp_path):
    saved = conversations.load(a_keeper(tmp_path).save("Menu").folder)
    line = saved.sentences()[0]
    assert saved.clip(line, conversations.ORIGINAL).seconds == 1.0
    translation = saved.clip(line, conversations.TRANSLATION)
    assert translation.rate == 22050 and translation.seconds == 0.1
    assert saved.clip(saved.sentences()[1], conversations.TRANSLATION) is None
    assert saved.has_audio()


def test_without_the_audio_only_the_words_are_kept(tmp_path):
    saved = conversations.load(a_keeper(tmp_path).save("Menu", keep_audio=False).folder)
    assert not (saved.folder / "audio").exists() and not saved.has_audio()
    assert saved.clip(saved.sentences()[0], conversations.ORIGINAL) is None
    assert saved.sentences()[0]["translation"] == "Hello"


def test_a_late_translations_speech_is_added_on_the_next_update(tmp_path):
    keeper = a_keeper(tmp_path)
    keeper.clips.put_spoken("2.1", np.ones(100, np.float32), 1000)
    session = a_session()
    lines = bubbles.lines_from(session)
    lines[1]["speech"] = "2.1"
    keeper.update(lines)
    assert keeper.conversation.lines[1]["audio_translation"].endswith("-translation.wav")


def test_a_file_is_written_once(tmp_path):
    keeper = a_keeper(tmp_path)
    path = keeper.conversation.folder / "audio" / "0001-original.wav"
    path.write_bytes(b"left alone")
    keeper.update(bubbles.lines_from(a_session()))
    assert path.read_bytes() == b"left alone"


def test_typed_sentences_have_no_original_audio(tmp_path):
    s = a_session()
    s.apply(ev.SentenceMsg("t1.1", 0, "typed", "fa", 0.0, 0.0, False, True))
    store = clips.Clips()
    store.put_heard(0, 0.0, np.ones(16000, np.float32))
    keeper = Keeper(tmp_path, ("fa", "en"), "together", store)
    keeper.update(bubbles.lines_from(s))
    assert keeper.conversation.lines[-1]["audio_original"] == ""


def test_a_crash_is_recovered_as_an_ordinary_conversation(tmp_path):
    a_keeper(tmp_path)
    found = conversations.recover(tmp_path)
    assert found.recovered and found.name == conversations.RECOVERED_NAME and found.has_audio()
    assert not paths.in_progress_dir(tmp_path).exists()
    assert conversations.load_all(tmp_path)[0][0].folder == found.folder
    assert conversations.recover(tmp_path) is None


def test_an_empty_one_is_not_worth_recovering(tmp_path):
    keeper = Keeper(tmp_path, ("fa", "en"), "together", clips.Clips())
    keeper.update([])
    assert conversations.recover(tmp_path) is None
    assert not paths.in_progress_dir(tmp_path).exists()


def test_the_in_progress_one_is_not_listed(tmp_path):
    a_keeper(tmp_path)
    assert conversations.load_all(tmp_path) == ([], [])


def test_newest_first_and_a_broken_one_is_named_not_fatal(tmp_path):
    older = Keeper(tmp_path, ("fa", "en"), "x", clips.Clips(), "2026-01-01 10:00")
    older.update([])
    older.save("Older")
    newer = Keeper(tmp_path, ("fa", "en"), "x", clips.Clips(), "2026-02-01 10:00")
    newer.update([])
    newer.save("Newer")
    broken = paths.conversations_dir(tmp_path) / "broken"
    broken.mkdir()
    (broken / "conversation.json").write_text("{not json", encoding="utf-8")
    found, problems = conversations.load_all(tmp_path)
    assert [c.name for c in found] == ["Newer", "Older"]
    assert len(problems) == 1 and str(broken) in problems[0]


def test_a_newer_format_is_refused_by_name(tmp_path):
    saved = a_keeper(tmp_path).save("Menu")
    path = saved.folder / "conversation.json"
    path.write_text(path.read_text(encoding="utf-8").replace('"version": 1', '"version": 99'), encoding="utf-8")
    with pytest.raises(ConversationError, match="newer"):
        conversations.load(saved.folder)


def test_two_with_the_same_name_get_their_own_folders(tmp_path):
    first = a_keeper(tmp_path).save("Menu")
    second = a_keeper(tmp_path).save("Menu")
    assert first.folder != second.folder and first.folder.exists() and second.folder.exists()


def test_a_name_windows_would_refuse_still_saves(tmp_path):
    saved = a_keeper(tmp_path).save('a:b/c\\d*e?"<>|.')
    assert saved.folder.is_dir() and saved.name == 'a:b/c\\d*e?"<>|.'


def test_renaming_changes_the_name_and_the_text_but_not_the_folder(tmp_path):
    saved = a_keeper(tmp_path).save("Menu")
    folder = saved.folder
    saved.name, saved.speakers = "Lunch", {"right": "Waiter"}
    saved.save_names()
    again = conversations.load(folder)
    assert (again.name, again.speakers) == ("Lunch", {"right": "Waiter"})
    assert "Lunch" in (folder / "conversation.txt").read_text(encoding="utf-8")


def test_search_looks_in_the_name_the_speakers_and_everything_said(tmp_path):
    saved = a_keeper(tmp_path).save("Menu", True, {"left": "Sara"})
    for found in ("menu", "SARA", "سلام", "hello", ""):
        assert saved.matches(found), found
    assert not saved.matches("nothing like this")


def test_a_file_named_outside_the_folder_stays_inside(tmp_path):
    saved = a_keeper(tmp_path).save("Menu")
    path = saved.audio_path({"audio_original": "..\\..\\..\\secret.wav"}, conversations.ORIGINAL)
    assert path.parent == saved.folder / "audio"


def test_only_a_conversation_can_be_removed(tmp_path):
    other = tmp_path / "something else"
    other.mkdir()
    with pytest.raises(ConversationError):
        conversations.remove(other)
    assert other.exists()
    saved = a_keeper(tmp_path).save("Menu")
    conversations.remove(saved.folder)
    assert not saved.folder.exists()


def test_a_session_can_keep_everything():
    s = ses.Session()
    s.max_lines = None
    s.begin("fa", "en", False, True)
    for n in range(ses.MAX_LINES + 50):
        s.apply(ev.SentenceMsg(f"{n}.1", n, "x", "fa", 0.0, 1.0))
    assert len(s.lines) == ses.MAX_LINES + 50
