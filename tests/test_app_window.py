"""The new window. Qt offscreen; no model is loaded, and the pipeline is a
stand-in that records what it was asked."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from volis import audio, cli, models  # noqa: E402
from volis import events as ev  # noqa: E402
from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui import app_window, bubbles, sample, talk, theme  # noqa: E402
from volis.gui import session as ses  # noqa: E402


class FakePipeline:
    made: list = []

    def __init__(self, root, config, options, events, source=None, pyconfig=None):
        self.config, self.options, self.events = config, options, events
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

    def translate_typed(self, lines, direction=None):
        self.asked.append(("typed", tuple(lines), direction.side if direction else ""))


def _engine(name, languages):
    class E:
        dir_name, named, unusable = name, True, ""
        languages_known = True

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
        type("R", (), {"engine": e, "fit": 0}) for e in engines if tag.split("-")[0] in e.languages])
    FakePipeline.made = []
    windows = []

    def build(config=None, pyconfig=None, found=True):
        config = config or Config()
        config.asr.engine = ""
        w = app_window.AppWindow(tmp_path, config, pyconfig or PythonConfig())
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


def test_the_flag_opens_it():
    assert cli.parse(["--new-window"]) == cli.Command("new-window")
    with pytest.raises(cli.UsageError):
        cli.parse(["--new-window", "extra"])


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
    assert not window.new_button.isHidden() and window.speak_left.isHidden()
    window.new_button.click()
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
