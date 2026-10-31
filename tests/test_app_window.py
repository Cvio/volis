"""The new window (U1). Qt offscreen; no model is loaded."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from volis import cli  # noqa: E402
from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui import app_window, bubbles, theme  # noqa: E402


@pytest.fixture
def window(tmp_path):
    QApplication.instance() or QApplication([])
    w = app_window.AppWindow(tmp_path, Config(), PythonConfig())
    w.resize(1000, 700)
    w.show()
    QApplication.processEvents()
    yield w
    w.close()


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


def test_the_sample_is_drawn_as_bubbles_on_each_side(window):
    rows = window.chat.rows
    assert list(rows) == [i.key for i in bubbles.items(window.session)]
    assert rows["1.1"].side == bubbles.LEFT
    assert rows["2.1"].side == bubbles.RIGHT
    assert rows["4.1"].bubble.property("speaking") is False


def test_each_line_reads_in_its_own_direction(window):
    row = window.chat.rows["1.1"]
    assert row.original.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert row.translation.layoutDirection() == Qt.LayoutDirection.LeftToRight


def test_lines_sit_on_the_edge_their_script_starts_from(window):
    row = window.chat.rows["1.1"]
    QApplication.processEvents()
    inner = row.bubble.contentsRect()
    margin = row.bubble.layout().contentsMargins()
    assert row.original.geometry().right() == inner.right() - margin.right()
    assert row.translation.geometry().left() == inner.left() + margin.left()


def test_each_speakers_label_is_on_their_own_side(window):
    QApplication.processEvents()
    left, right = window.chat.rows["1.1"], window.chat.rows["2.1"]
    assert left.speaker.geometry().left() == left.bubble.geometry().left()
    assert right.speaker.geometry().right() == right.bubble.geometry().right()


def test_a_sentence_on_one_line_gets_one_lines_height(window):
    row = window.chat.rows["1.1"]
    assert row.original.height() < row.original.fontMetrics().lineSpacing() * 1.5


def test_a_short_sentence_stays_on_one_line_and_a_long_one_wraps(window):
    rows = window.chat.rows
    short, long = rows["4.1"].translation, rows["3.1"].translation
    assert short.height() < short.fontMetrics().lineSpacing() * 1.5
    assert long.height() > long.fontMetrics().lineSpacing() * 1.5
    assert long.width() <= window.chat.bubble_width()


def test_markup_in_what_someone_said_is_only_words(window):
    assert window.chat.rows["1.1"].translation.textFormat() == Qt.TextFormat.PlainText


def test_text_size_changes_the_bubbles_stops_at_the_ends_and_is_saved(window, tmp_path):
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


def test_opening_uses_the_remembered_theme(tmp_path):
    QApplication.instance() or QApplication([])
    config = PythonConfig()
    config.window.theme = "midnight"
    w = app_window.AppWindow(tmp_path, Config(), config)
    assert theme.MIDNIGHT.background in w.styleSheet()
    assert w.theme_buttons["midnight"].isChecked()
    w.close()


def test_a_save_that_fails_names_the_file(window, tmp_path):
    (tmp_path / "volis-python.toml").mkdir()
    window.choose_theme("midnight")
    assert str(tmp_path) in window.settings_problem.text()


def test_controls_that_do_not_work_yet_say_so(window):
    for button in (window.sound, window.microphone, window.more):
        assert not button.isEnabled() and button.toolTip() == app_window.NOT_YET


def test_redrawing_nothing_new_leaves_the_rows_alone(window):
    before = dict(window.chat.rows)
    window.draw_conversation()
    assert all(window.chat.rows[k] is before[k] for k in before)


def test_lines_removed_from_the_session_are_removed_from_the_screen(window):
    window.session.clear()
    window.draw_conversation()
    assert window.chat.rows == {}
