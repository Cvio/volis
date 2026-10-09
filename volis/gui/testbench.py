"""The test bench: View > Test bench (Ctrl+Shift+T).

A window of its own, for whoever is choosing models or checking a change.
Nothing in it is needed to hold a conversation, which is why it is not in
the main window. Three tabs, each answering one question:

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

What can start, and why not, is decided in `bench.ready`; the work itself is
`bench.Worker`. This file only lays the controls out and paints.
"""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from .. import bench, models, perf, typed
from .. import events as ev
from ..audio import SAMPLE_RATE
from . import view

log = logging.getLogger(__name__)

AUDIO_FILES = "Audio (*.wav *.mp3 *.m4a *.flac *.ogg *.mp4);;All files (*)"
COLORS = {"ok": "", "amber": "#d08c00", "red": "#d03030", "fits": "#2e8b57", "tight": "#d08c00", "no": "#d03030"}
GRAY = "color: gray"


def gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def _checklist(height: int = 110) -> QListWidget:
    box = QListWidget()
    box.setMinimumHeight(height)
    return box


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
    """The same choices as one of the main window's lists, and its choice."""
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


def _table() -> QTableWidget:
    from .window import DirectionDelegate

    table = QTableWidget(0, 0)
    table.setWordWrap(True)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setItemDelegate(DirectionDelegate(table))
    table.setMinimumHeight(170)
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
        self.record_button.setToolTip("Record from the microphone chosen in the main window. Press again to stop.")
        self.record_button.clicked.connect(self.toggle_record)
        self.file_button = QPushButton("Choose an audio file...")
        self.file_button.clicked.connect(self.choose_file)
        self.play_button = QPushButton("Play")
        self.play_button.setToolTip("Play the sound through the speakers chosen in the main window.")
        self.play_button.clicked.connect(self.play)
        self.label = QLabel("No sound yet.")
        self.label.setStyleSheet(GRAY)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        for widget in (self.record_button, self.file_button, self.play_button):
            row.addWidget(widget)
        row.addWidget(self.label, 1)
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
        super().__init__(window, Qt.WindowType.Window)
        self.setWindowTitle("Test bench - Volis")
        self.resize(1040, 780)
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
        banner = QHBoxLayout()
        self.banner = QLabel(bench.STOP_FIRST)
        self.banner.setStyleSheet("font-weight: bold; color: #d08c00")
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
        self.busy_label.setStyleSheet("font-weight: bold")
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Stop after the model that is running now. Nothing more is loaded.")
        self.cancel_button.clicked.connect(self.cancel)
        working.addWidget(self.busy_bar)
        working.addWidget(self.busy_label, 1)
        working.addWidget(self.cancel_button)
        layout.addLayout(working)
        self.said = QLabel()  # what the last press did, when it isn't in a table
        self.said.setWordWrap(True)
        self.said.setStyleSheet(GRAY)
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

    def _results(self, kind: str, use_tip: str) -> tuple[QVBoxLayout, dict]:
        """The part under each comparison: the table, what the numbers mean,
        and what can be done with a row."""
        box = QVBoxLayout()
        earlier = QComboBox()
        earlier.setToolTip("Every comparison made here is kept. Choose one to see it again.")
        earlier.currentIndexChanged.connect(lambda index, k=kind: self._show_earlier(k, index))
        table = _table()
        table.itemSelectionChanged.connect(self.draw)
        note = QLabel()
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 8pt")
        use = QPushButton("Use in the conversation")
        use.setToolTip(use_tip)
        use.clicked.connect(lambda _checked=False, k=kind: self.use_selected(k))
        copy = QPushButton("Copy as a table")
        copy.setToolTip("Copy this comparison as a Markdown table, to paste into notes.")
        copy.clicked.connect(lambda _checked=False, k=kind: self.copy_table(k))
        top = QHBoxLayout()
        top.addWidget(QLabel("Results"))
        top.addWidget(earlier, 1)
        box.addLayout(top)
        box.addWidget(table, 1)
        box.addWidget(note)
        buttons = QHBoxLayout()
        buttons.addWidget(use)
        buttons.addWidget(copy)
        buttons.addStretch(1)
        box.addLayout(buttons)
        return box, {"earlier": earlier, "table": table, "note": note, "use": use, "copy": copy}

    def _recognizers_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.r_language = QComboBox()
        self.r_language.currentIndexChanged.connect(lambda _i: self._fill_recognizers())
        self.r_sound = ClipInput(self)
        self.r_sound.changed.connect(self.draw)
        self.r_models = _checklist()
        self.r_models.itemChanged.connect(lambda _item: self.draw())
        self.r_reference = QPlainTextEdit()
        self.r_reference.setPlaceholderText("Optional: type or paste what was really said. Each recognizer is then "
                                            "scored against it.")
        self.r_reference.setFixedHeight(64)
        form.addRow("Language spoken", self.r_language)
        form.addRow("Sound", self.r_sound)
        form.addRow("Recognizers", self.r_models)
        form.addRow("Correct text", self.r_reference)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.r_run = QPushButton("Compare recognizers")
        self.r_run.setMinimumHeight(34)
        self.r_run.clicked.connect(self.run_recognizers)
        self.r_reason = QLabel()
        self.r_reason.setStyleSheet(GRAY)
        row.addWidget(self.r_run)
        row.addWidget(self.r_reason, 1)
        layout.addLayout(row)
        results, self.r = self._results(bench.RECOGNIZERS, "Choose this recognizer in the main window.")
        layout.addLayout(results, 1)
        return page

    def _translators_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.t_source, self.t_target = QComboBox(), QComboBox()
        self.t_source.currentIndexChanged.connect(lambda _i: self._fill_recognizer_choice())
        languages = QHBoxLayout()
        languages.addWidget(self.t_source, 1)
        languages.addWidget(QLabel("into"))
        languages.addWidget(self.t_target, 1)
        self.t_from_text = QRadioButton("Text I type or paste")
        self.t_from_sound = QRadioButton("Speech: a recording or an audio file")
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
        self.t_recognizer = QComboBox()
        self.t_recognizer.setToolTip("The sound is turned into text by this recognizer first; every translator is "
                                     "then given the same text.")
        self.t_sound_box = QWidget()
        sound = QHBoxLayout(self.t_sound_box)
        sound.setContentsMargins(0, 0, 0, 0)
        sound.addWidget(self.t_sound, 2)
        sound.addWidget(QLabel("heard by"))
        sound.addWidget(self.t_recognizer, 1)
        self.t_models = _checklist()
        self.t_models.itemChanged.connect(lambda _item: self.draw())
        self.t_reference = QPlainTextEdit()
        self.t_reference.setPlaceholderText("Optional: a reference translation to score each one against (Google's, "
                                            "or a person's). One line per line of the text.")
        self.t_reference.setFixedHeight(64)
        form.addRow("Translate from", languages)
        form.addRow("Test with", kind)
        form.addRow("Text", self.t_text)
        form.addRow("Sound", self.t_sound_box)
        form.addRow("Translators", self.t_models)
        form.addRow("Reference", self.t_reference)
        self._t_form = form
        layout.addLayout(form)
        row = QHBoxLayout()
        self.t_run = QPushButton("Compare translators")
        self.t_run.setMinimumHeight(34)
        self.t_run.clicked.connect(self.run_translators)
        self.t_reason = QLabel()
        self.t_reason.setStyleSheet(GRAY)
        row.addWidget(self.t_run)
        row.addWidget(self.t_reason, 1)
        layout.addLayout(row)
        results, self.t = self._results(bench.TRANSLATORS, "Choose this translator in the main window.")
        layout.addLayout(results, 1)
        return page

    def _whole_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        intro = QLabel("Choose a recognizer, a translator and a voice to see whether they fit in this computer's "
                       "memory together. Nothing is loaded to work that out. Then measure the set on a recording.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.w_asr, self.w_asr2, self.w_mt, self.w_voice = QComboBox(), QComboBox(), QComboBox(), QComboBox()
        form.addRow("Recognizer", self.w_asr)
        form.addRow("Second recognizer (shared machine)", self.w_asr2)
        form.addRow("Translator", self.w_mt)
        form.addRow("Voice", self.w_voice)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.w_fill = QPushButton("Take the conversation's choice")
        self.w_fill.setToolTip("Set the lists above to what is chosen in the main window.")
        self.w_fill.clicked.connect(self.fill_from_window)
        self.w_apply = QPushButton("Use this set in the conversation")
        self.w_apply.setToolTip("Choose this recognizer and translator in the main window.")
        self.w_apply.clicked.connect(self.apply_set)
        row.addWidget(self.w_fill)
        row.addWidget(self.w_apply)
        row.addStretch(1)
        layout.addLayout(row)
        self.verdict_label = QLabel()
        self.verdict_label.setWordWrap(True)
        layout.addWidget(self.verdict_label)
        self.estimate_table = QTableWidget(0, 5)
        self.estimate_table.setHorizontalHeaderLabels(["Model", "On", "GPU", "System", "From"])
        self.estimate_table.setMaximumHeight(150)
        layout.addWidget(self.estimate_table)
        self.speed_label = QLabel()
        self.speed_label.setWordWrap(True)
        layout.addWidget(self.speed_label)
        measure = QHBoxLayout()
        self.w_run = QPushButton("Measure this set on a recording...")
        self.w_run.setMinimumHeight(34)
        self.w_run.setToolTip("Runs an audio file through this recognizer and translator, without speaking, as fast "
                              "as the models allow, and keeps the speeds and the memory it took.")
        self.w_run.clicked.connect(lambda _checked=False: self.measure())
        self.w_reason = QLabel()
        self.w_reason.setStyleSheet(GRAY)
        measure.addWidget(self.w_run)
        measure.addWidget(self.w_reason, 1)
        layout.addLayout(measure)
        layout.addWidget(QLabel("Every run measured on this computer (kept in logs\\performance.json):"))
        self.runs_table = QTableWidget(0, 8)
        self.runs_table.setHorizontalHeaderLabels(["When", "Recognizer", "Translator", "Mode", "ASR RTF",
                                                   "Translate ms", "First sound ms", "Peak GPU"])
        layout.addWidget(self.runs_table, 1)
        for combo in (self.w_asr, self.w_asr2, self.w_mt, self.w_voice):
            combo.currentIndexChanged.connect(lambda _i: self.refresh_whole())
        return page

    # -------------------------------------------------------------- the lists

    def refill(self) -> None:
        """Take the models and languages from the main window again (at
        opening, and after a rescan there)."""
        w = self.window_
        _copy_items(self.r_language, w.source_lang)
        _copy_items(self.t_source, w.source_lang)
        _copy_items(self.t_target, w.target_lang)
        self._fill_recognizers()
        self._fill_recognizer_choice()
        _refill(self.t_models, [(view.plain_name(t.named, t.name, t.id), t.id,
                                 view.translator_limits(t.backend) or t.id) for t in w.translators if t.enabled()])
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

    def _list_earlier(self, kind: str) -> None:
        combo = self._parts(kind)["earlier"]
        combo.blockSignals(True)
        combo.clear()
        records = self.history.of(kind)
        for record in records:
            combo.addItem(record.label())
        combo.blockSignals(False)
        combo.setEnabled(bool(records))
        if not records:
            combo.addItem("Nothing compared yet.")

    def _show_earlier(self, kind: str, index: int) -> None:
        records = self.history.of(kind)
        if 0 <= index < len(records):
            self.show_record(records[index])

    def show_record(self, record: bench.Record) -> None:
        parts = self._parts(record.kind)
        table = parts["table"]
        self.shown[record.kind] = record
        table.setColumnCount(len(record.columns))
        table.setHorizontalHeaderLabels(record.columns)
        _fill(table, record.rows)
        header = table.horizontalHeader()
        wide = {"What it heard", "Text", "Translation"}
        for column, name in enumerate(record.columns):
            header.setSectionResizeMode(column, header.ResizeMode.Stretch if name in wide
                                        else header.ResizeMode.ResizeToContents)
        table.resizeRowsToContents()
        parts["note"].setText("  ".join(x for x in (f"Reference: {record.reference}" if record.reference else "",
                                                     record.note) if x))
        self.draw()

    def _take(self, outcome: bench.Outcome) -> None:
        if outcome.record is None:
            self.said.setText(outcome.problem)
            return
        for h in outcome.heard:  # what a recognizer took, for the Whole set tab's estimates
            if h.gpu_bytes or h.cpu_bytes:
                self.perf.measured.model("recognizer", h.engine, h.device, h.gpu_bytes, h.cpu_bytes)
        self.history.add(outcome.record)
        self._list_earlier(outcome.record.kind)
        self.show_record(outcome.record)
        self.said.setText("Done. The comparison is in the table, and kept under Results.")

    def _selected(self, kind: str) -> str:
        record, table = self.shown[kind], self._parts(kind)["table"]
        row = table.currentRow()
        return record.ids[row] if record is not None and 0 <= row < len(record.ids) else ""

    def use_selected(self, kind: str) -> None:
        ident = self._selected(kind)
        if not ident:
            return
        w = self.window_
        combo, what = (w.recognizer, "recognizer") if kind == bench.RECOGNIZERS else (w.translator, "translator")
        if w.running():
            self.said.setText(bench.STOP_FIRST)
            return
        index = combo.findData(ident)
        if index < 0:
            self.said.setText(f"The main window doesn't offer that {what} for the language chosen there. "
                              "Change the language in the main window first.")
            return
        combo.setCurrentIndex(index)
        self.said.setText(f"{combo.currentText().strip()} is now the conversation's {what}.")

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
                                     "yet. Use the button below.")
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
        self._t_form.setRowVisible(self.t_text, not from_sound)
        self._t_form.setRowVisible(self.t_sound_box, from_sound)
        for kind, button, reason in ((bench.RECOGNIZERS, self.r_run, self.r_reason),
                                     (bench.TRANSLATORS, self.t_run, self.t_reason), ("whole", self.w_run, self.w_reason)):
            state = self._ready(kind)
            button.setEnabled(state.enabled)
            reason.setText(state.message)
        for clip in (self.r_sound, self.t_sound):
            clip.setEnabled(not busy)
        for kind in (bench.RECOGNIZERS, bench.TRANSLATORS):
            parts = self._parts(kind)
            parts["use"].setEnabled(bool(self._selected(kind)) and not running)
            parts["use"].setToolTip("Stop the conversation to change this." if running else
                                    "Click a row first." if not self._selected(kind) else
                                    "Choose this model in the main window.")
            parts["copy"].setEnabled(self.shown[kind] is not None)

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
