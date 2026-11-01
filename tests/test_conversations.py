"""Saved conversations (U4). No Qt and no sound device."""

import json
import wave
import zipfile

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


# ---------------------------------------------------------------- sharing


def a_saved(tmp_path):
    return a_keeper(tmp_path).save("Menu", True, {"left": "Sara"})


def test_a_shared_file_opens_the_same_in_another_volis(tmp_path):
    saved = a_saved(tmp_path / "one")
    shared = conversations.share_file(saved, tmp_path / "Menu")
    assert shared.name == "Menu.volis"
    opened, outcome = conversations.open_file(tmp_path / "two", shared)
    assert outcome == conversations.NEW and opened.folder.parent == paths.conversations_dir(tmp_path / "two")
    again = conversations.load(opened.folder)
    assert (again.name, again.speakers, again.lines) == (saved.name, saved.speakers, saved.lines)
    line = again.sentences()[0]
    assert len(again.clip(line, conversations.ORIGINAL).samples) == 16000
    assert again.clip(line, conversations.TRANSLATION).rate == 22050
    assert (opened.folder / "conversation.txt").is_file()


def test_opening_the_same_file_again_makes_no_copy(tmp_path):
    shared = conversations.share_file(a_saved(tmp_path / "one"), tmp_path / "Menu.volis")
    first, _ = conversations.open_file(tmp_path / "two", shared)
    second, outcome = conversations.open_file(tmp_path / "two", shared)
    assert outcome == conversations.ALREADY and second.folder == first.folder
    assert len(conversations.load_all(tmp_path / "two")[0]) == 1


def a_zip(path, data, members=()):
    with zipfile.ZipFile(path, "w") as out:
        out.writestr("conversation.json", json.dumps(data))
        for name, content in members:
            out.writestr(name, content)
    return path


def good_data(**changes):
    return {"version": 1, "name": "Menu", "created": "2026-10-31 14:05", "languages": ["fa", "en"], "lines": [
        {"kind": "bubble", "key": "1.1", "audio_original": "0001-original.wav"}], **changes}


def test_a_file_from_elsewhere_can_not_write_outside_its_folder(tmp_path):
    root = tmp_path / "root"
    outside = "../../../outside.wav"
    path = a_zip(tmp_path / "bad.volis", good_data(created="../../../escaped", name="..\\..\\away", lines=[
        {"kind": "bubble", "key": "1.1", "audio_original": outside},
        {"kind": "bubble", "key": "1.2", "audio_original": "0002-original.wav"}]),
        [(outside, b"x"), ("audio/" + outside, b"x"), ("audio/0002-original.wav", b"good"), ("audio/other.exe", b"x")])
    opened, _ = conversations.open_file(root, path)
    base = paths.conversations_dir(root)
    assert opened.folder.parent == base
    assert [p.name for p in (opened.folder / "audio").iterdir()] == ["0002-original.wav"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["bad.volis", "root"]
    assert [p.name for p in base.iterdir()] == [opened.folder.name]


@pytest.mark.parametrize("changes", [
    {"version": 99}, {"version": "1"}, {"languages": ["fa"]}, {"languages": "fa"}, {"name": 3}, {"speakers": {"left": 3}},
    {"lines": "many"}, {"lines": ["one"]}, {"lines": [{"kind": "bubble"}]},
    {"lines": [{"kind": "bubble", "key": "1", "original": 3}]}, {"lines": [{"kind": "note", "key": "1"}]},
])
def test_a_bad_file_says_so_and_leaves_nothing(tmp_path, changes):
    path = a_zip(tmp_path / "bad.volis", good_data(**changes))
    with pytest.raises(ConversationError, match="bad.volis"):
        conversations.open_file(tmp_path / "root", path)
    assert not paths.conversations_dir(tmp_path / "root").exists()


def test_something_that_is_not_a_conversation_file_says_so(tmp_path):
    not_a_zip = tmp_path / "a.volis"
    not_a_zip.write_bytes(b"hello")
    with pytest.raises(ConversationError, match="a.volis"):
        conversations.open_file(tmp_path, not_a_zip)
    other = tmp_path / "b.volis"
    with zipfile.ZipFile(other, "w") as out:
        out.writestr("something.txt", "x")
    with pytest.raises(ConversationError, match="isn't a Volis conversation file"):
        conversations.open_file(tmp_path, other)
    with pytest.raises(ConversationError, match="c.volis"):
        conversations.open_file(tmp_path, tmp_path / "c.volis")


def test_a_wav_that_is_not_ours_is_a_problem_not_a_crash(tmp_path):
    path = tmp_path / "odd.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0\0\0")
    with pytest.raises(ConversationError, match="odd.wav"):
        conversations.read_wav(path)


def test_the_shared_text_opens_as_unicode_in_word_and_notepad(tmp_path):
    written = conversations.share_text(a_saved(tmp_path), tmp_path / "Menu")
    raw = written.read_bytes()
    assert written.suffix == ".txt" and raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    words = raw.decode("utf-8-sig")
    assert words.index("Sara") < words.index("سلام") < words.index("Hello")


def test_the_whole_audio_is_each_original_then_its_translation(tmp_path):
    keeper_clips = clips.Clips()
    keeper_clips.put_heard(1, 10.0, np.full(16000, 0.5, np.float32))
    keeper_clips.put_spoken("1.1", np.full(16000, -0.5, np.float32), 16000)
    keeper_clips.put_spoken("2.1", np.full(8000, -0.25, np.float32), 16000)
    s = a_session()
    s.apply(ev.Translated("2.1", "Hi", "fa", 300, "cuda", "m"))
    keeper = Keeper(tmp_path, ("fa", "en"), "together", keeper_clips, "2026-10-31 14:05")
    keeper.update(bubbles.lines_from(s))
    saved = keeper.save("Menu")
    whole = conversations.whole_audio(saved)
    part, sentence = int(conversations.BETWEEN_PARTS * 16000), int(conversations.BETWEEN_SENTENCES * 16000)
    assert whole.rate == 16000 and len(whole.samples) == 16000 + part + 16000 + sentence + 8000 + sentence
    assert whole.samples[100] > 0 and whole.samples[16000 + 100] == 0 and whole.samples[16000 + part + 100] < 0
    written = conversations.share_audio(saved, tmp_path / "all")
    assert written.suffix == ".wav" and conversations.read_wav(written).seconds == whole.seconds


def test_the_whole_audio_brings_every_voice_to_one_rate(tmp_path):
    whole = conversations.whole_audio(a_saved(tmp_path))
    expected = 16000 + int(conversations.BETWEEN_PARTS * 16000) + 1600 + int(conversations.BETWEEN_SENTENCES * 16000)
    assert whole.rate == 16000 and abs(len(whole.samples) - expected) < 50


def test_no_audio_means_nothing_to_share(tmp_path):
    saved = a_keeper(tmp_path).save("Menu", False)
    assert conversations.whole_audio(saved) is None
    with pytest.raises(ConversationError, match="no audio"):
        conversations.share_audio(saved, tmp_path / "all.wav")
    shared = conversations.share_file(saved, tmp_path / "Menu.volis")
    assert not conversations.open_file(tmp_path / "two", shared)[0].has_audio()


# ---------------------------------------------------------------- two computers


def half(tmp_path, name, lines, audio):
    store = clips.Clips()
    keeper = Keeper(tmp_path, ("fa", "en"), "two-computers", store, "2026-10-31 14:05")
    for key, clip in audio.items():
        store.put_spoken(key, np.ones(160, np.float32) / clip, 16000)
    keeper.update(lines)
    return keeper.save(name)


MINE = [{"kind": "bubble", "key": "1.1", "side": "right", "speaker": "Persian", "original": "سلام", "translation": "Hello", "speech": "1.1x"}]
THEIRS = [{"kind": "bubble", "key": "remote-9", "side": "left", "speaker": "Persian", "original": "سلام", "translation": "Hello", "speech": "r"}]


def test_the_other_computers_file_adds_its_audio_to_this_copy(tmp_path):
    mine = half(tmp_path / "one", "Ours", [dict(l) for l in MINE], {})
    theirs = half(tmp_path / "two", "Theirs", [dict(l) for l in THEIRS], {"r": 2})
    assert not mine.has_audio()
    shared = conversations.share_file(theirs, tmp_path / "theirs")
    combined, outcome = conversations.open_file(tmp_path / "one", shared)
    assert outcome == conversations.COMBINED and combined.folder == mine.folder and combined.name == "Ours"
    again = conversations.load(mine.folder)
    assert again.clip(again.sentences()[0], conversations.TRANSLATION).rate == 16000
    assert len(conversations.load_all(tmp_path / "one")[0]) == 1


def test_another_conversation_is_not_taken_for_the_other_half(tmp_path):
    half(tmp_path / "one", "Ours", [dict(l) for l in MINE], {})
    other = [dict(THEIRS[0], translation="Something else altogether")]
    shared = conversations.share_file(half(tmp_path / "two", "Other", other, {}), tmp_path / "other")
    assert conversations.open_file(tmp_path / "one", shared)[1] == conversations.NEW


def test_received_audio_is_kept_with_the_sentence(tmp_path):
    store = clips.Clips()
    store.put_received(clips.TRANSLATION, "Hello  there", np.ones(10, np.int16).tobytes(), 22050)
    store.put_received(clips.ORIGINAL, "Hi", np.ones(10, np.int16).tobytes(), 16000)
    keeper = Keeper(tmp_path, ("fa", "en"), "two-computers", store, "2026-10-31 14:05")
    keeper.update([{"kind": "bubble", "key": "1.1", "side": "right", "translation": "Hello there", "speech": "1.1", "utterance": 1},
                   {"kind": "bubble", "key": "remote-1", "side": "left", "translation": "Hi", "speech": "r"}])
    saved = keeper.save("Menu")
    first, second = saved.sentences()
    assert first["audio_translation"] and not first["audio_original"]
    assert second["audio_original"] and not second["audio_translation"]
