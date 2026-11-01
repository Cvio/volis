"""The test bench: a page in developer mode (Ctrl+Shift+T).

For whoever is choosing models or checking a change. Nothing in it is needed
to hold a conversation, which is why it is not in Models. Each tab has numbered
steps on the left, with the one to do next lit, and the answer on the right.
Three tabs, each answering one question:

* Recognizers: which one hears this best? A recording or an audio file
  through each ticked recognizer, scored against the correct text if given.
* Translators: which one translates this best? Typed or pasted text, or
  what a recognizer hears in a recording or a file, through each ticked
  translator, scored against a reference if given.
* Whole set: does this combination work on this computer? Whether a
  recognizer, translator and voice fit in memory together (worked out, with
  nothing loaded), and a button that measures them on a recording.

One rule covers all three: the bench needs the memory a conversation uses, so
it works only while none is running. The line at the top says so and offers
to stop it; while the bench is working the same line says what it is doing.

What can start, and why not, is decided in `bench.ready`; which step is next in
`bench.step_states`; the results as cards in `bench.cards`; the work itself is
`bench.Worker`. This file only lays the controls out and paints.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QStackedWidget, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from .. import bench, models, perf, typed
from .. import events as ev
from ..audio import SAMPLE_RATE
from . import view
from .chat import scrolled
from .session import has_rtl

log = logging.getLogger(__name__)

AUDIO_FILES = "Audio (*.wav *.mp3 *.m4a *.flac *.ogg *.mp4);;All files (*)"
COLORS = {"ok": "", "amber": "#d08c00", "red": "#d03030", "fits": "#2e8b57", "tight": "#d08c00", "no": "#d03030"}
SETUP_WIDTH = 420
MOST_ROWS = 6  # a longer list of models scrolls


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


class WholeRowTicks(QStyledItemDelegate):
    """Clicking anywhere on a model's row ticks it, not only in the small box.
    Every row is one height, so the list can be made exactly as tall as its rows."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt's name
        return QSize(super().sizeHint(option, index).width(), option.fontMetrics.height() + 14)

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802 - Qt's name
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton and option.rect.contains(event.position().toPoint()):
                ticked = Qt.CheckState(index.data(Qt.ItemDataRole.CheckStateRole)) == Qt.CheckState.Checked
                wanted = Qt.CheckState.Unchecked if ticked else Qt.CheckState.Checked
                model.setData(index, wanted.value, Qt.ItemDataRole.CheckStateRole)
            return True
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            return True
        return super().editorEvent(event, model, option, index)


def _checklist() -> QListWidget:
    box = QListWidget()
    box.setSelectionMode(QListWidget.SelectionMode.NoSelection)
    box.setItemDelegate(WholeRowTicks(box))
    return box


def _fit_rows(box: QListWidget) -> None:
    """As tall as its models, so that a short list leaves no empty space."""
    rows = sum(box.sizeHintForRow(i) for i in range(min(box.count(), MOST_ROWS)))
    box.setFixedHeight(rows + 2 * box.frameWidth() + 2)


def _text(name: str = "muted") -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)  # what a model wrote is never markup
    return label


def _said(label: QLabel, text: str) -> None:
    """Words in either direction, laid out from their own side."""
    label.setText(text)
    label.setLayoutDirection(Qt.LayoutDirection.RightToLeft if has_rtl(text) else Qt.LayoutDirection.LeftToRight)
    label.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)


def _narrow(combo: QComboBox) -> QComboBox:
    """A long model name mustn't widen the column it sits in."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    return combo


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class Step(QFrame):
    """One numbered step. The step to do next is lit; none is ever locked."""

    def __init__(self, number: int, title: str, hint: str = "") -> None:
        super().__init__()
        self.setObjectName("step")
        self.number_text = str(number)
        self.state = ""
        self.number = QLabel(self.number_text)
        self.number.setObjectName("stepNumber")
        self.number.setFixedSize(24, 24)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel(title)
        self.title.setObjectName("stepTitle")
        self.title.setWordWrap(True)
        top = QHBoxLayout()
        top.addWidget(self.number)
        top.addWidget(self.title, 1)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(12, 10, 12, 12)
        self.body.setSpacing(8)
        self.body.addLayout(top)
        if hint:
            words = _text()
            words.setText(hint)
            self.body.addWidget(words)
        self.set_state(bench.LATER)

    def set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        self.setProperty("state", state)
        self.number.setText("\u2713" if state == bench.DONE else self.number_text)
        for widget in (self, self.number, self.title):
            _repolish(widget)


class CardView(QFrame):
    """One model's result: what it wrote, how near and how fast, and the way to use it."""

    def __init__(self, card: bench.Card, show_given: bool, use) -> None:
        super().__init__()
        self.setObjectName("card")
        self.setProperty("best", card.best)
        self.card = card
        column = QVBoxLayout(self)
        column.setContentsMargins(16, 12, 16, 12)
        column.setSpacing(8)
        top = QHBoxLayout()
        self.name = _text("heading")
        self.name.setText(card.name)
        top.addWidget(self.name, 1)
        if card.best:
            badge = QLabel("Closest to your text")
            badge.setObjectName("badge")
            top.addWidget(badge)
        column.addLayout(top)
        self.score = _text("status")
        self.score.setText(card.score)
        self.score.setVisible(bool(card.score))
        column.addWidget(self.score)
        self.wrote: list[QLabel] = []
        for given, wrote in card.lines:
            if show_given and given:
                line = _text()
                _said(line, given)
                column.addWidget(line)
            line = _text("problem" if card.failed else "written")
            font = line.font()
            font.setPointSizeF(font.pointSizeF() + 2)
            line.setFont(font)
            line.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            _said(line, wrote)
            column.addWidget(line)
            self.wrote.append(line)
        bottom = QHBoxLayout()
        self.facts = _text()
        self.facts.setText("  \u00b7  ".join(card.facts))
        bottom.addWidget(self.facts, 1)
        self.use = QPushButton("Use in the conversation")
        self.use.setVisible(not card.failed)
        self.use.clicked.connect(lambda _checked=False: use(card.ident))
        bottom.addWidget(self.use)
        column.addLayout(bottom)


def _ticked(box: QListWidget) -> list[str]:
    return [box.item(i).data(Qt.ItemDataRole.UserRole) for i in range(box.count())
            if box.item(i).checkState() == Qt.CheckState.Checked]


def _refill(box: QListWidget, items: list[tuple[str, str, str]]) -> None:
    """`(label, id, tooltip)` for each model; what was ticked stays ticked."""
    ticked = set(_ticked(box))
    box.blockSignals(True)
    box.clear()
    for label, ident, tip in items:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, ident)
        item.setToolTip(tip)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if ident in ticked else Qt.CheckState.Unchecked)
        box.addItem(item)
    box.blockSignals(False)


def _copy_items(combo: QComboBox, other: QComboBox) -> None:
    """The same choices as one of Models's lists, and its choice."""
    combo.blockSignals(True)
    combo.clear()
    for i in range(other.count()):
        combo.addItem(other.itemText(i), other.itemData(i))
    combo.setCurrentIndex(max(other.currentIndex(), 0) if combo.count() else -1)
    combo.blockSignals(False)


def _choices(combo: QComboBox, items: list[str], selected) -> None:
    keep = selected if selected in items else combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(items)
    if keep in items:
        combo.setCurrentIndex(items.index(keep))
    combo.blockSignals(False)


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _fill(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = table.item(r, c)
            if item is None:
                table.setItem(r, c, QTableWidgetItem(str(value)))
            elif item.text() != str(value):
                item.setText(str(value))


class ClipInput(QWidget):
    """Sound to test with: recorded from the microphone, or an audio file."""

    changed = Signal()

    def __init__(self, bench_window) -> None:
        super().__init__()
        self.bench = bench_window
        self.audio: np.ndarray | None = None
        self.described = ""
        self.path: Path | None = None
        self.recorder: bench.Recorder | None = None
        self.record_button = QPushButton("Record")
        self.record_button.setToolTip("Record from the microphone chosen in Models. Press again to stop.")
        self.record_button.clicked.connect(self.toggle_record)
        self.file_button = QPushButton("Choose a file...")
        self.file_button.clicked.connect(self.choose_file)
        self.play_button = QPushButton("Play")
        self.play_button.setToolTip("Play the sound through the speakers chosen in Models.")
        self.play_button.clicked.connect(self.play)
        self.label = _text()
        self.label.setText("No sound yet.")
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        for widget in (self.record_button, self.file_button, self.play_button):
            row.addWidget(widget)
        column.addLayout(row)
        column.addWidget(self.label)
        self._draw()

    # ---- state

    def recording(self) -> bool:
        return self.recorder is not None

    def has_sound(self) -> bool:
        return self.audio is not None and len(self.audio) > 0

    def set_audio(self, audio: np.ndarray, described: str, path: Path | None = None) -> None:
        self.audio, self.described, self.path = audio, described, path
        self.label.setText(f"{described}, {bench.seconds_text(len(audio) / SAMPLE_RATE)}" if len(audio)
                           else "Nothing was recorded.")
        self._draw()
        self.changed.emit()

    def _draw(self) -> None:
        self.record_button.setText("Stop recording" if self.recording() else "Record")
        self.file_button.setEnabled(not self.recording())
        self.play_button.setEnabled(self.has_sound() and not self.recording())

    # ---- what the buttons do

    def toggle_record(self) -> None:
        if self.recording():
            recorder, self.recorder = self.recorder, None
            self.set_audio(recorder.stop(), "a recording")
            return
        if self.bench.window_.running():
            self.label.setText("Stop the conversation first: it is using the microphone.")
            return
        recorder = bench.Recorder(self.bench.spawn_capture)
        try:
            recorder.start(self.bench.window_.input_device.currentData() or "")
        except Exception as e:  # the reason is what the user needs
            self.label.setText(f"The microphone could not be opened: {e}")
            return
        self.recorder = recorder
        self.label.setText("Recording...")
        self._draw()
        self.changed.emit()

    def tick(self) -> None:
        if self.recorder is None:
            return
        level = self.recorder.poll()
        heard = "" if level > -50 else "  (very quiet: is the microphone on?)"
        self.label.setText(f"Recording... {self.recorder.seconds():.0f} s{heard}  Press Stop recording when done.")
        if self.recorder.seconds() >= bench.MAX_RECORD_S:
            self.toggle_record()

    def choose_file(self) -> None:
        start = str(self.bench.root / "tests" / "fixtures")
        path, _ = QFileDialog.getOpenFileName(self, "An audio file to test with", start, AUDIO_FILES)
        if path:
            self.load_file(Path(path))

    def load_file(self, path: Path) -> None:
        from ..filesource import read_16k_mono

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            audio = read_16k_mono(path)
        except Exception as e:
            self.label.setText(f"That file could not be read: {e}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.set_audio(audio, path.name, path)

    def play(self) -> None:
        if not self.has_sound():
            return
        from . import devicetest

        audio, device = self.audio, self.bench.window_.output_device.currentData() or ""
        threading.Thread(target=lambda: devicetest._play(audio, SAMPLE_RATE, device), name="volis-bench-play",
                         daemon=True).start()


class TestBench(QWidget):
    __test__ = False  # not a pytest class, whatever its name starts with

    def __init__(self, window, worker: bench.Worker | None = None) -> None:
        super().__init__()
        self.window_ = window
        self.root = window.root
        self.perf = window.perf_panel  # what has been measured on this machine lives there
        self.history = bench.History.load(self.root)
        self.worker = worker or bench.Worker(self.root, window.config, window.pyconfig)
        self.sampler = perf.Sampler()
        self.spawn_capture = None  # tests put a stand-in here; None is the real microphone
        self.bench_events: queue.Queue | None = None  # a "measure this set" run in progress
        self.bench_pipeline = None
        self.bench_note = ""
        self.bench_file = ""
        self.shown: dict[str, bench.Record | None] = {bench.RECOGNIZERS: None, bench.TRANSLATORS: None}
        self._ticks = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        banner = QHBoxLayout()
        self.banner = QLabel(bench.STOP_FIRST)
        self.banner.setObjectName("problem")
        self.stop_button = QPushButton("Stop the conversation")
        self.stop_button.clicked.connect(window.stop)
        banner.addWidget(self.banner, 1)
        banner.addWidget(self.stop_button)
        layout.addLayout(banner)
        working = QHBoxLayout()
        self.busy_bar = QProgressBar()  # moves while anything in the bench is under way
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedSize(160, 10)
        self.busy_label = QLabel()
        self.busy_label.setObjectName("heading")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Stop after the model that is running now. Nothing more is loaded.")
        self.cancel_button.clicked.connect(self.cancel)
        working.addWidget(self.busy_bar)
        working.addWidget(self.busy_label, 1)
        working.addWidget(self.cancel_button)
        layout.addLayout(working)
        self.said = _text("status")  # what the last press did, when it isn't in the results
        self.tabs = QTabWidget()
        self.tabs.addTab(self._recognizers_tab(), "Recognizers")
        self.tabs.addTab(self._translators_tab(), "Translators")
        self.tabs.addTab(self._whole_tab(), "Whole set")
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.said)

        self.refill()
        for kind in (bench.RECOGNIZERS, bench.TRANSLATORS):
            self._list_earlier(kind)
            self._show_earlier(kind, 0)  # the last comparison made, if any
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(150)
        self.tick()

    # -------------------------------------------------------------- tabs

    def _split(self, setup: QWidget, answer: QWidget) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        row = QHBoxLayout(page)
        row.setSpacing(16)
        setup.setFixedWidth(SETUP_WIDTH)
        row.addWidget(setup)
        row.addWidget(answer, 1)
        return page

    def _setup(self, question: str, steps: list[Step], earlier: QWidget | None = None) -> QWidget:
        """The left of a tab: its question, its steps, and what was done before.
        The last step, the button, stays in sight however long the others are."""
        panel = QWidget()
        panel.setObjectName("page")
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        heading = _text("heading")
        heading.setText(question)
        column.addWidget(heading)
        inner = QWidget()
        stack = QVBoxLayout(inner)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(8)
        for step in steps[:-1]:
            stack.addWidget(step)
        stack.addStretch(1)
        column.addWidget(scrolled(inner), 1)
        column.addWidget(steps[-1])
        if earlier is not None:
            column.addWidget(earlier)
        return panel

    def _action(self, number: int, title: str, words: str, run) -> tuple[Step, QPushButton, QLabel]:
        """The last step: the button, and beside it why it can't be pressed yet."""
        step = Step(number, title)
        button = QPushButton(words)
        button.setObjectName("primary")
        button.clicked.connect(lambda _checked=False: run())
        reason = _text()
        step.body.addWidget(button)
        step.body.addWidget(reason)
        return step, button, reason

    def _earlier(self, kind: str) -> tuple[QWidget, dict]:
        """Every comparison of this kind: to look at again, to find, to delete."""
        panel = QWidget()
        panel.setObjectName("page")
        panel.setFixedHeight(190)
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 4, 0, 0)
        column.setSpacing(6)
        top = QHBoxLayout()
        heading = _text("heading")
        heading.setText("Earlier comparisons")
        delete = QPushButton("Delete")
        delete.setToolTip("Delete the comparison on the right.")
        delete.clicked.connect(lambda _checked=False, k=kind: self._ask_delete(k))
        top.addWidget(heading, 1)
        top.addWidget(delete)
        column.addLayout(top)
        search = QLineEdit()
        search.setPlaceholderText("Search")
        search.textChanged.connect(lambda _text_now, k=kind: self._search(k))
        column.addWidget(search)
        listed = QListWidget()
        listed.setWordWrap(True)
        listed.setTextElideMode(Qt.TextElideMode.ElideNone)
        listed.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        listed.currentRowChanged.connect(lambda row, k=kind: self._show_earlier(k, row))
        column.addWidget(listed, 1)
        none = _text()
        none.setText("Nothing compared yet.")
        none.setAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignTop)
        column.addWidget(none, 1)
        confirm = QWidget()
        confirm_row = QHBoxLayout(confirm)
        confirm_row.setContentsMargins(0, 0, 0, 0)
        ask = _text("problem")
        ask.setText("Delete this for good?")
        yes, no = QPushButton("Delete it"), QPushButton("Keep it")
        yes.clicked.connect(lambda _checked=False, k=kind: self.delete_shown(k))
        no.clicked.connect(lambda _checked=False: confirm.hide())
        confirm_row.addWidget(ask, 1)
        confirm_row.addWidget(yes)
        confirm_row.addWidget(no)
        confirm.hide()
        column.addWidget(confirm)
        return panel, {"earlier": listed, "search": search, "delete": delete, "none": none, "confirm": confirm,
                       "delete_yes": yes, "delete_no": no}

    def _results(self, kind: str) -> tuple[QWidget, dict]:
        """The right of a tab: what the next step is until there is an answer,
        then a card for each model."""
        panel = QWidget()
        panel.setObjectName("page")
        column = QVBoxLayout(panel)
        column.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        title = _text("heading")
        copy = QPushButton("Copy as a table")
        copy.setToolTip("Copy this comparison as a Markdown table, to paste into notes.")
        copy.clicked.connect(lambda _checked=False, k=kind: self.copy_table(k))
        top.addWidget(title, 1)
        top.addWidget(copy)
        column.addLayout(top)
        tested = _text()
        column.addWidget(tested)
        stack = QStackedWidget()
        empty = _text()
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stack.addWidget(empty)
        inner = QWidget()
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 12, 0)
        body.setSpacing(10)
        body.addStretch(1)
        stack.addWidget(scrolled(inner))
        column.addWidget(stack, 1)
        hint = _text()
        hint.setText("Read what each one wrote, then press Use in the conversation on the one you prefer.")
        column.addWidget(hint)
        note = _text()
        font = note.font()
        font.setPointSizeF(font.pointSizeF() - 1)
        note.setFont(font)
        column.addWidget(note)
        return panel, {"title": title, "copy": copy, "tested": tested, "stack": stack, "empty": empty, "body": body,
                       "hint": hint, "note": note, "cards": []}

    def _recognizers_tab(self) -> QWidget:
        self.r_language = _narrow(QComboBox())
        self.r_language.currentIndexChanged.connect(lambda _i: self._fill_recognizers())
        self.r_sound = ClipInput(self)
        self.r_sound.changed.connect(self.draw)
        sound = Step(1, "The speech to test", "Choose the language spoken, then record it or choose a file.")
        sound.body.addWidget(self.r_language)
        sound.body.addWidget(self.r_sound)
        self.r_models = _checklist()
        self.r_models.itemChanged.connect(lambda _item: self.draw())
        chosen = Step(2, "The recognizers to compare", "Tick the ones to compare. They run one at a time.")
        chosen.body.addWidget(self.r_models)
        self.r_reference = QPlainTextEdit()
        self.r_reference.setPlaceholderText("What was really said. Each recognizer is then scored against it.")
        self.r_reference.setFixedHeight(52)
        self.r_reference.textChanged.connect(self.draw)
        correct = Step(3, "The correct text (optional)")
        correct.body.addWidget(self.r_reference)
        action, self.r_run, self.r_reason = self._action(4, "Compare", "Compare recognizers", self.run_recognizers)
        self.r_steps = [sound, chosen, correct, action]
        earlier, parts = self._earlier(bench.RECOGNIZERS)
        answer, self.r = self._results(bench.RECOGNIZERS)
        self.r.update(parts)
        return self._split(self._setup("Which recognizer hears this best?", self.r_steps, earlier), answer)

    def _translators_tab(self) -> QWidget:
        self.t_source, self.t_target = _narrow(QComboBox()), _narrow(QComboBox())
        self.t_source.currentIndexChanged.connect(lambda _i: self._fill_recognizer_choice())
        languages = QHBoxLayout()
        languages.addWidget(self.t_source, 1)
        languages.addWidget(QLabel("into"))
        languages.addWidget(self.t_target, 1)
        self.t_from_text = QRadioButton("Text")
        self.t_from_sound = QRadioButton("Speech")
        self.t_from_text.setChecked(True)
        self._t_kind = QButtonGroup(self)
        for button in (self.t_from_text, self.t_from_sound):
            self._t_kind.addButton(button)
            button.toggled.connect(lambda _on: self.draw())
        kind = QHBoxLayout()
        kind.addWidget(self.t_from_text)
        kind.addWidget(self.t_from_sound)
        kind.addStretch(1)
        self.t_text = QPlainTextEdit()
        self.t_text.setPlaceholderText("The text to translate. Each line is translated on its own.")
        self.t_text.setFixedHeight(64)
        self.t_text.textChanged.connect(self.draw)
        self.t_sound = ClipInput(self)
        self.t_sound.changed.connect(self.draw)
        self.t_recognizer = _narrow(QComboBox())
        self.t_recognizer.setToolTip("The sound is turned into text by this recognizer first; every translator is "
                                     "then given the same text.")
        self.t_sound_box = QWidget()
        sound = QVBoxLayout(self.t_sound_box)
        sound.setContentsMargins(0, 0, 0, 0)
        sound.addWidget(self.t_sound)
        heard = QHBoxLayout()
        heard.addWidget(QLabel("Heard by"))
        heard.addWidget(self.t_recognizer, 1)
        sound.addLayout(heard)
        given = Step(1, "What to translate", "Choose the languages, then type some text or give it speech.")
        given.body.addLayout(languages)
        given.body.addLayout(kind)
        given.body.addWidget(self.t_text)
        given.body.addWidget(self.t_sound_box)
        self.t_models = _checklist()
        self.t_models.itemChanged.connect(lambda _item: self.draw())
        chosen = Step(2, "The translators to compare", "Tick the ones to compare. They run one at a time.")
        chosen.body.addWidget(self.t_models)
        self.t_reference = QPlainTextEdit()
        self.t_reference.setPlaceholderText("A translation you trust, one line per line of the text")
        self.t_reference.setFixedHeight(52)
        self.t_reference.textChanged.connect(self.draw)
        trusted = Step(3, "A translation to score against (optional)")
        trusted.body.addWidget(self.t_reference)
        action, self.t_run, self.t_reason = self._action(4, "Compare", "Compare translators", self.run_translators)
        self.t_steps = [given, chosen, trusted, action]
        earlier, parts = self._earlier(bench.TRANSLATORS)
        answer, self.t = self._results(bench.TRANSLATORS)
        self.t.update(parts)
        return self._split(self._setup("Which translator translates this best?", self.t_steps, earlier), answer)

    def _whole_tab(self) -> QWidget:
        self.w_asr, self.w_asr2 = _narrow(QComboBox()), _narrow(QComboBox())
        self.w_mt, self.w_voice = _narrow(QComboBox()), _narrow(QComboBox())
        chosen = Step(1, "The models to run together", "The answer appears on the right at once. Nothing is loaded.")
        self.w_fill = QPushButton("Take the conversation's choice")
        self.w_fill.setToolTip("Set the lists below to what is chosen in Models.")
        self.w_fill.clicked.connect(self.fill_from_window)
        chosen.body.addWidget(self.w_fill)
        for words, combo in (("Recognizer", self.w_asr), ("Second recognizer (two people, one computer)", self.w_asr2),
                             ("Translator", self.w_mt), ("Voice", self.w_voice)):
            label = _text()
            label.setText(words)
            chosen.body.addWidget(label)
            chosen.body.addWidget(combo)
        action, self.w_run, self.w_reason = self._action(2, "Measure them (optional)", "Measure on a recording...",
                                                         self.measure)
        self.w_run.setToolTip("Runs an audio file through this recognizer and translator, without speaking, as fast "
                              "as the models allow, and keeps the speeds and the memory it took.")
        self.w_steps = [chosen, action]
        answer = QWidget()
        answer.setObjectName("page")
        column = QVBoxLayout(answer)
        column.setContentsMargins(0, 0, 0, 0)
        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)
        column.addWidget(self.verdict_label)
        self.estimate_table = _table(["Model", "On", "GPU", "System", "From"])
        self.estimate_table.setMaximumHeight(150)
        column.addWidget(self.estimate_table)
        self.speed_label = _text()
        column.addWidget(self.speed_label)
        self.w_apply = QPushButton("Use this set in the conversation")
        self.w_apply.setToolTip("Choose this recognizer and translator on the Models page.")
        self.w_apply.clicked.connect(self.apply_set)
        column.addWidget(self.w_apply, 0, Qt.AlignmentFlag.AlignLeft)
        runs = _text("heading")
        runs.setText("Every run measured on this computer")
        column.addWidget(runs)
        self.runs_table = _table(["When", "Recognizer", "Translator", "Mode", "ASR RTF", "Translate ms", "First sound ms",
                                  "Peak GPU"])
        column.addWidget(self.runs_table, 1)
        for combo in (self.w_asr, self.w_asr2, self.w_mt, self.w_voice):
            combo.currentIndexChanged.connect(lambda _i: self.refresh_whole())
        return self._split(self._setup("Will these run together on this computer?", self.w_steps), answer)

    # -------------------------------------------------------------- the lists

    def refill(self) -> None:
        """Take the models and languages from Models again (at
        opening, and after a rescan there)."""
        w = self.window_
        _copy_items(self.r_language, w.source_lang)
        _copy_items(self.t_source, w.source_lang)
        _copy_items(self.t_target, w.target_lang)
        self._fill_recognizers()
        self._fill_recognizer_choice()
        _refill(self.t_models, [(view.plain_name(t.named, t.name, t.id), t.id,
                                 view.translator_limits(t.backend) or t.id) for t in w.translators if t.enabled()])
        _fit_rows(self.t_models)
        self.fill_from_window()
        self.draw()

    def _usable(self, tag: str) -> list:
        """The recognizers that can be compared for a language, best fit first."""
        return [r for r in models.rank(tag or "", self.window_.engines) if r.engine.kind == "segment"]

    def _engine_name(self, engine) -> str:
        return view.plain_name(engine.named, engine.name, engine.dir_name)

    def _fill_recognizers(self) -> None:
        tag = self.r_language.currentData() or ""
        _refill(self.r_models, [(self._engine_name(r.engine), r.engine.dir_name, r.fit.label(tag))
                                for r in self._usable(tag)])
        _fit_rows(self.r_models)
        self.draw()

    def _fill_recognizer_choice(self) -> None:
        tag = self.t_source.currentData() or ""
        wanted = self.t_recognizer.currentData() or self.window_.recognizer.currentData()
        self.t_recognizer.blockSignals(True)
        self.t_recognizer.clear()
        for r in self._usable(tag):
            self.t_recognizer.addItem(self._engine_name(r.engine), r.engine.dir_name)
        index = self.t_recognizer.findData(wanted)
        self.t_recognizer.setCurrentIndex(index if index >= 0 else (0 if self.t_recognizer.count() else -1))
        self.t_recognizer.blockSignals(False)
        self.draw()

    # -------------------------------------------------------------- state

    def busy(self) -> bool:
        return self.worker.busy or self.bench_events is not None

    def recording(self) -> bool:
        return self.r_sound.recording() or self.t_sound.recording()

    def _ready(self, kind: str) -> bench.Ready:
        common = dict(running=self.window_.running(), busy=self.busy())
        if kind == bench.RECOGNIZERS:
            return bench.ready(kind, recording=self.r_sound.recording(), ticked=len(_ticked(self.r_models)),
                               has_sound=self.r_sound.has_sound(), **common)
        if kind == bench.TRANSLATORS:
            from_sound = self.t_from_sound.isChecked()
            return bench.ready(kind, recording=from_sound and self.t_sound.recording(),
                               ticked=len(_ticked(self.t_models)), has_sound=self.t_sound.has_sound(),
                               has_text=bool(typed.lines_of(self.t_text.toPlainText())), from_sound=from_sound,
                               has_recognizer=self.t_recognizer.currentData() is not None, **common)
        return bench.ready("whole", recording=self.recording(), **common)

    # -------------------------------------------------------------- starting work

    def _free_the_memory(self) -> None:
        if self.window_.typed_worker is not None:
            self.window_.typed_worker.release()  # a translator kept loaded for typed text

    def run_recognizers(self) -> None:
        if not self._ready(bench.RECOGNIZERS).enabled:
            return
        tag = self.r_language.currentData() or ""
        ticked = set(_ticked(self.r_models))
        engines = [r.engine for r in self._usable(tag) if r.engine.dir_name in ticked]
        self._free_the_memory()
        self.said.setText("")
        self.worker.recognizers(self.r_sound.audio, f"{self.r_language.currentText()}, {self.r_sound.described}", tag,
                                engines, self.r_reference.toPlainText(),
                                {e.dir_name: self._engine_name(e) for e in engines})
        self.draw()

    def run_translators(self) -> None:
        if not self._ready(bench.TRANSLATORS).enabled:
            return
        from ..translate.context import parse_glossary

        w = self.window_
        ticked = set(_ticked(self.t_models))
        entries = [t for t in w.translators if t.id in ticked]
        names = {t.id: view.plain_name(t.named, t.name, t.id) for t in entries}
        source, target = self.t_source.currentData(), self.t_target.currentData()
        pair = f"{self.t_source.currentText()} > {self.t_target.currentText()}"
        audio = recognizer = None
        lines, described = typed.lines_of(self.t_text.toPlainText()), f"{pair}, typed"
        if self.t_from_sound.isChecked():
            recognizer = next(r.engine for r in self._usable(source) if r.engine.dir_name == self.t_recognizer.currentData())
            names[recognizer.dir_name] = self._engine_name(recognizer)
            audio, lines, described = self.t_sound.audio, [], f"{pair}, {self.t_sound.described}"
        self._free_the_memory()
        self.said.setText("")
        self.worker.translators(lines, described, source, target, entries, self.t_reference.toPlainText(),
                                parse_glossary(w.glossary.text()), names, audio, recognizer)
        self.draw()

    def cancel(self) -> None:
        self.worker.cancel()
        if self.bench_pipeline is not None:
            self.bench_pipeline.stop()
        self.busy_label.setText("Stopping after the model that is running now...")

    # -------------------------------------------------------------- results

    def _parts(self, kind: str) -> dict:
        return self.r if kind == bench.RECOGNIZERS else self.t

    def _list_earlier(self, kind: str, row: int = 0) -> None:
        parts = self._parts(kind)
        listed = parts["earlier"]
        records = self.history.of(kind)
        listed.blockSignals(True)
        listed.clear()
        for record in records:
            models_in_it = len(dict.fromkeys(record.ids))
            listed.addItem(f"{record.title}\n{record.when}, {models_in_it} {'model' if models_in_it == 1 else 'models'}")
        listed.setCurrentRow(min(row, len(records) - 1))
        listed.blockSignals(False)
        listed.setVisible(bool(records))
        parts["search"].setVisible(bool(records))
        parts["none"].setVisible(not records)
        self._search(kind)

    def _search(self, kind: str) -> None:
        parts = self._parts(kind)
        words = parts["search"].text().casefold().split()
        for row in range(parts["earlier"].count()):
            item = parts["earlier"].item(row)
            item.setHidden(not all(word in item.text().casefold() for word in words))

    def _show_earlier(self, kind: str, row: int) -> None:
        records = self.history.of(kind)
        self._parts(kind)["confirm"].hide()
        if 0 <= row < len(records):
            self.show_record(records[row])
        else:
            self._show_nothing(kind)

    def _show_nothing(self, kind: str) -> None:
        parts = self._parts(kind)
        self.shown[kind] = None
        self._set_cards(parts, [])
        for name in ("title", "tested", "note"):
            parts[name].setText("")
        parts["stack"].setCurrentIndex(0)
        self.draw()

    def _set_cards(self, parts: dict, cards: list[CardView]) -> None:
        for old in parts["cards"]:
            parts["body"].removeWidget(old)
            old.deleteLater()
        for n, card in enumerate(cards):
            parts["body"].insertWidget(n, card)
        parts["cards"] = cards

    def show_record(self, record: bench.Record) -> None:
        parts = self._parts(record.kind)
        self.shown[record.kind] = record
        parts["title"].setText(f"{record.title}  ({record.when})")
        given = bench.tested_text(record)
        _said(parts["tested"], given)
        self._set_cards(parts, [CardView(card, not given, lambda ident, k=record.kind: self.use(k, ident))
                                for card in bench.cards(record)])
        parts["stack"].setCurrentIndex(1)
        parts["note"].setText("  ".join(x for x in (f"Reference: {record.reference}" if record.reference else "",
                                                     record.note) if x))
        self.draw()

    def _ask_delete(self, kind: str) -> None:
        if self.shown[kind] is not None:
            self._parts(kind)["confirm"].show()

    def delete_shown(self, kind: str) -> None:
        parts = self._parts(kind)
        record = self.shown[kind]
        parts["confirm"].hide()
        if record is None:
            return
        row = parts["earlier"].currentRow()
        self.history.remove(record)
        self._list_earlier(kind, max(row, 0))
        self._show_earlier(kind, parts["earlier"].currentRow())
        self.said.setText("Deleted.")

    def _take(self, outcome: bench.Outcome) -> None:
        if outcome.record is None:
            self.said.setText(outcome.problem)
            return
        for h in outcome.heard:  # what a recognizer took, for the Whole set tab's estimates
            if h.gpu_bytes or h.cpu_bytes:
                self.perf.measured.model("recognizer", h.engine, h.device, h.gpu_bytes, h.cpu_bytes)
        self.history.add(outcome.record)
        self._parts(outcome.record.kind)["search"].clear()
        self._list_earlier(outcome.record.kind)
        self.show_record(outcome.record)
        self.said.setText("Done. This comparison is kept under Earlier comparisons.")

    def _conversation_choice(self, kind: str) -> tuple[QComboBox, str]:
        w = self.window_
        return (w.recognizer, "recognizer") if kind == bench.RECOGNIZERS else (w.translator, "translator")

    def use(self, kind: str, ident: str) -> None:
        combo, what = self._conversation_choice(kind)
        if self.window_.running():
            self.said.setText(bench.STOP_FIRST)
            return
        index = combo.findData(ident)
        if index < 0:
            self.said.setText(f"The main window doesn't offer that {what} for the language chosen there. "
                              "Change the language in Models first.")
            return
        combo.setCurrentIndex(index)
        self.said.setText(f"{combo.currentText().strip()} is now the conversation's {what}.")
        self.draw()

    def copy_table(self, kind: str) -> None:
        record = self.shown[kind]
        if record is not None:
            QGuiApplication.clipboard().setText(bench.markdown(record))
            self.said.setText("Copied. Paste it wherever you keep notes.")

    # -------------------------------------------------------------- whole set

    def fill_from_window(self) -> None:
        w = self.window_
        usable = [e.dir_name for e in w.engines if e.enabled()]
        _choices(self.w_asr, usable, w.recognizer.currentData())
        _choices(self.w_asr2, ["(none)"] + usable, "(none)")
        _choices(self.w_mt, ["(none)"] + [t.id for t in w.translators if t.enabled()], w.translator.currentData())
        _choices(self.w_voice, ["(none)"] + [v.dir_name for v in w.voices if v.enabled()], "(none)")
        self.refresh_whole()

    def apply_set(self) -> None:
        w = self.window_
        if w.running():
            self.said.setText(bench.STOP_FIRST)
            return
        done, missing = [], []
        for combo, ident, what in ((w.recognizer, self.w_asr.currentText(), "recognizer"),
                                   (w.translator, self.w_mt.currentText(), "translator")):
            if ident in ("", "(none)"):
                continue
            index = combo.findData(ident)
            if index < 0:
                missing.append(what)
            else:
                combo.setCurrentIndex(index)
                done.append(f"{what} {combo.currentText().strip()}")
        text = f"The conversation now uses: {', '.join(done)}." if done else ""
        if missing:
            text += (f" The main window doesn't offer that {' or '.join(missing)} for the language chosen there: "
                     "change the language first.")
        self.said.setText(text.strip())

    def refresh_whole(self) -> None:
        w, measured = self.window_, self.perf.measured
        estimates = []
        for combo in (self.w_asr, self.w_asr2):
            engine = next((e for e in w.engines if e.dir_name == combo.currentText()), None)
            if engine is not None:
                estimates.append(perf.estimate_recognizer(engine, measured, self.perf.gpu))
        entry = next((t for t in w.translators if t.id == self.w_mt.currentText()), None)
        if entry is not None:
            estimates.append(perf.estimate_translator(entry, measured, self.perf.gpu))
        voice = next((v for v in w.voices if v.dir_name == self.w_voice.currentText()), None)
        if voice is not None:
            estimates.append(perf.estimate_voice(voice))
        sample = self.sampler.latest()
        ours_gpu = sum(e.gpu_bytes for e in self.perf.loaded.values())
        verdict = perf.verdict(estimates, sample, ours_gpu, sample.ram_ours if sample else 0)
        level = verdict.level if sample else "ok"
        color = COLORS.get(level, "")
        self.verdict_label.setText(verdict.text if sample else "Measuring this computer's memory...")
        self.verdict_label.setStyleSheet(f"color: {color}; font-weight: bold" if color else "")
        _fill(self.estimate_table, [[e.name, e.device.upper(), gb(e.gpu_bytes), gb(e.cpu_bytes),
                                     "measured here" if e.measured else "its files"] for e in estimates])
        self.estimate_table.resizeColumnsToContents()
        speed = measured.speed(self.w_asr.currentText(), self.w_mt.currentText())
        if speed["runs"]:
            self.speed_label.setText(
                f"Measured in {speed['runs']} run(s) here: recognition RTF {speed['asr_rtf']}, "
                f"translation {speed['translate_ms']} ms a sentence, first sound "
                f"{speed['first_audio_ms'] or '-'} ms after speech ends (medians).")
        else:
            self.speed_label.setText("Speed: this recognizer and translator have not been measured together here "
                                     "yet. Press Measure on a recording.")
        _fill(self.runs_table, [[r["when"], r["recognizer"], r["translator"], r["mode"], r["asr_rtf"] or "",
                                 r["translate_ms"] or "", r["first_audio_ms"] or "",
                                 gb(r["peak_gpu_used"]) if r["peak_gpu_used"] else ""]
                                for r in reversed(measured.runs[-100:])])
        self.runs_table.resizeColumnsToContents()

    def measure(self, path: str | None = None) -> None:
        """Run a recording through the chosen recognizer and translator and
        keep what it took (the performance panel does the keeping)."""
        if not self._ready("whole").enabled:
            return
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "A recording to measure this set with",
                                                  str(self.root / "tests" / "fixtures" / "files"), AUDIO_FILES)
        if not path:
            return
        from ..filesource import read_16k_mono
        from ..pipeline import ArraySource, Options, Pipeline

        w = self.window_
        asr, mt = self.w_asr.currentText(), self.w_mt.currentText()
        options = Options(translate=mt != "(none)", speak=False, mt="" if mt == "(none)" else mt, asr=asr,
                          streaming=False)
        config, pyconfig = dataclasses.replace(w.config), dataclasses.replace(w.pyconfig)
        self._free_the_memory()
        self.bench_events = events = queue.Queue()
        self.bench_note = ""
        self.bench_file = Path(path).name
        self.said.setText("")

        def run() -> None:
            try:
                source = ArraySource(read_16k_mono(Path(path)))
                self.bench_pipeline = Pipeline(self.root, config, options, events, source, pyconfig).start()
                self.bench_pipeline.join()
            except Exception as e:  # shown in the bench, never raised into Qt
                events.put(ev.Error(f"the measurement failed: {e}"))
            events.put(None)

        threading.Thread(target=run, name="volis-benchmark", daemon=True).start()
        self.draw()

    def _drain_measurement(self) -> None:
        if self.bench_events is None:
            return
        sample = self.sampler.latest()
        if sample is not None and sample.gpu is not None and self.perf.run_began:
            self.perf.run_peak = max(self.perf.run_peak, sample.gpu.used)
        while True:
            try:
                event = self.bench_events.get_nowait()
            except queue.Empty:
                return
            if event is None:
                self.bench_events = self.bench_pipeline = None
                self.said.setText(self.bench_note or "Measured. The run is at the top of the table.")
                self.refresh_whole()
                return
            if isinstance(event, ev.Error):
                self.bench_note = event.message
            self.perf.observe(event)

    # -------------------------------------------------------------- drawing

    def tick(self) -> None:
        self._ticks += 1
        for clip in (self.r_sound, self.t_sound):
            clip.tick()
        while True:
            try:
                outcome = self.worker.outcomes.get_nowait()
            except queue.Empty:
                break
            self._take(outcome)
        self._drain_measurement()
        if self._ticks % 7 == 0 and self.isVisible() and self.tabs.currentIndex() == 2:
            self.refresh_whole()
        self.draw()

    def draw(self) -> None:
        running, busy = self.window_.running(), self.busy()
        self.banner.setVisible(running)
        self.stop_button.setVisible(running)
        self.busy_bar.setVisible(busy)
        self.cancel_button.setVisible(busy)
        if busy:
            if not self.busy_label.text().startswith("Stopping"):
                doing = self.worker.status or (f"Measuring this set on {self.bench_file}..."
                                               if self.bench_events is not None else "Starting...")
                self.busy_label.setText(f"{doing.rstrip('.')}. Nothing more to do: please wait.")
        else:
            self.busy_label.setText("")
        self.busy_label.setVisible(busy)
        from_sound = self.t_from_sound.isChecked()
        self.t_text.setVisible(not from_sound)
        self.t_sound_box.setVisible(from_sound)
        for kind, button, reason in ((bench.RECOGNIZERS, self.r_run, self.r_reason),
                                     (bench.TRANSLATORS, self.t_run, self.t_reason), ("whole", self.w_run, self.w_reason)):
            state = self._ready(kind)
            button.setEnabled(state.enabled)
            reason.setText(state.message)
            reason.setVisible(bool(state.message))
        self._draw_steps(from_sound)
        for clip in (self.r_sound, self.t_sound):
            clip.setEnabled(not busy)
        for kind in (bench.RECOGNIZERS, bench.TRANSLATORS):
            self._draw_results(kind, running, busy)
        self.said.setVisible(bool(self.said.text()))

    def _draw_steps(self, from_sound: bool) -> None:
        given = self.t_sound.has_sound() if from_sound else bool(typed.lines_of(self.t_text.toPlainText()))
        for steps, filled in (
            (self.r_steps, [self.r_sound.has_sound(), bool(_ticked(self.r_models)),
                            bool(self.r_reference.toPlainText().strip()) or None]),
            (self.t_steps, [given, bool(_ticked(self.t_models)), bool(self.t_reference.toPlainText().strip()) or None]),
            (self.w_steps, [bool(self.w_asr.currentText())]),
        ):
            for step, state in zip(steps, bench.step_states(filled)):
                step.set_state(state)

    def _draw_results(self, kind: str, running: bool, busy: bool) -> None:
        parts = self._parts(kind)
        shown = self.shown[kind] is not None
        words = "Working. The answer will appear here." if busy else (
            self._ready(kind).message or "Ready. Press Compare, and the answer will appear here.")
        if parts["empty"].text() != words:
            parts["empty"].setText(words)
        parts["copy"].setVisible(shown)
        parts["delete"].setVisible(shown)
        parts["hint"].setVisible(shown and any(not c.card.failed for c in parts["cards"]))
        parts["tested"].setVisible(bool(parts["tested"].text()))
        parts["note"].setVisible(bool(parts["note"].text()))
        combo, _what = self._conversation_choice(kind)
        for view_ in parts["cards"]:
            current = view_.card.ident == combo.currentData()
            view_.use.setEnabled(not running and not current)
            view_.use.setText("In use now" if current else "Use in the conversation")
            view_.use.setToolTip("Stop the conversation to change this." if running else "Choose this model in Models.")

    # -------------------------------------------------------------- showing and closing

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        self.sampler.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.sampler.stop()
        super().hideEvent(event)

    def shutdown(self) -> None:
        """The main window is closing."""
        self._timer.stop()
        for clip in (self.r_sound, self.t_sound):
            if clip.recorder is not None:
                clip.recorder.stop()
                clip.recorder = None
        if self.bench_pipeline is not None:
            self.bench_pipeline.stop()
        self.sampler.stop()
        self.worker.close()
