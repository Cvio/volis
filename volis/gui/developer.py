"""Developer mode: the pages a customer's copy never
shows. Models, Test bench, Performance and every option that a customer's setup
fixes. Made only when Volis opens with --developer, and this file is not even
imported otherwise. The test bench and the performance panel read their models
and devices from `Hub`."""

from __future__ import annotations

import dataclasses
import logging
import threading
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from .. import export, filerun, models, paths, perf, scoring, varieties
from .. import events as ev
from .. import shared as shared_mod
from ..pipeline import Collected, Options
from ..translate.context import parse_glossary
from . import rescan as rescan_mod
from . import session as ses
from . import talk, view
from .chat import scrolled
from .perf_panel import PerfPanel

log = logging.getLogger(__name__)

MODELS, TEST_BENCH, PERFORMANCE, DEVELOPER = 3, 4, 5, 6  # after Talk, Saved and Settings


def _draw_models(p) -> None:
    for y in (5, 11, 17):
        p.drawRoundedRect(QRectF(4, y, 16, 4), 1.5, 1.5)


def _draw_bench(p) -> None:
    p.drawLine(QPointF(3, 20), QPointF(21, 20))
    for x, height in ((6, 7), (12, 14), (18, 10)):
        p.drawLine(QPointF(x, 20), QPointF(x, 20 - height))


def _draw_performance(p) -> None:
    for start, end in (((3, 16), (8, 11)), ((8, 11), (13, 14)), ((13, 14), (21, 5))):
        p.drawLine(QPointF(*start), QPointF(*end))


def _draw_developer(p) -> None:
    for start, end in (((8, 7), (3, 12)), ((3, 12), (8, 17)), ((16, 7), (21, 12)), ((21, 12), (16, 17)), ((14, 5), (10, 19))):
        p.drawLine(QPointF(*start), QPointF(*end))


RAIL = ((MODELS, "Models", _draw_models), (TEST_BENCH, "Test bench", _draw_bench),
        (PERFORMANCE, "Performance", _draw_performance), (DEVELOPER, "Developer", _draw_developer))


def _heading(words: str) -> QLabel:
    label = QLabel(words)
    label.setObjectName("heading")
    return label


def _note(name: str = "muted") -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class Hub:
    BENCH_BUSY = "The test bench is still working. Wait for it to finish, or press Cancel there."

    def __init__(self, window) -> None:
        self.window = window
        self.root, self.config, self.pyconfig = window.root, window.config, window.pyconfig
        self.input_device, self.output_device = window.input_device, window.output_device
        self.typed_worker = None  # the test bench asks; the new window has no worker of its own
        self.test_bench = None  # made when first opened
        self.translators: list = []
        self.broken_engines: list = []
        self.broken_translators: list = []
        self.collected = Collected()
        self.scores = ""
        self.recording: Path | None = None  # what the record on screen came from
        self._filling = True
        self.perf_panel = PerfPanel(self)
        self.pages = {MODELS: self._build_models(), TEST_BENCH: self._build_bench(),
                      PERFORMANCE: self._build_performance(), DEVELOPER: self._build_settings()}
        self._set_boxes()
        self._filling = False

    # -------------------------------------------------------------- what the bench and the panel read

    @property
    def engines(self) -> list:
        return self.window.engines

    @property
    def voices(self) -> list:
        return self.window.voices

    @property
    def pipeline(self):
        return self.window.pipeline

    @pipeline.setter
    def pipeline(self, value) -> None:
        self.window.pipeline = value

    def running(self) -> bool:
        return self.window.pipeline is not None

    def stop(self) -> None:
        self.window.end_conversation()

    def bench_busy(self) -> bool:
        return self.test_bench is not None and self.test_bench.busy()

    # -------------------------------------------------------------- pages

    def _build_models(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(32, 28, 32, 28)
        column.setSpacing(10)
        column.addWidget(_heading("Models"))
        self.recognizer, self.translator = QComboBox(), QComboBox()
        self.source_lang, self.target_lang = QComboBox(), QComboBox()  # the bench copies its languages from these
        for combo in (self.source_lang, self.target_lang):
            for variety in varieties.TABLE:
                combo.addItem(variety.display, variety.tag)
        self.source_lang.setCurrentIndex(max(0, self.source_lang.findData(self.config.languages.source)))
        self.target_lang.setCurrentIndex(max(0, self.target_lang.findData(self.config.languages.target)))
        self.source_lang.currentIndexChanged.connect(self.language_changed)
        self.recognizer.currentIndexChanged.connect(self.models_changed)
        self.translator.currentIndexChanged.connect(self.models_changed)
        form = QFormLayout()
        form.addRow("Rank recognizers for", self.source_lang)
        form.addRow("Recognizer", self.recognizer)
        form.addRow("Translator", self.translator)
        column.addLayout(form)
        self.fit_warning = _note("problem")
        column.addWidget(self.fit_warning)
        column.addSpacing(10)
        column.addWidget(_heading("Two people, this computer"))
        self.sides: dict[str, dict] = {}
        sides = QHBoxLayout()
        for side in shared_mod.SIDES:
            title, recognizer, voice = _note(), QComboBox(), QComboBox()
            side_form = QFormLayout()
            side_form.addRow(title)
            side_form.addRow("Heard by", recognizer)
            side_form.addRow("Spoken by", voice)
            voice.setToolTip("The voice this person's words are spoken in: a voice in the other person's language.")
            for combo in (recognizer, voice):
                combo.currentIndexChanged.connect(self.sides_changed)
            sides.addLayout(side_form)
            self.sides[side] = {"title": title, "recognizer": recognizer, "voice": voice}
        column.addLayout(sides)
        column.addSpacing(10)
        self.rescan_button = QPushButton("Rescan models and devices (F5)")
        self.rescan_button.clicked.connect(self.window.rescan)
        column.addWidget(self.rescan_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.notice = _note()
        self.notice.hide()
        column.addWidget(self.notice)
        column.addStretch(1)
        return scrolled(page)

    def _build_bench(self) -> QWidget:
        self.bench_holder = QWidget()
        self.bench_holder.setObjectName("page")
        layout = QVBoxLayout(self.bench_holder)
        layout.setContentsMargins(0, 0, 0, 0)
        return self.bench_holder

    def _build_performance(self) -> QWidget:
        page = QWidget()
        page.setObjectName("page")
        column = QVBoxLayout(page)
        column.setContentsMargins(16, 12, 16, 12)
        self.run_lines = _note()
        self.run_lines.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.run_lines)
        self.export_button = QPushButton("Export this run...")
        self.export_button.setToolTip("The transcript, the translation, subtitles, and everything that happened.")
        self.export_button.clicked.connect(self.export)
        column.addWidget(self.export_button, 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(self.perf_panel, 1)
        return page

    def _build_settings(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)
        column.setContentsMargins(32, 28, 32, 28)
        column.setSpacing(6)
        column.addWidget(_heading("Developer settings"))
        self.busy_note = _note()
        column.addWidget(self.busy_note)
        self.reasons: dict[str, QLabel] = {}

        def box(name: str, words: str, tip: str = "") -> QCheckBox:
            check = QCheckBox(words)
            check.setToolTip(tip)
            check.toggled.connect(self.settings_changed)
            column.addWidget(check)
            self.reasons[name] = _note()
            self.reasons[name].hide()
            column.addWidget(self.reasons[name])
            return check

        column.addSpacing(6)
        column.addWidget(_heading("Listening"))
        self.streaming = box("streaming", "Show text while speaking (streaming)",
                             "Transcribes the growing utterance every second; words two passes agree on are committed, "
                             "the rest may change. Costs more recognition.")
        self.hold_fragments = box("hold_fragments", "Join short fragments to what follows")
        self.style_hold = box("turn_style", "Hold the key while speaking, rather than press and press again")
        column.addSpacing(6)
        column.addWidget(_heading("Translating"))
        self.use_context = box("use_context", "Translate with the earlier sentences as context")
        self.revise = box("revise", "Revise earlier translations when what follows changes them",
                          "After each sentence the last few are translated again together; a short earlier sentence "
                          "whose translation changes is replaced. A sentence already spoken is never revised.")
        self.hold_speech = box("hold_speech", "Wait for the next sentence before speaking a short one",
                               "With revision and sound on: a short sentence waits at most [context] hold_speech_s for "
                               "the next one, so that it is spoken as revised.")
        self.diacritize = box("diacritize", "Add vowel marks to Arabic before it is spoken",
                              "A small model predicts the short vowels first (about 0.3 s more per sentence).")
        column.addWidget(QLabel("Glossary"))
        self.glossary = QLineEdit()
        self.glossary.setPlaceholderText("Names and terms to keep exactly, separated by commas")
        self.glossary.editingFinished.connect(self.glossary_changed)
        column.addWidget(self.glossary)
        column.addSpacing(6)
        column.addWidget(_heading("Reading a recording"))
        self.read_realtime = box("speed", "At playing speed, rather than as fast as it can")
        self.read_original = box("read_original", "Play the original while reading")
        self.read_speak = box("read_speak", "Speak the translations while reading")
        column.addStretch(1)
        return scrolled(page)

    def _set_boxes(self) -> None:
        py = self.pyconfig
        self.streaming.setChecked(py.asr.streaming)
        self.hold_fragments.setChecked(py.fragments.hold)
        self.style_hold.setChecked(self.config.mode.turn_style == "hold")
        self.use_context.setChecked(py.context.mode in ("carry", "revision"))
        self.revise.setChecked(py.context.mode == "revision")
        self.hold_speech.setChecked(py.context.hold_speech)
        self.diacritize.setChecked(py.tts.diacritize)

    # -------------------------------------------------------------- models

    def take_found(self, found_asr: list, found_mt: list) -> None:
        """What the window's search found, in the lists."""
        self.broken_engines = [e for e in found_asr if isinstance(e, models.Failed)]
        self.translators = [t for t in found_mt if isinstance(t, models.Translator)]
        self.broken_translators = [t for t in found_mt if isinstance(t, models.Failed)]
        self.fill_pickers()

    def fill_pickers(self) -> None:
        was, self._filling = self._filling, True
        self.fill_sides()
        self._fill_recognizers()
        self._fill_translators()
        self._filling = was
        if self.test_bench is not None:
            self.test_bench.refill()  # its lists are these models and languages
        self.update_fit_warning()

    def _fill_recognizers(self) -> None:
        """Ranked for the language chosen: tuned, general, other varieties, then
        models whose languages are unknown, each labelled."""
        tag = self.source_lang.currentData() or self.config.languages.source
        self.recognizer.clear()
        ranked = models.rank(tag, self.engines)
        for r in ranked:
            e = r.engine
            label = r.fit.label(tag)
            self.recognizer.addItem(view.plain_name(e.named, e.name, e.dir_name)
                                    + (f"  ({label})" if label.startswith("tuned") else ""), e.dir_name)
            self.recognizer.setItemData(self.recognizer.count() - 1, view.details([
                ("Folder", e.dir_name), ("Fit", label), ("Runs with", e.backend),
                ("Languages", ", ".join(e.languages) if e.languages_known else "not stated"),
                ("Size", view.size_text(sum(f.path.stat().st_size for f in e.files if f.present))),
                ("Details", e.detail)]), Qt.ItemDataRole.ToolTipRole)
        listed = {r.engine.dir_name for r in ranked}
        for engine in self.engines:
            if engine.dir_name not in listed and not engine.enabled():
                why = engine.unusable or "missing: " + ", ".join(engine.missing_files())
                self.recognizer.addItem(f"{view.plain_name(engine.named, engine.name, engine.dir_name)}  "
                                        "(can't be used)", engine.dir_name)
                index = self.recognizer.count() - 1
                self.recognizer.setItemData(index, why, Qt.ItemDataRole.ToolTipRole)
                self.recognizer.model().item(index).setEnabled(False)
        for failed in self.broken_engines:
            self._add_broken(self.recognizer, failed)
        if not _select(self.recognizer, self.config.asr.engine) and self.recognizer.count():
            self.recognizer.setCurrentIndex(0)  # the best fit for this language

    def _fill_translators(self) -> None:
        self.translator.clear()
        for t in self.translators:
            name = view.plain_name(t.named, t.name, t.id)
            self.translator.addItem(name if t.enabled() else f"{name}  (can't be used)", t.id)
            self.translator.setItemData(self.translator.count() - 1, view.details([
                ("Can't be used", "" if t.enabled() else (t.unusable or "missing: " + ", ".join(t.missing))),
                ("File", t.id), ("Family", t.architecture), ("Compression", view.quantization(t.path.name)),
                ("Size", view.size_text(t.size_bytes) if t.size_bytes else ""), ("Runs with", t.backend),
                ("Languages", str(len(t.languages)) if t.languages else ""),
                ("Limits", view.translator_limits(t.backend))]),
                Qt.ItemDataRole.ToolTipRole)
        for failed in self.broken_translators:
            self._add_broken(self.translator, failed)
        top = next((t.id for t in self.translators if t.top_level), "")
        if not _select(self.translator, self.pyconfig.translate.model or top):
            # The chosen one is gone: the file at the top of models\mt\, or else the first that works.
            usable = rescan_mod.translator_items(self.translators + self.broken_translators)
            _select(self.translator, rescan_mod.first_usable(usable, top))

    @staticmethod
    def _add_broken(combo: QComboBox, failed) -> None:
        """A folder that could not be understood: listed, greyed out, with the
        reason --report gives as its tooltip."""
        combo.addItem(f"{failed.dir_name}  (broken)", failed.dir_name)
        index = combo.count() - 1
        combo.setItemData(index, failed.error, Qt.ItemDataRole.ToolTipRole)
        combo.model().item(index).setEnabled(False)

    def fill_sides(self) -> None:
        """Each side's recognizers, best first, and the voices that speak the OTHER side's language."""
        was, self._filling = self._filling, True
        settings = self.config.shared
        for side in shared_mod.SIDES:
            widgets, tag = self.sides[side], shared_mod.language(side, settings)
            other = shared_mod.language(shared_mod.other(side), settings)
            widgets["title"].setText(varieties.display_name(tag))
            for combo, first, ranked, chosen, wanted in (
                (widgets["recognizer"], "(best match)", shared_mod.recognizers_for(tag, self.engines),
                 shared_mod.asr(side, settings), tag),
                (widgets["voice"], "(first match)", shared_mod.voices_for(other, self.voices),
                 shared_mod.voice(side, settings), other),
            ):
                combo.clear()
                combo.addItem(first, "")
                for r in ranked:
                    label = r.fit.label(wanted)
                    combo.addItem(view.plain_name(r.engine.named, r.engine.name, r.engine.dir_name)
                                  + (f"  ({label})" if label.startswith("tuned") else ""), r.engine.dir_name)
                if chosen and combo.findData(chosen) < 0:
                    combo.addItem(f"{chosen}  (not usable for this language)", chosen)
                _select(combo, chosen)
        self._filling = was

    def language_changed(self) -> None:
        if self._filling:
            return
        self._filling = True
        self._fill_recognizers()
        self._filling = False
        self.models_changed()

    def models_changed(self) -> None:
        if self._filling:
            return
        self.save_choices()
        self.window.save()
        self.update_fit_warning()

    def save_choices(self) -> None:
        self.config.asr.engine = self.recognizer.currentData() or ""
        self.pyconfig.translate.model = self.translator.currentData() or ""

    def sides_changed(self) -> None:
        if self._filling:
            return
        s = self.config.shared
        left, right = self.sides["left"], self.sides["right"]
        s.left_asr, s.right_asr = left["recognizer"].currentData() or "", right["recognizer"].currentData() or ""
        s.left_voice, s.right_voice = left["voice"].currentData() or "", right["voice"].currentData() or ""
        self.window.save()
        if self.running() and self.window.way.name == talk.TOGETHER and not self.window.reading:
            self.window.pipeline.prepare_shared(dataclasses.replace(s))

    def update_fit_warning(self) -> None:
        """Will the chosen recognizer and translator fit, and were they fast enough
        here? Worked out from files and from what was measured; nothing is loaded."""
        panel = self.perf_panel
        chosen = self.recognizer.currentData() or ""
        try:
            estimates = [perf.estimate_recognizer(e, panel.measured, panel.gpu) for e in self.engines
                         if e.dir_name == chosen and e.enabled()]
            entry = next((t for t in self.translators if t.id == self.translator.currentData()), None)
            if entry is not None and entry.enabled():
                estimates.append(perf.estimate_translator(entry, panel.measured, panel.gpu))
            sample = panel.sampler.latest() or panel.sampler.sample()
            ours = sum(e.gpu_bytes for e in panel.loaded.values())
            speed = panel.measured.speed(chosen, self.translator.currentData() or "")
            warning = view.fit_warning(perf.verdict(estimates, sample, ours, sample.ram_ours), speed)
        except Exception as e:  # a warning must never stop the page opening
            log.debug("no fit warning: %s", e)
            warning = view.Warning("", "")
        self.fit_warning.setText(warning.text)
        self.fit_warning.setToolTip(warning.detail)
        self.fit_warning.setVisible(bool(warning.text))

    # -------------------------------------------------------------- settings

    def context_mode(self) -> str:
        if not self.use_context.isChecked():
            return "off"
        return "revision" if self.revise.isChecked() else "carry"

    def settings_changed(self) -> None:
        if self._filling:
            return
        py = self.pyconfig
        py.asr.streaming = self.streaming.isChecked()
        py.fragments.hold = self.hold_fragments.isChecked()
        self.config.mode.turn_style = "hold" if self.style_hold.isChecked() else "toggle"
        py.context.mode = self.context_mode()
        py.context.hold_speech = self.hold_speech.isChecked()
        py.tts.diacritize = self.diacritize.isChecked()
        self.window.save()
        self.draw()

    def glossary_changed(self) -> None:
        """Applies from the next sentence, even during a conversation. It isn't saved."""
        if self.running():
            self.window.pipeline.set_glossary(parse_glossary(self.glossary.text()))

    def situation(self) -> view.Situation:
        way = self.window.way.name
        return view.Situation(running=self.running(), file_mode=self.window.reading and self.running(),
                              shared=way == talk.TOGETHER, turn_mode=way != talk.HANDS_FREE,
                              pair=way == talk.TWO_COMPUTERS, context=self.use_context.isChecked(),
                              revise=self.revise.isChecked(), speak=self.config.tts.enabled)

    def draw(self) -> None:
        """Which options can be used now, each that can't saying why."""
        running = self.running()
        why = view.disabled_reasons(self.situation())
        boxes = {"streaming": self.streaming, "hold_fragments": self.hold_fragments, "turn_style": self.style_hold,
                 "use_context": self.use_context, "revise": self.revise, "hold_speech": self.hold_speech,
                 "diacritize": self.diacritize, "speed": self.read_realtime, "read_original": self.read_original,
                 "read_speak": self.read_speak}
        if running:
            why.setdefault("read_original", view.RUNNING)
            why.setdefault("read_speak", view.RUNNING)
        elif not self.read_realtime.isChecked():
            why.setdefault("read_original", "Only at playing speed.")
        for name, widget in boxes.items():
            widget.setEnabled(name not in why)
            self.reasons[name].setText(why.get(name, ""))
            self.reasons[name].setVisible(name in why)
        self.busy_note.setText("" if not running else view.RUNNING)
        self.busy_note.setVisible(running)
        for widget in (self.source_lang, self.recognizer, self.translator, self.rescan_button):
            widget.setEnabled(not running)
        for side in self.sides.values():
            turn_busy = running and (self.window.session.turn != ses.IDLE or self.window.session.speaking)
            side["recognizer"].setEnabled(not turn_busy)
            side["voice"].setEnabled(not turn_busy)
        self._draw_run()

    def _draw_run(self) -> None:
        s = self.window.session
        lines = []
        row = s.latest_timed()
        if row is not None:
            parts = [f"recognised {row.asr_ms} ms ({row.speech_ms} ms of speech)", f"translated {row.translate_ms} ms"]
            if row.first_audio_ms is not None:
                parts.append(f"first audio {row.first_audio_ms} ms")
            lines.append("Latest: " + "  |  ".join(parts))
        if s.lines or s.stats:
            # While a run is going the pipeline hasn't summed up yet: what the rows say.
            stats = dict(s.stats) if s.stats else s.counts() | s.running_stats() | {"worst_stall_ms": s.worst_stall_ms}
            lines.append(filerun.status_line(stats))
        if self.scores:
            lines.append(self.scores)
        self.run_lines.setText("\n".join(lines))
        self.run_lines.setVisible(bool(lines))
        self.export_button.setEnabled(any(isinstance(e, ev.SentenceMsg) for e in self.collected.events))

    # -------------------------------------------------------------- a run

    def options(self) -> dict:
        """What a conversation takes from here."""
        return {"glossary": parse_glossary(self.glossary.text())}

    def begin(self, recording: Path | None) -> None:
        self.collected = Collected()
        self.scores = ""
        self.recording = recording

    def observe(self, event) -> None:
        self.collected.events.append(event)
        self.perf_panel.observe(event)

    def finished(self) -> None:
        """A recording with a reference beside it is scored. It takes a moment: not on the window's thread."""
        if self.recording is None:
            return
        path, collected = self.recording, self.collected
        source, target = self.window.session.languages

        def score() -> None:
            try:
                reference = scoring.find_reference(path)
                if reference is not None:
                    self.scores = filerun.scores(reference, collected, source, target)
            except scoring.ReferenceError as e:
                self.window.session.last_error = str(e)

        threading.Thread(target=score, name="volis-score", daemon=True).start()

    def export(self) -> None:
        default = export.default_folder(self.root, self.recording)
        default.parent.mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(self.export_button, "Export to folder", str(default.parent))
        if folder:
            self.export_to(Path(folder) / default.name if Path(folder) == default.parent else Path(folder))

    def export_to(self, folder: Path) -> None:
        prompt_file = paths.prompts_dir(self.root) / f"{self.pyconfig.translate.prompt}.txt"
        session_models = self.window.session.models
        translator, recognizer = session_models.get("translator"), session_models.get("recognizer")
        configuration = export.configuration(
            self.root, audio=self.recording, config=self.config, pyconfig=self.pyconfig, options=Options(),
            recognizer=recognizer.name if recognizer else "", translator=translator.name if translator else "",
            prompt_file=prompt_file if translator else None,
            cli={"window": True, "realtime": self.read_realtime.isChecked()},
        )
        try:
            export.write(folder, self.collected.events, configuration)
            self.scores = "\n".join(x for x in (self.scores, f"Exported to {folder}") if x)
        except OSError as e:
            self.window.session.last_error = f"cannot write the export to {folder}: {e}"
        self._draw_run()

    # -------------------------------------------------------------- pages coming and going

    def page_chosen(self, page: int) -> None:
        if page == TEST_BENCH and self.test_bench is None:
            from .testbench import TestBench  # it reads its history from disk: only when asked for

            self.test_bench = TestBench(self)
            self.bench_holder.layout().addWidget(self.test_bench)
            self.test_bench.show()
        if page == MODELS:
            self.fill_sides()  # the start screen may have changed the languages
            self.update_fit_warning()
        self.draw()

    def shutdown(self) -> None:
        self.perf_panel.sampler.stop()
        if self.test_bench is not None:
            self.test_bench.shutdown()


def _select(combo: QComboBox, data: str) -> bool:
    index = combo.findData(data)
    if index >= 0:
        combo.setCurrentIndex(index)
    return index >= 0
