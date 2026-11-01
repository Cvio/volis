"""The new window. Qt offscreen; no model is loaded, and the pipeline is a
stand-in that records what it was asked."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402
import zipfile  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import QRect, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import numpy as np  # noqa: E402

from volis import audio, clips, cli, conversations, models, paths  # noqa: E402
from volis import events as ev  # noqa: E402
from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui import app_window, bubbles, sample, talk, theme  # noqa: E402
from volis.gui import session as ses  # noqa: E402


class FakePipeline:
    made: list = []

    def __init__(self, root, config, options, events, source=None, pyconfig=None):
        self.config, self.options, self.events, self.source = config, options, events, source
        self.asked: list = []
        self.muted = False
        FakePipeline.made.append(self)

    def start(self):
        return self

    def stop(self):
        self.asked.append(("stop",))
        self.events.put(ev.Stopped())

    def join(self, timeout=None):
        pass

    def begin_shared_turn(self, direction):
        self.asked.append(("begin", direction.side))

    def begin_turn(self):
        self.asked.append(("begin",))

    def end_turn(self):
        self.asked.append(("end",))

    def cancel(self):
        self.asked.append(("cancel",))

    def connect(self, address):
        self.asked.append(("connect", address.host))

    def accept_peer(self):
        self.asked.append(("accept",))

    def decline_peer(self):
        self.asked.append(("decline",))

    def disconnect(self):
        self.asked.append(("disconnect",))

    def finish_with_peer(self, parts):
        self.asked.append(("finish", [(track, text) for track, text, _clip in parts]))

    def translate_typed(self, lines, direction=None):
        self.asked.append(("typed", tuple(lines), direction.side if direction else ""))


FIT = type("Fit", (), {"label": lambda self, tag: "general"})()


def _engine(name, languages):
    class E:
        dir_name, named, unusable = name, True, ""
        languages_known = True
        files, detail = [], ""

        def enabled(self):
            return True

        def missing_files(self):
            return []

    e = E()
    e.name, e.languages, e.backend = name, languages, "whisper"
    return e


@pytest.fixture
def make(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio, "list_input_devices", lambda: [])
    monkeypatch.setattr(audio, "list_output_devices", lambda: [])
    monkeypatch.setattr(app_window, "Pipeline", FakePipeline)
    monkeypatch.setattr(models, "rank", lambda tag, engines: [
        type("R", (), {"engine": e, "fit": FIT}) for e in engines if tag.split("-")[0] in e.languages])
    FakePipeline.made = []
    windows = []

    def build(config=None, pyconfig=None, found=True, developer=False):
        config = config or Config()
        config.asr.engine = ""
        w = app_window.AppWindow(tmp_path, config, pyconfig or PythonConfig(), developer)
        w.resize(1000, 700)
        w.show()
        windows.append(w)
        deadline = time.monotonic() + 10
        while found and not w.found and time.monotonic() < deadline:
            w.tick()
            time.sleep(0.01)
        if found:
            w.engines = [_engine("hears-all", ["fa", "en", "ar", "es"])]
            w.voices = [_engine("voice", ["fa", "en"])]
            w._fill_languages()
            if developer:
                w.dev.fill_pickers()
        return w

    yield build
    for w in windows:
        w.pipeline = None
        w.close()


@pytest.fixture
def window(make):
    return make()


def together(w):
    """A conversation under way: two people, one computer."""
    w.way_buttons[talk.TOGETHER].click()
    w.first_language.setCurrentIndex(w.first_language.findData("fa"))
    w.second_language.setCurrentIndex(w.second_language.findData("en"))
    w.start_button.click()
    w.events.put(ev.Listening())
    w.events.put(ev.Mode("shared"))
    w.tick()
    return w.pipeline


def shown_sample(w):
    w.session.begin("fa", "en", False, True)
    w.pipeline = FakePipeline(None, None, None, w.events)
    for event in sample.events():
        w.session.apply(event)
    w.refresh()
    QApplication.processEvents()


def test_the_flag_opens_developer_mode():
    assert cli.parse([]) == cli.Command("gui")
    assert cli.parse(["--developer"]) == cli.Command("developer")
    with pytest.raises(cli.UsageError):
        cli.parse(["--developer", "extra"])


def test_the_rail_changes_page(window):
    assert window.pages.currentIndex() == app_window.TALK
    for page in (app_window.SAVED, app_window.SETTINGS, app_window.TALK):
        window.rail_buttons[page].click()
        assert window.pages.currentIndex() == page
        assert [b for b in window.rail_buttons.values() if b.isChecked()] == [window.rail_buttons[page]]


# ---------------------------------------------------------------- the start screen


def test_it_opens_on_the_start_screen_and_waits_for_the_search(make):
    w = make(found=False)
    assert w.talk_stack.currentIndex() == app_window.START
    if not w.found:
        assert not w.start_button.isEnabled() or w._found_now is not None


def test_only_languages_it_can_hear_are_listed(make):
    w = make()
    w.engines = [_engine("a", ["fa", "en"])]
    w._fill_languages()
    tags = [w.first_language.itemData(i) for i in range(w.first_language.count())]
    assert "fa" in tags and "ar" not in tags


def test_a_customers_setup_decides_what_appears(make):
    py = PythonConfig()
    py.setup.ways, py.setup.languages = ["together"], ["fa", "en"]
    w = make(pyconfig=py)
    assert w.ways_box.isHidden(), "with one way there is nothing to choose"
    assert [w.first_language.itemData(i) for i in range(w.first_language.count())] == ["en", "fa"]
    assert w.pause_box.isHidden(), "no hands-free, no hands-free setting"


def test_swap_changes_places(window):
    window.first_language.setCurrentIndex(window.first_language.findData("fa"))
    window.second_language.setCurrentIndex(window.second_language.findData("en"))
    window.swap_button.click()
    assert (window.first_language.currentData(), window.second_language.currentData()) == ("en", "fa")


def test_the_same_language_twice_can_not_start(window):
    window.first_language.setCurrentIndex(window.first_language.findData("fa"))
    window.second_language.setCurrentIndex(window.second_language.findData("fa"))
    assert not window.start_button.isEnabled() and "different" in window.start_note.text()


def test_start_is_remembered_in_the_settings_files(window, tmp_path):
    together(window)
    saved = Config.load(tmp_path / "volis.toml")[0]
    assert (saved.mode.kind, saved.shared.left_language, saved.shared.right_language) == ("shared", "fa", "en")


# ---------------------------------------------------------------- running


def test_loading_then_the_conversation_then_end_then_new(window):
    window.way_buttons[talk.TOGETHER].click()
    window.start_button.click()
    assert window.talk_stack.currentIndex() == app_window.LOADING
    window.events.put(ev.Loading("translator x"))
    window.tick()
    assert window.loading_words.text() == "Loading the translator..."
    window.events.put(ev.Listening())
    window.events.put(ev.Mode("shared"))
    window.tick()
    assert window.talk_stack.currentIndex() == app_window.CONVERSATION and not window.top_bar.isHidden()
    window.session.apply(ev.SentenceMsg("1.1", 1, "سلام", "fa", 0.0, 1.0))
    window.end_button.click()
    window.tick()
    assert window.pipeline is None
    assert window.talk_stack.currentIndex() == app_window.CONVERSATION, "the conversation stays to be read"
    assert not window.save_box.isHidden() and window.speak_left.isHidden()
    window.delete_unsaved.click()
    assert window.talk_stack.currentIndex() == app_window.START


def test_cancel_during_loading_goes_back_to_the_start(window):
    window.start_button.click()
    window.cancel_button.click()
    window.tick()
    assert window.pipeline is None and window.talk_stack.currentIndex() == app_window.START


def test_two_buttons_take_turns(window):
    pipeline = together(window)
    assert window.speak_left.isEnabled() and "Press to speak" in window.speak_left.text()
    window.speak_left.click()
    assert pipeline.asked[-1] == ("begin", "left")
    window.events.put(ev.TurnStarted("left"))
    window.tick()
    assert "Press when finished" in window.speak_left.text() and not window.speak_right.isEnabled()
    assert window.speak_left.property("tone") == talk.LISTENING
    window.speak_left.click()
    assert pipeline.asked[-1] == ("end",)
    window.events.put(ev.TurnEnded())
    window.tick()
    assert not window.speak_left.isEnabled() and "Please wait" in window.speak_left.text()


def test_the_arrow_keys_are_the_buttons(window):
    pipeline = together(window)
    assert window.shared_key_for(Qt.Key.Key_Left) == "left" and window.shared_key_for(Qt.Key.Key_Right) == "right"
    window.shared_key("right")
    assert pipeline.asked[-1] == ("begin", "right")


def test_a_turn_prefers_the_recognizer_the_pipeline_was_told(window):
    """Or the window would ask for a second model the pipeline hadn't loaded."""
    window.engines = [_engine("first", ["fa", "en"]), _engine("second", ["fa", "en"])]
    window.config.asr.engine = "second"
    pipeline = together(window)
    assert pipeline.options.asr == "second"
    window.config.asr.engine = "first"
    assert window._direction("right").asr == "second"


def test_a_side_that_can_not_take_a_turn_says_why(window):
    pipeline = together(window)
    window.engines = []
    window.speak_left.click()
    assert not pipeline.asked and "recognizer" in window.side_note.text()


def test_two_computers_connect_then_talk(window):
    window.way_buttons[talk.TWO_COMPUTERS].click()
    window.first_language.setCurrentIndex(window.first_language.findData("fa"))
    window.second_language.setCurrentIndex(window.second_language.findData("en"))
    window.start_button.click()
    pipeline = window.pipeline
    assert pipeline.options.pair is True and pipeline.config.mode.kind == "turn"
    for event in (ev.Listening(), ev.Mode("turn"), ev.PeerMsg("waiting", port=47800)):
        window.events.put(event)
    window.tick()
    assert not window.peer_box.isHidden() and not window.speak_one.isEnabled() and window.speak_left.isHidden()
    window.peer_input.setText("192.168.1.5")
    window.connect_button.click()
    assert pipeline.asked[-1] == ("connect", "192.168.1.5")
    window.events.put(ev.PeerMsg("connected", name="Front desk"))
    window.tick()
    assert window.peer_box.isHidden() and window.speak_one.isEnabled() and "Front desk" in window.link_words.text()
    window.speak_one.click()
    assert pipeline.asked[-1] == ("begin",)
    assert window.turn_key_active()


def test_a_bad_address_is_a_problem_not_a_crash(window):
    window.way_buttons[talk.TWO_COMPUTERS].click()
    window.start_button.click()
    window.peer_input.setText("not an address at all!")
    window.connect_button.click()
    assert not window.banner.isHidden()


def test_hands_free_has_no_buttons_and_says_it_is_listening(window):
    window.way_buttons[talk.HANDS_FREE].click()
    window.start_button.click()
    assert window.pipeline.config.mode.kind == "continuous"
    window.events.put(ev.Listening())
    window.events.put(ev.Mode("continuous"))
    window.tick()
    assert window.speak_left.isHidden() and window.speak_one.isHidden() and not window.hands_free.isHidden()
    assert "Listening" in window.hands_free.text()


def test_each_person_can_type_as_themselves(window):
    pipeline = together(window)
    window.type_toggle.click()
    window.type_text.setText("Hello")
    window.type_right.click()
    assert pipeline.asked[-1] == ("typed", ("Hello",), "right") and window.type_text.text() == ""


def test_alone_typing_has_no_sides(window):
    window.way_buttons[talk.HANDS_FREE].click()
    window.start_button.click()
    window.events.put(ev.Listening())
    window.tick()
    window.type_toggle.click()
    window.type_text.setText("Hello")
    window.type_one.click()
    assert window.pipeline.asked[-1] == ("typed", ("Hello",), "")


def test_sound_applies_at_once_and_is_remembered(window, tmp_path):
    pipeline = together(window)
    window.sound.click()
    assert pipeline.muted is True and window.sound.text() == "Sound off"
    assert Config.load(tmp_path / "volis.toml")[0].tts.enabled is False


def test_sound_off_is_how_the_next_conversation_starts(make):
    config = Config()
    config.tts.enabled = False
    w = make(config=config)
    assert together(w).muted is True


# ---------------------------------------------------------------- problems


def test_a_problem_is_plain_words_with_the_message_behind_details(window):
    pipeline = together(window)
    window.events.put(ev.Error("cannot start a turn: PortAudio error -9996"))
    window.tick()
    assert window.banner_title.text() == "We can't use your microphone" and window.banner_more.isHidden()
    window.banner_details.click()
    assert "PortAudio" in window.banner_more.text() and not window.banner_more.isHidden()
    window.banner_fix.click()
    assert window.pages.currentIndex() == app_window.SETTINGS
    window.banner_close.click()
    assert window.banner.isHidden()
    assert pipeline is window.pipeline


def test_a_failed_load_returns_to_the_start_with_the_problem(window):
    window.start_button.click()
    window.events.put(ev.Error("no translator was found"))
    window.events.put(ev.Stopped())
    window.tick()
    assert window.talk_stack.currentIndex() == app_window.START and not window.banner.isHidden()
    assert window.start_button.isEnabled()


def test_a_silent_microphone_turns_red_and_clears_when_heard(window, monkeypatch):
    together(window)
    window.events.put(ev.TurnStarted("left"))
    window.tick()
    later = time.monotonic() + talk.SILENT_SECONDS + 1
    monkeypatch.setattr(app_window.time, "monotonic", lambda: later)
    window.tick()
    assert window.banner_title.text() == talk.MIC_SILENT.title and window.level.property("silent") is True
    window.events.put(ev.Level(-20.0))
    window.tick()
    assert window.banner.isHidden() and window.level.property("silent") is False


# ---------------------------------------------------------------- listening again


class FakePlayer:
    device_rate = 1000

    def __init__(self):
        self.left, self.closed = 0, False

    def clear(self):
        self.left = 0

    def play(self, samples, rate):
        self.left += len(samples)

    def queued(self):
        return self.left

    def close(self):
        self.closed = True


def with_a_sentence(w):
    """A conversation with one spoken sentence, and its speech kept."""
    pipeline = together(w)
    w.player = FakePlayer()
    pipeline.output = lambda: w.player
    for event in (ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0), ev.Translated("1.1", "Hello", "en", 300, "cuda", "m")):
        w.events.put(event)
    w.tick()
    pipeline.options.clips.put_spoken("1.1", np.ones(2000, np.float32) / 2, 1000)
    return pipeline


def click(w, key):
    w.chat.rows[key].bubble.clicked()


def test_clicking_a_bubble_plays_it_on_the_shared_bar(window):
    with_a_sentence(window)
    assert window.audio_bar.isHidden()
    click(window, "1.1")
    assert not window.audio_bar.isHidden() and window.replay.key == "1.1" and window.player.left == 2000
    assert window.bar_play.text() == "Pause" and window.bar_time.text() == "0:00 / 0:02"
    assert window.chat.rows["1.1"].bubble.property("speaking") is True
    window.player.left = 1000
    window.tick()
    assert window.bar_time.text() == "0:01 / 0:02" and window.bar_slider.value() == 500


def test_it_stops_at_the_end_and_can_be_played_again(window):
    with_a_sentence(window)
    click(window, "1.1")
    window.player.left = 0
    window.tick()
    assert window.replay.finished and window.bar_play.text() == "Play" and window.bar_slider.value() == 1000
    window.bar_play.click()
    assert window.replay.playing() and window.player.left == 2000


def test_pause_and_the_bar_move_it(window):
    with_a_sentence(window)
    click(window, "1.1")
    window.bar_play.click()
    assert window.player.left == 0 and window.bar_play.text() == "Play"
    window.bar_slider.setValue(500)
    window.bar_seek()
    assert window.replay.paused and window.replay.position() == 1.0
    window.bar_play.click()
    assert window.player.left == 1000


def test_no_replay_during_a_turn_and_taking_a_turn_stops_it(window):
    pipeline = with_a_sentence(window)
    click(window, "1.1")
    window.speak_left.click()
    assert not window.replay.active() and window.audio_bar.isHidden() and pipeline.asked[-1] == ("begin", "left")
    window.events.put(ev.TurnStarted("left"))
    window.tick()
    click(window, "1.1")
    assert not window.replay.active() and window.bar_note.text() == talk.WAIT_TO_LISTEN


def test_a_new_sentence_being_spoken_takes_over(window):
    with_a_sentence(window)
    click(window, "1.1")
    window.player.play(np.ones(300), 1000)  # the new sentence, queued before the event says so
    window.events.put(ev.SpeakingStarted("2.1", 900))
    window.tick()
    assert not window.replay.active() and window.player.left == 2300, "the new sentence must survive"


def test_your_own_words_on_two_computers_say_where_they_were_spoken(window):
    window.way_buttons[talk.TWO_COMPUTERS].click()
    window.start_button.click()
    for event in (ev.Listening(), ev.Mode("turn"), ev.SentenceMsg("1.1", 1, "سلام", "fa", 0.0, 1.0),
                  ev.Translated("1.1", "Hello", "en", 300, "cuda", "m")):
        window.events.put(event)
    window.tick()
    click(window, "1.1")
    assert window.bar_note.text() == talk.SPOKEN_ELSEWHERE and not window.bar_note.isHidden()


def test_what_arrived_from_the_other_computer_can_be_replayed(window):
    window.way_buttons[talk.TWO_COMPUTERS].click()
    window.start_button.click()
    pipeline = window.pipeline
    window.player = FakePlayer()
    pipeline.output = lambda: window.player
    for event in (ev.Listening(), ev.Mode("turn"), ev.Remote("Desk", "fa", "سلام", "en", "Hello")):
        window.events.put(event)
    window.tick()
    pipeline.options.clips.put_spoken(clips.remote_key("fa", "سلام"), np.ones(500, np.float32), 1000)
    click(window, next(iter(window.chat.rows)))
    assert window.replay.active() and window.player.left == 500


def test_after_the_end_it_still_plays_through_its_own_player(window, monkeypatch):
    with_a_sentence(window)
    made = FakePlayer()
    monkeypatch.setattr(app_window.playback, "Player", lambda device, gate: made)
    click(window, "1.1")
    window.end_button.click()
    window.tick()
    assert window.pipeline is None and not window.replay.active()
    click(window, "1.1")
    assert window.replay.player is made and made.left == 2000
    window.new_button.click()
    assert not window.replay.active() and window.clips.spoken("1.1") is None


def test_a_speaker_that_can_not_open_is_a_problem(window, monkeypatch):
    with_a_sentence(window)
    window.end_button.click()
    window.tick()

    def broken(device, gate):
        raise app_window.playback.PlaybackError('cannot open output device "x"')

    monkeypatch.setattr(app_window.playback, "Player", broken)
    click(window, "1.1")
    assert window.banner_title.text() == "We can't use your speakers"


# ---------------------------------------------------------------- saving


def ended(w):
    """A conversation with a spoken sentence, ended."""
    with_a_sentence(w)
    w.clips.put_heard(1, 1.0, np.ones(16000, np.float32) / 2)
    w.end_button.click()
    w.tick()


def only_saved(w):
    found, problems = conversations.load_all(w.root)
    assert len(found) == 1 and not problems
    return found[0]


def saved_one(w, name="Menu"):
    ended(w)
    w.save_name.setText(name)
    w.save_button.click()
    return only_saved(w)


def show_saved(w):
    w.rail_buttons[app_window.SAVED].click()
    w.saved_items.setCurrentRow(0)
    QApplication.processEvents()


def test_ending_asks_and_save_keeps_it(window, tmp_path):
    ended(window)
    assert not window.save_box.isHidden() and window.new_button.isHidden()
    window.save_name.setText("Menu")
    window.save_left.setText("Sara")
    window.save_button.click()
    saved = only_saved(window)
    assert (saved.name, saved.speakers) == ("Menu", {"left": "Sara"}) and saved.has_audio()
    assert window.save_box.isHidden() and not window.new_button.isHidden() and "Menu" in window.saved_words.text()
    assert not paths.in_progress_dir(tmp_path).exists()


def test_leaving_the_name_empty_uses_the_suggested_one(window):
    ended(window)
    window.save_button.click()
    assert "Persian and English" in only_saved(window).name


def test_keeping_no_audio(window):
    ended(window)
    window.save_audio.setChecked(False)
    window.save_button.click()
    assert not only_saved(window).has_audio()


def test_delete_forgets_it_and_goes_back_to_the_start(window, tmp_path):
    ended(window)
    window.delete_unsaved.click()
    assert conversations.load_all(tmp_path) == ([], [])
    assert not paths.in_progress_dir(tmp_path).exists()
    assert window.talk_stack.currentIndex() == app_window.START


def test_always_save_does_not_ask(make):
    py = PythonConfig()
    py.saving.mode = "always"
    w = make(pyconfig=py)
    ended(w)
    assert w.save_box.isHidden() and only_saved(w).has_audio() and not w.new_button.isHidden()


def test_never_save_writes_nothing_at_all(make, tmp_path):
    py = PythonConfig()
    py.saving.mode = "never"
    w = make(pyconfig=py)
    ended(w)
    assert w.save_box.isHidden() and not w.new_button.isHidden()
    assert not paths.conversations_dir(tmp_path).exists()


def test_nothing_said_nothing_to_ask(window, tmp_path):
    together(window)
    window.end_button.click()
    window.tick()
    assert window.save_box.isHidden() and not paths.in_progress_dir(tmp_path).exists()


def test_the_temporary_copy_keeps_up_during_the_conversation(window, tmp_path, monkeypatch):
    with_a_sentence(window)
    window.kept_at = 0.0
    window.keep_dirty = True
    window.tick()
    kept = conversations.load(paths.in_progress_dir(tmp_path))
    assert kept.sentences()[0]["translation"] == "Hello"
    assert kept.sentences()[0]["audio_translation"], "the audio is on disk as it goes"


def test_a_crash_is_found_when_volis_next_opens(make, tmp_path):
    w = make()
    with_a_sentence(w)
    w.kept_at = 0.0
    w.keep_dirty = True
    w.tick()
    again = make()  # no goodbye: the first never settled it
    assert not again.start_notice.isHidden() and "recovered" in again.start_notice.text()
    assert only_saved(again).name == conversations.RECOVERED_NAME
    w.keeper = None


def test_closing_mid_conversation_leaves_it_to_recover(make, tmp_path):
    w = make()
    with_a_sentence(w)
    w.close()
    assert conversations.recover(tmp_path).sentences()[0]["translation"] == "Hello"


def test_a_long_conversation_is_not_cut_off(window):
    together(window)
    for n in range(ses.MAX_LINES + 20):
        window.session.apply(ev.SentenceMsg(f"{n}.1", n, "x", "fa", 0.0, 1.0))
    assert len(window.session.lines) == ses.MAX_LINES + 20


def test_the_saving_choice_is_remembered(window, tmp_path):
    window.saving_buttons["never"].click()
    assert PythonConfig.load(tmp_path / "volis-python.toml")[0].saving.mode == "never"
    assert "Nothing is saved" in window.saving_words.text()


# ---------------------------------------------------------------- the Saved page


def test_saved_is_empty_at_first(window):
    window.rail_buttons[app_window.SAVED].click()
    assert window.saved_items.count() == 0 and window.saved_stack.currentIndex() == 0


def test_a_saved_conversation_reopens_with_its_bubbles(window):
    saved_one(window)
    show_saved(window)
    assert window.saved_items.count() == 1 and "Menu" in window.saved_items.item(0).text()
    assert window.saved_stack.currentIndex() == 1 and window.saved_name.text() == "Menu"
    row = window.saved_chat.rows["1.1"]
    assert (row.side, row.original.text(), row.translation.text()) == ("left", "سلام", "Hello")


def test_a_long_sentence_is_not_cut_off_on_the_saved_page(window, monkeypatch):
    """It is first drawn while its page is hidden."""
    pipeline = together(window)
    long = "Does this dish have meat? I can't eat meat because of a health problem, and I have to be very careful. " * 3
    for event in (ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0), ev.Translated("1.1", long, "en", 300, "cuda", "m")):
        window.events.put(event)
    window.tick()
    assert pipeline is window.pipeline
    window.end_button.click()
    window.tick()
    window.save_button.click()
    show_saved(window)
    label = window.saved_chat.rows["1.1"].translation
    flags = Qt.TextFlag.TextWordWrap
    needed = label.fontMetrics().boundingRect(QRect(0, 0, label.width(), 100000), flags, long).height()
    assert label.height() == needed
    for size in (1000, 800, 1300):  # and the bubble keeps up when the text has to wrap afresh
        window.resize(size, 700)
        for _ in range(3):
            QApplication.processEvents()
        row = window.saved_chat.rows["1.1"]
        row.bubble.layout().activate()
        QApplication.processEvents()
        assert row.bubble.height() >= row.bubble.layout().minimumSize().height(), size


def test_search_narrows_the_list(window):
    saved_one(window)
    show_saved(window)
    window.saved_search.setText("hello")
    assert window.saved_items.count() == 1
    window.saved_search.setText("nothing like this")
    assert window.saved_items.count() == 0 and window.saved_stack.currentIndex() == 0
    assert "Nothing matches" in window.saved_empty.text()


def test_rename_and_name_a_speaker(window):
    saved_one(window)
    show_saved(window)
    window.saved_name.setText("Lunch")
    window.saved_left.setText("Sara")
    window.saved_names_changed()
    saved = only_saved(window)
    assert (saved.name, saved.speakers) == ("Lunch", {"left": "Sara"})
    assert "Lunch" in window.saved_items.item(0).text()
    assert "Sara" in window.saved_chat.rows["1.1"].speaker.text()


def test_delete_asks_first(window):
    folder = saved_one(window).folder
    show_saved(window)
    window.saved_delete.click()
    assert not window.saved_confirm.isHidden() and folder.exists()
    window.saved_delete_no.click()
    assert window.saved_confirm.isHidden() and folder.exists()
    window.saved_delete.click()
    window.saved_delete_yes.click()
    assert not folder.exists() and window.saved_items.count() == 0


def listening_to_saved(w, monkeypatch):
    saved_one(w)
    player = FakePlayer()
    monkeypatch.setattr(app_window.playback, "Player", lambda device, gate: player)
    show_saved(w)
    return player


def test_clicking_a_saved_sentence_plays_the_translation(window, monkeypatch):
    player = listening_to_saved(window, monkeypatch)
    window.saved_chat.rows["1.1"].bubble.clicked()
    assert window.saved_replay.key == "1.1" and player.left > 0
    assert window.saved_chat.rows["1.1"].bubble.property("speaking") is True


def test_the_switch_plays_the_original(window, monkeypatch):
    player = listening_to_saved(window, monkeypatch)
    window.saved_chat.rows["1.1"].bubble.clicked()
    window.saved_track_button.click()
    assert window.saved_track == conversations.ORIGINAL and window.saved_track_button.text() == "Original"
    assert window.saved_replay.clip.rate == 16000 and window.saved_replay.key == "1.1" and player.left == 16000


def test_play_all_goes_through_them_and_stops_at_the_end(window, monkeypatch):
    player = listening_to_saved(window, monkeypatch)
    window.saved_all.click()
    assert window.saved_playing_all and window.saved_replay.key == "1.1" and window.saved_all.text() == "Stop"
    player.left = 0
    window.tick()
    assert not window.saved_playing_all and window.saved_all.text() == "Play all"


def test_a_saved_one_can_not_play_during_a_conversation(window, monkeypatch):
    listening_to_saved(window, monkeypatch)
    window.rail_buttons[app_window.TALK].click()
    window.new_button.click()
    together(window)
    window.rail_buttons[app_window.SAVED].click()
    window.saved_items.setCurrentRow(0)
    window.saved_chat.rows["1.1"].bubble.clicked()
    assert not window.saved_replay.active() and "End the conversation" in window.saved_bar.note.text()


def test_without_audio_it_says_so(window):
    ended(window)
    window.save_audio.setChecked(False)
    window.save_button.click()
    show_saved(window)
    assert not window.saved_all.isEnabled() and window.saved_bar.note.text() == "No audio was kept."


# ---------------------------------------------------------------- settings


def test_sound_settings_are_saved_and_locked_while_talking(window, tmp_path):
    window.pause.setValue(1.2)
    window.headset.setChecked(True)
    saved = Config.load(tmp_path / "volis.toml")[0]
    assert (saved.vad.min_silence_ms, saved.tts.half_duplex) == (1200, False)
    together(window)
    assert not window.input_device.isEnabled() and not window.pause.isEnabled() and not window.test_speakers.isEnabled()
    assert not window.settings_busy.isHidden()


# ---------------------------------------------------------------- the conversation


def test_the_conversation_is_drawn_as_bubbles_on_each_side(window):
    shown_sample(window)
    rows = window.chat.rows
    assert list(rows) == [i.key for i in bubbles.items(window.session)]
    assert rows["1.1"].side == bubbles.LEFT
    assert rows["2.1"].side == bubbles.RIGHT
    assert rows["4.1"].bubble.property("speaking") is False


def test_each_line_reads_in_its_own_direction(window):
    shown_sample(window)
    row = window.chat.rows["1.1"]
    assert row.original.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert row.translation.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_lines_sit_on_the_edge_their_script_starts_from(window):
    shown_sample(window)
    row = window.chat.rows["1.1"]
    inner = row.bubble.contentsRect()
    margin = row.bubble.layout().contentsMargins()
    assert row.original.geometry().right() == inner.right() - margin.right()
    assert row.translation.geometry().left() == inner.left() + margin.left()


def test_each_speakers_label_is_on_their_own_side(window):
    shown_sample(window)
    left, right = window.chat.rows["1.1"], window.chat.rows["2.1"]
    assert left.speaker.geometry().left() == left.bubble.geometry().left()
    assert right.speaker.geometry().right() == right.bubble.geometry().right()


def test_a_sentence_on_one_line_gets_one_lines_height(window):
    shown_sample(window)
    row = window.chat.rows["1.1"]
    assert row.original.height() < row.original.fontMetrics().lineSpacing() * 1.5


def test_a_short_sentence_stays_on_one_line_and_a_long_one_wraps(window):
    shown_sample(window)
    rows = window.chat.rows
    short, long = rows["4.1"].translation, rows["3.1"].translation
    assert short.height() < short.fontMetrics().lineSpacing() * 1.5
    assert long.height() > long.fontMetrics().lineSpacing() * 1.5
    assert long.width() <= window.chat.bubble_width()


def test_markup_in_what_someone_said_is_only_words(window):
    shown_sample(window)
    assert window.chat.rows["1.1"].translation.textFormat() == Qt.TextFormat.PlainText


def test_text_size_changes_the_bubbles_stops_at_the_ends_and_is_saved(window, tmp_path):
    shown_sample(window)
    before = window.chat.rows["1.1"].translation.font().pointSize()
    window.larger.click()
    assert window.chat.rows["1.1"].translation.font().pointSize() > before
    assert PythonConfig.load(tmp_path / "volis-python.toml")[0].window.text_size == window.pyconfig.window.text_size
    for _ in range(40):
        if window.larger.isEnabled():
            window.larger.click()
    assert not window.larger.isEnabled() and window.smaller.isEnabled()


def test_a_theme_is_applied_shown_and_saved(window, tmp_path):
    assert window.theme_buttons["graphite"].isChecked()
    window.rail_buttons[app_window.SETTINGS].click()
    window.theme_buttons["warm-charcoal"].click()
    assert theme.WARM_CHARCOAL.background in window.styleSheet()
    assert window.theme_buttons["warm-charcoal"].isChecked() and not window.theme_buttons["graphite"].isChecked()
    assert PythonConfig.load(tmp_path / "volis-python.toml")[0].window.theme == "warm-charcoal"


def test_opening_uses_the_remembered_theme(make):
    config = PythonConfig()
    config.window.theme = "midnight"
    w = make(pyconfig=config)
    assert theme.MIDNIGHT.background in w.styleSheet()
    assert w.theme_buttons["midnight"].isChecked()


def test_a_save_that_fails_names_the_file(window, tmp_path):
    (tmp_path / "volis-python.toml").mkdir()
    window.choose_theme("midnight")
    assert str(tmp_path) in window.settings_problem.text()


def test_redrawing_nothing_new_leaves_the_rows_alone(window):
    shown_sample(window)
    before = dict(window.chat.rows)
    window.draw_conversation()
    assert all(window.chat.rows[k] is before[k] for k in before)


def test_lines_removed_from_the_session_are_removed_from_the_screen(window):
    shown_sample(window)
    window.session.clear()
    window.draw_conversation()
    assert window.chat.rows == {}


def test_a_live_session_state_is_not_stopped_by_drawing(window):
    together(window)
    assert window.session.state == ses.LISTENING


# ---------------------------------------------------------------- open and share


def recording_chosen(w, tmp_path, monkeypatch, seconds=3):
    monkeypatch.setattr(app_window, "read_16k_mono", lambda path: np.zeros(16000 * seconds, np.float32))
    w.open_path(tmp_path / "interview.m4a")
    deadline = time.monotonic() + 5
    while w.opening_audio is None and time.monotonic() < deadline:
        w.tick()
        time.sleep(0.01)
    w.recording_language.setCurrentIndex(w.recording_language.findData("fa"))
    w.recording_target.setCurrentIndex(w.recording_target.findData("en"))
    w.refresh()


def reading(w, tmp_path, monkeypatch):
    recording_chosen(w, tmp_path, monkeypatch)
    w.opening_start.click()
    w.events.put(ev.Listening())
    w.events.put(ev.Mode("continuous"))
    w.tick()
    return w.pipeline


def test_a_recording_asks_for_its_languages(window, tmp_path, monkeypatch):
    recording_chosen(window, tmp_path, monkeypatch, 65)
    assert window.talk_stack.currentIndex() == app_window.OPENING
    assert window.pages.currentIndex() == app_window.TALK
    assert "interview.m4a" in window.opening_file.text() and "1:05" in window.opening_file.text()
    assert window.opening_start.isEnabled()
    window.recording_target.setCurrentIndex(window.recording_target.findData("fa"))
    window.refresh()
    assert not window.opening_start.isEnabled()
    window.opening_cancel.click()
    assert window.talk_stack.currentIndex() == app_window.START


def test_a_recording_runs_from_the_file_at_full_speed_and_silently(window, tmp_path, monkeypatch):
    pipeline = reading(window, tmp_path, monkeypatch)
    assert pipeline.options.speak and pipeline.options.clips is window.clips and pipeline.options.streaming is False
    assert pipeline.muted and pipeline.source.lossless and not pipeline.source.realtime
    assert not pipeline.options.pair
    assert window.config.languages.source == "fa" and window.config.languages.target == "en"


def test_reading_shows_how_far_and_has_no_microphone_or_buttons(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    window.events.put(ev.Progress(30.0, 120.0))
    window.tick()
    assert window.talk_stack.currentIndex() == app_window.CONVERSATION
    assert window.hands_free.text() == "Reading the recording: 0:30 of 2:00" and window.read_bar.value() == 250
    assert window.end_button.text() == "Stop reading"
    for hidden in (window.sound, window.level, window.speak_left, window.speak_one, window.type_toggle):
        assert hidden.isHidden()


def test_a_silent_file_never_warns_about_the_microphone(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    window.mic_watch.silent(True, time.monotonic() - 100)
    window.tick()
    assert not window.mic_silent


def test_a_recording_ends_like_a_conversation_named_after_its_file(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    for event in (ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0), ev.Translated("1.1", "Hello", "en", 300, "cuda", "m"),
                  ev.Stopped()):
        window.events.put(event)
    window.tick()
    assert window.save_name.placeholderText() == "interview" and window.save_right.isHidden()
    window.save_button.click()
    saved = only_saved(window)
    assert saved.name == "interview" and saved.way == talk.RECORDING


def test_a_recording_with_no_speech_says_so(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    window.events.put(ev.Stopped())
    window.tick()
    assert window.talk_stack.currentIndex() == app_window.START
    assert window.start_notice.text() == talk.NO_SPEECH and not window.start_notice.isHidden()


def test_a_file_that_can_not_be_read_says_so(window, tmp_path, monkeypatch):
    def fails(path):
        raise app_window.FileSourceError(f"cannot decode {path}")

    monkeypatch.setattr(app_window, "read_16k_mono", fails)
    window.open_path(tmp_path / "broken.m4a")
    deadline = time.monotonic() + 5
    while not window.opening_note.text() and time.monotonic() < deadline:
        window.tick()
        time.sleep(0.01)
    assert "broken.m4a" in window.opening_note.text() and not window.opening_note.isHidden()
    assert not window.opening_start.isEnabled()


def test_a_recording_waits_for_the_conversation_in_hand(window, tmp_path, monkeypatch):
    together(window)
    window.open_path(tmp_path / "a.m4a")
    assert window.opening is None and window.saved_problem.text() == talk.END_FIRST
    window.pages.setCurrentIndex(app_window.TALK)
    ended_window = window
    ended_window.events.put(ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0))
    ended_window.end_button.click()
    ended_window.tick()
    window.open_path(tmp_path / "a.m4a")
    assert window.opening is None and window.saved_problem.text() == talk.FINISH_FIRST
    assert not window.save_box.isHidden()


def test_starting_a_conversation_after_a_recording_is_a_conversation_again(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    window.events.put(ev.Stopped())
    window.tick()
    pipeline = together(window)
    assert not window.reading and pipeline.source is None if hasattr(pipeline, "source") else True
    assert not window.speak_left.isHidden()


def picking(monkeypatch, path):
    monkeypatch.setattr(app_window.QFileDialog, "getSaveFileName", lambda *a, **k: (str(path), ""))


def test_each_kind_of_share_writes_its_file(window, tmp_path, monkeypatch):
    saved_one(window)
    show_saved(window)
    for action, name, check in ((window.share_conversation, "out.volis", lambda p: zipfile.is_zipfile(p)),
                                (window.share_words, "out.txt", lambda p: "Hello" in p.read_text(encoding="utf-8-sig")),
                                (window.share_sound, "out.wav", lambda p: conversations.read_wav(p).seconds > 1)):
        picking(monkeypatch, tmp_path / name)
        action.trigger()
        assert check(tmp_path / name) and name in window.saved_status.text()


def test_cancelling_a_share_writes_nothing(window, tmp_path, monkeypatch):
    saved_one(window)
    show_saved(window)
    monkeypatch.setattr(app_window.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    before = set(tmp_path.iterdir())
    window.share_conversation.trigger()
    assert set(tmp_path.iterdir()) == before and window.saved_status.isHidden()


def test_a_share_that_fails_says_where(window, tmp_path, monkeypatch):
    saved_one(window)
    show_saved(window)
    picking(monkeypatch, tmp_path / "no-such-folder" / "out.txt")
    window.share_words.trigger()
    assert "no-such-folder" in window.saved_problem.text()
    assert QApplication.overrideCursor() is None


def test_audio_can_not_be_shared_when_none_was_kept(window):
    ended(window)
    window.save_audio.setChecked(False)
    window.save_button.click()
    show_saved(window)
    assert not window.share_sound.isEnabled() and window.share_words.isEnabled()


def test_open_shows_a_shared_conversation_in_saved(make, tmp_path, monkeypatch):
    w = make()
    saved_one(w, "Lunch")
    show_saved(w)
    shared_file = tmp_path / "out" / "Lunch.volis"
    shared_file.parent.mkdir()
    conversations.share_file(only_saved(w), shared_file)
    conversations.remove(only_saved(w).folder)
    w.rail_buttons[app_window.TALK].click()
    w.open_path(shared_file)
    assert w.pages.currentIndex() == app_window.SAVED
    assert w.saved_current.name == "Lunch" and w.saved_items.currentRow() == 0
    assert w.saved_name.text() == "Lunch" and "Opened Lunch" in w.saved_status.text()
    assert w.saved_chat.rows["1.1"].translation.text()
    w.open_path(shared_file)
    assert "already in Saved" in w.saved_status.text() and len(conversations.load_all(tmp_path)[0]) == 1


def test_a_bad_conversation_file_is_a_problem_on_the_saved_page(window, tmp_path):
    bad = tmp_path / "bad.volis"
    bad.write_bytes(b"not a zip")
    window.open_path(bad)
    assert window.pages.currentIndex() == app_window.SAVED and "bad.volis" in window.saved_problem.text()
    assert not window.saved_problem.isHidden()


def test_open_is_offered_on_the_start_screen_and_in_saved(window, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(app_window.QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "x.volis"), ""))
    monkeypatch.setattr(window, "open_path", opened.append)
    window.start_open.click()
    window.saved_open.click()
    assert opened == [tmp_path / "x.volis"] * 2
    assert not window.start_open.isHidden()


# ---------------------------------------------------------------- developer mode


def test_a_customer_has_no_route_to_the_developer_pages(window):
    assert window.dev is None and window.pages.count() == 3 and set(window.rail_buttons) == {0, 1, 2}
    assert "volis-developer" not in window.windowTitle()


def test_the_flag_is_refused_where_the_setup_says_so(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    made = []

    class Window:
        def __init__(self, root, config, pyconfig, developer):
            made.append(developer)

        def show(self):
            pass

    monkeypatch.setattr(app_window, "AppWindow", Window)
    monkeypatch.setattr(QApplication.instance(), "exec", lambda: 0, raising=False)
    monkeypatch.setattr(QApplication, "exec", lambda *a: 0)
    paths.python_config_file(tmp_path).write_text("[setup]\ndeveloper = false\n", encoding="utf-8")
    assert app_window.run(tmp_path, Config(), True) == 0 and made == [False]
    paths.python_config_file(tmp_path).write_text("", encoding="utf-8")
    assert app_window.run(tmp_path, Config(), True) == 0 and made == [False, True]


@pytest.fixture
def developer(make, tmp_path):
    w = make(developer=True)
    return w


def test_developer_mode_adds_its_pages_to_the_same_window(developer):
    from volis.gui import developer as pages

    assert developer.windowTitle() == "Volis (developer)" and developer.pages.count() == 7
    for page, words, _draw in pages.RAIL:
        developer.rail_buttons[page].click()
        assert developer.pages.currentIndex() == page and developer.rail_buttons[page].text() == words


def test_every_old_setting_has_a_home(developer):
    """The old window's options, each found where a developer can change it."""
    dev = developer.dev
    for widget in (dev.recognizer, dev.translator, dev.source_lang, dev.sides["left"]["recognizer"], dev.sides["right"]["voice"],
                   dev.rescan_button, dev.streaming, dev.hold_fragments, dev.style_hold, dev.use_context, dev.revise,
                   dev.hold_speech, dev.diacritize, dev.glossary, dev.read_realtime, dev.read_original, dev.read_speak,
                   dev.export_button, developer.input_device, developer.output_device, developer.test_microphone,
                   developer.test_speakers, developer.headset, developer.sound, developer.pause, developer.smaller,
                   developer.first_language, developer.second_language, developer.swap_button, developer.way_buttons[talk.HANDS_FREE],
                   developer.peer_input, developer.type_text, developer.saved_open):
        assert widget is not None


def test_developer_settings_reach_the_settings_files(developer):
    dev = developer.dev
    dev.revise.setChecked(True)
    dev.streaming.setChecked(True)
    dev.diacritize.setChecked(True)
    dev.style_hold.setChecked(True)
    py, _ = PythonConfig.load(paths.python_config_file(developer.root))
    assert (py.context.mode, py.asr.streaming, py.tts.diacritize) == ("revision", True, True)
    assert developer.config.mode.turn_style == "hold"
    dev.use_context.setChecked(False)
    assert PythonConfig.load(paths.python_config_file(developer.root))[0].context.mode == "off"


def test_a_greyed_out_option_says_why(developer):
    dev = developer.dev
    dev.use_context.setChecked(False)
    assert not dev.revise.isEnabled() and "context" in dev.reasons["revise"].text() and not dev.reasons["revise"].isHidden()
    dev.use_context.setChecked(True)
    assert dev.revise.isEnabled() and dev.reasons["revise"].isHidden()


def test_a_customer_is_always_press_and_press_again_but_a_developer_can_hold(window, developer):
    window.config.mode.turn_style = "hold"
    window.way_buttons[talk.TOGETHER].click()
    window.start_button.click()
    assert window.config.mode.turn_style == "toggle"
    developer.config.mode.turn_style = "hold"
    developer.way_buttons[talk.TOGETHER].click()
    developer.start_button.click()
    assert developer.config.mode.turn_style == "hold"


def holding_a_turn(w):
    w.way_buttons[talk.TWO_COMPUTERS].click()
    w.config.mode.turn_style = "hold"
    w.start_button.click()
    w.config.mode.turn_style = "hold"
    for event in (ev.Listening(), ev.Mode("turn"), ev.PeerMsg("connected", name="Desk")):
        w.events.put(event)
    w.tick()
    w.isActiveWindow = lambda: True  # offscreen windows are never "active"
    return w.pipeline


def test_holding_the_key_is_a_turn(developer):
    pipeline = holding_a_turn(developer)
    developer.turn_key_event(ses.KeyEdges(pressed=True))
    assert pipeline.asked == [("begin",)]
    developer.session.apply(ev.TurnStarted())
    developer.turn_key_event(ses.KeyEdges(released=True))
    assert pipeline.asked == [("begin",), ("end",)]


def test_the_turn_key_never_reaches_a_focused_widget(window):
    """SPEC §8: Space must not also press whatever button has focus."""
    from PySide6.QtTest import QTest

    clicks = []
    button = window.swap_button
    button.clicked.disconnect()
    button.clicked.connect(lambda: clicks.append(1))
    window.activateWindow()
    QApplication.processEvents()
    button.setFocus()
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert clicks == [1], "outside a turn the key belongs to the widgets"
    window.way_buttons[talk.TWO_COMPUTERS].click()
    window.start_button.click()
    for event in (ev.Listening(), ev.Mode("turn"), ev.PeerMsg("connected", name="Desk")):
        window.events.put(event)
    window.tick()
    window.isActiveWindow = lambda: True
    QTest.keyClick(button, Qt.Key.Key_Space)
    assert clicks == [1], "Space pressed the focused button"
    assert window.pipeline.asked == [("begin",)]
    QTest.keyClick(button, Qt.Key.Key_Return)
    assert window.pipeline.asked == [("begin",)], "other keys are left for the widgets"


def test_a_developer_can_read_a_recording_at_playing_speed_and_pause(make, tmp_path, monkeypatch):
    w = make(developer=True)
    w.dev.read_realtime.setChecked(True)
    w.dev.read_speak.setChecked(True)
    pipeline = reading(w, tmp_path, monkeypatch)
    assert pipeline.source.realtime and not pipeline.muted and pipeline.options.streaming is None
    assert not w.pause_reading.isHidden()
    w.pause_reading.click()
    assert w.reading_paused and w.pause_reading.text() == "Resume"
    w.end_button.click()
    assert not w.reading_paused, "stopping resumes the source, so that it can end"
    pipeline.source.stop()


def test_a_customers_recording_has_no_pause(window, tmp_path, monkeypatch):
    reading(window, tmp_path, monkeypatch)
    assert window.pause_reading.isHidden()


def test_a_run_can_be_exported_and_the_glossary_reaches_it(make, tmp_path, monkeypatch):
    w = make(developer=True)
    w.dev.glossary.setText("Sara, Tehran")
    pipeline = together(w)
    assert pipeline.options.glossary == ["Sara", "Tehran"]
    for event in (ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0), ev.Translated("1.1", "Hello", "en", 300, "cuda", "m")):
        w.events.put(event)
    w.tick()
    assert w.dev.export_button.isEnabled()
    vad = paths.vad_model_file(tmp_path)  # the export's record names the speech detector's file
    vad.parent.mkdir(parents=True, exist_ok=True)
    vad.write_bytes(b"stand-in")
    w.dev.export_to(tmp_path / "out")
    assert "Hello" in (tmp_path / "out" / "conversation.txt").read_text(encoding="utf-8")
    assert "Exported to" in w.dev.run_lines.text()


def test_settings_offers_a_choice_only_if_the_setup_includes_it(make):
    plain = make()
    assert plain.speed_box.isHidden() and plain.voice_box.isHidden()
    py = PythonConfig()
    py.setup.faster, py.setup.accurate = ["hears-all", "small.gguf"], ["hears-all", "big.gguf"]
    py.setup.voices, py.setup.languages = ["amir", "gyro"], ["fa", "en"]
    w = make(pyconfig=py)
    assert not w.speed_box.isHidden()
    w.voices = [_engine("amir", ["fa"]), _engine("gyro", ["fa"]), _engine("lessac", ["en"])]
    w._fill_voices()
    assert not w.voice_box.isHidden() and list(w.voice_combos) == ["fa"]
    w.voice_combos["fa"].setCurrentIndex(w.voice_combos["fa"].findData("gyro"))
    w.speed_buttons[talk.FASTER].click()
    assert PythonConfig.load(paths.python_config_file(w.root))[0].window.voices == ["gyro"]
    assert PythonConfig.load(paths.python_config_file(w.root))[0].window.speed == "faster"
    pipeline = together(w)
    assert pipeline.options.mt == "small.gguf" and pipeline.options.asr == "hears-all"
    assert pipeline.options.voices == ("gyro",)
    assert w.config.shared.right_voice == "gyro", "the person speaking English is heard in the Persian voice"


def test_a_bubble_says_what_was_heard_and_what_a_revision_replaced(window):
    together(window)
    for event in (ev.SentenceMsg("1.1", 1, "می‌خواهم", "fa", 1.0, 2.0, original="می خواهم"),
                  ev.Translated("1.1", "I want", "en", 300, "cuda", "m"),
                  ev.Revised("1.1", "I want", "I would like")):
        window.events.put(event)
    window.tick()
    row = window.chat.rows["1.1"]
    assert row.original.toolTip() == "As heard, before clean-up: می خواهم"
    assert row.translation.toolTip() == "Earlier: I want" and row.note.text() == bubbles.REVISED


def test_settings_from_the_old_window_still_load(tmp_path):
    path = paths.python_config_file(tmp_path)
    path.write_text("[window]\nadvanced_open = true\ntext_size = 14\n", encoding="utf-8")
    assert PythonConfig.load(path)[0].window.text_size == 14


# ---------------------------------------------------------------- nearby computers, accepting, swapping


def two_computers(w, peer_state=None):
    w.way_buttons[talk.TWO_COMPUTERS].click()
    w.start_button.click()
    for event in (ev.Listening(), ev.Mode("turn"), peer_state or ev.PeerMsg("waiting", port=47800)):
        w.events.put(event)
    w.tick()
    return w.pipeline


def test_nearby_computers_are_buttons_and_typing_stays(window):
    pipeline = two_computers(window)
    assert pipeline.options.ask_first
    assert window.found_list.count() == 0 and not window.peer_input.isHidden()
    window.events.put(ev.Discovered([("Front desk", "192.168.1.9", 47800)]))
    window.tick()
    button = window.found_list.itemAt(0).widget()
    assert "Front desk" in button.text() and not window.peer_input.isHidden()
    button.click()
    assert pipeline.asked == [("connect", "192.168.1.9")]


def test_someone_asking_gets_an_answer_from_the_person_here(window):
    pipeline = two_computers(window)
    window.events.put(ev.PeerMsg("asking", name="Front desk", addr="192.168.1.9:47800", speaks="fa", sends="en"))
    window.tick()
    assert not window.asking_box.isHidden() and "Front desk wants to connect" in window.asking_words.text()
    assert "Persian" in window.asking_words.text() and not window.speak_one.isEnabled()
    window.asking_yes.click()
    window.asking_no.click()
    assert pipeline.asked == [("accept",), ("decline",)]


def test_waiting_for_an_answer_can_be_cancelled_and_a_connection_ended(window):
    pipeline = two_computers(window, ev.PeerMsg("connecting", addr="192.168.1.9:47800"))
    assert "accept" in window.link_words.text() and window.link_button.text() == "Cancel"
    window.link_button.click()
    window.events.put(ev.PeerMsg("connected", name="Desk"))
    window.tick()
    assert window.link_button.text() == "Disconnect"
    assert pipeline.asked == [("disconnect",)]


def connected_with_a_sentence(w):
    pipeline = two_computers(w, ev.PeerMsg("connected", name="Desk"))
    for event in (ev.SentenceMsg("1.1", 1, "سلام", "fa", 1.0, 2.0), ev.Translated("1.1", "Hello", "en", 300, "cuda", "m"),
                  ev.Remote("Desk", "fa", "خوبم", "en", "I am fine")):
        w.events.put(event)
    w.tick()
    w.clips.put_heard(1, 1.0, np.ones(16000, np.float32) / 2)
    w.clips.put_spoken(clips.remote_key("fa", "خوبم"), np.ones(2205, np.float32) / 2, 22050)
    return pipeline


def test_ending_swaps_first_and_stops_only_when_that_is_done(window):
    pipeline = connected_with_a_sentence(window)
    window.end_button.click()
    assert pipeline.asked[-1] == ("finish", [("original", "Hello"), ("translation", "خوبم")])
    assert ("stop",) not in pipeline.asked and window.swapping and "Sharing" in window.link_words.text()
    window.end_button.click()
    assert sum(a[0] == "finish" for a in pipeline.asked) == 1
    window.clips.put_received(clips.TRANSLATION, "Hello", np.ones(10, np.int16).tobytes(), 22050)
    window.clips.put_received(clips.ORIGINAL, "خوبم", np.ones(10, np.int16).tobytes(), 16000)
    window.events.put(ev.SwapDone(True))
    window.tick()
    assert ("stop",) in pipeline.asked
    window.tick()
    window.save_button.click()
    first, second = only_saved(window).sentences()
    assert first["audio_original"] and first["audio_translation"] and second["audio_original"] and second["audio_translation"]


def test_when_the_other_person_ends_it_ends_here_too(window):
    pipeline = connected_with_a_sentence(window)
    window.events.put(ev.PeerEnding())
    window.tick()
    assert pipeline.asked[-1][0] == "finish" and window.swap_note.text() == talk.THEY_ENDED


def test_a_failed_swap_says_how_to_finish_it_later(window):
    pipeline = connected_with_a_sentence(window)
    window.end_button.click()
    window.events.put(ev.SwapDone(False, "gone"))
    window.tick()
    assert ("stop",) in pipeline.asked and window.swap_note.text() == talk.SWAP_FAILED and not window.swap_note.isHidden()


def test_with_never_save_nothing_of_it_is_sent(make):
    py = PythonConfig()
    py.saving.mode = "never"
    w = make(pyconfig=py)
    pipeline = connected_with_a_sentence(w)
    w.end_button.click()
    assert pipeline.asked[-1] == ("finish", [])


def test_a_dropped_connection_ends_at_once_and_says_how_to_finish_it_later(window):
    pipeline = connected_with_a_sentence(window)
    window.events.put(ev.PeerMsg("disconnected", reason="gone"))
    window.tick()
    window.end_button.click()
    assert ("stop",) in pipeline.asked and window.swap_note.text() == talk.SWAP_FAILED


def test_nobody_can_start_a_turn_or_type_during_the_swap(window):
    pipeline = connected_with_a_sentence(window)
    window.end_button.click()
    assert "Please wait" in window.speak_one.text() and not window.speak_one.isEnabled()
    assert not window.turn_key_active() and window.type_toggle.isHidden()
    assert ("begin",) not in pipeline.asked
