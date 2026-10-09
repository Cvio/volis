"""The performance panel: View > Performance (Ctrl+Shift+P).

A dockable panel, closed when the app starts. It sits beside the window or is
pulled out as a window of its own. It shows what a running conversation costs
this computer: GPU, memory and CPU, for volis and for the machine, once a
second, with a graph of the last five minutes (marks where sentences were
translated), the models loaded and what each takes, and the last sentences'
timings with the context each carried. Amber or red when memory is nearly
full or speech falls behind.

It also keeps what is measured here (`measured`, logs\\performance.json): the
memory each model took when it loaded and the speed of each run. The window's
"won't fit" warning and the test bench's Whole set tab read it, and the test
bench's own measuring runs are recorded through `observe`.
"""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QDockWidget, QGridLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import events as ev
from .. import perf

GB = 1e9
COLORS = {"ok": "", "amber": "#d08c00", "red": "#d03030", "fits": "#2e8b57", "tight": "#d08c00", "no": "#d03030"}
SERIES = [("GPU memory", "#4c8bf5"), ("GPU load", "#2e8b57"), ("CPU", "#d08c00")]


def gb(n: int) -> str:
    return f"{n / GB:.1f} GB"


class Graph(QWidget):
    """The last five minutes: GPU memory, GPU load and CPU as percentages, and
    a tick at the bottom for each translated sentence."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(120)
        self.samples: list[perf.Sample] = []
        self.marks: list[float] = []

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt's name
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, self.palette().base())
        p.setPen(QPen(self.palette().mid().color()))
        for share in (0.25, 0.5, 0.75):
            p.drawLine(0, int(h * share), w, int(h * share))
        if not self.samples:
            return
        now = time.monotonic()
        span = perf.HISTORY * perf.SAMPLE_S

        def x(t: float) -> int:
            return int(w - (now - t) / span * w)

        def values(s: perf.Sample) -> list[float]:
            g = s.gpu
            return [100 * g.used / g.total if g and g.total else 0.0, g.load if g else 0.0, s.cpu]

        for i, (_name, color) in enumerate(SERIES):
            p.setPen(QPen(QColor(color), 2))
            points = [(x(s.t), h - int(values(s)[i] / 100 * (h - 4)) - 2) for s in self.samples]
            for a, b in zip(points, points[1:]):
                p.drawLine(a[0], a[1], b[0], b[1])
        p.setPen(QPen(self.palette().text().color()))
        for t in self.marks:
            if now - t < span:
                p.drawLine(x(t), h - 8, x(t), h)


class PerfPanel(QDockWidget):
    def __init__(self, window) -> None:
        super().__init__("Performance", window)
        self.setObjectName("performance")
        self.window_ = window
        self.root = window.root
        self.measured = perf.Measurements.load(self.root)
        self.sampler = perf.Sampler()
        self.gpu = perf.gpu_available()
        self.loaded: dict[str, perf.Estimate] = {}  # "role:name" -> what it took when it loaded
        self.sentences: dict[str, dict] = {}  # id -> timings
        self.asr_ms: dict[int, tuple[int, int]] = {}  # utterance -> (speech ms, recognition ms)
        self.behind_until = 0.0
        self.run_began = 0.0
        self.run_peak = 0

        self.setWidget(self._now_tab())
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.BottomDockWidgetArea)
        self.visibilityChanged.connect(self._shown)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)

    # -------------------------------------------------------------- layout

    def _now_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        grid = QGridLayout()
        self.now_labels: dict[str, QLabel] = {}
        rows = [("gpu", "GPU"), ("gpu_mem", "GPU memory"), ("gpu_split", "  volis / others / free"),
                ("ram", "System memory"), ("ram_split", "  volis / others / free"), ("cpu", "CPU"),
                ("speech", "Keeping up")]
        for i, (key, text) in enumerate(rows):
            grid.addWidget(QLabel(text), i, 0)
            self.now_labels[key] = QLabel("-")
            self.now_labels[key].setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(self.now_labels[key], i, 1)
        layout.addLayout(grid)
        legend = QHBoxLayout()
        for name, color in SERIES:
            legend.addWidget(QLabel(f'<span style="color:{color}">&#9632;</span> {name}'))
        legend.addWidget(QLabel("| a tick per sentence"))
        legend.addStretch()
        layout.addLayout(legend)
        self.graph = Graph()
        layout.addWidget(self.graph)
        self.models_table = QTableWidget(0, 4)
        self.models_table.setHorizontalHeaderLabels(["Loaded", "On", "GPU", "System"])
        layout.addWidget(self.models_table)
        self.sentence_table = QTableWidget(0, 6)
        self.sentence_table.setHorizontalHeaderLabels(["Sentence", "Speech ms", "Recognize ms", "Context",
                                                       "Translate ms", "To first sound ms"])
        layout.addWidget(self.sentence_table)
        return page

    # -------------------------------------------------------------- events

    def _shown(self, visible: bool) -> None:
        if visible:
            self.sampler.start()
            self._timer.start(1000)
            self.refresh()
        else:
            self.sampler.stop()
            self._timer.stop()

    def observe(self, event) -> None:
        """Every pipeline event the window sees, and those of the test bench's measuring runs."""
        now = time.monotonic()
        if isinstance(event, ev.Loading) and not self.run_began:
            self.run_began, self.run_peak = now, 0
            self.loaded.clear()
        elif isinstance(event, ev.ModelLoaded):
            self.loaded[f"{event.role}:{event.name}"] = perf.Estimate(event.role, event.name, event.device,
                                                                     event.gpu_bytes, event.cpu_bytes, True)
            self.measured.model(event.role, event.name, event.device, event.gpu_bytes, event.cpu_bytes)
        elif isinstance(event, ev.Final):
            self.asr_ms[event.index] = (event.speech_ms, event.asr_ms)
        elif isinstance(event, ev.Translated):
            row = self.sentences.setdefault(event.id, {})
            row.update(translate_ms=event.translate_ms, context=event.context_turns)
            utterance = int(event.id.split(".")[0]) if event.id.split(".")[0].isdigit() else -1
            if utterance in self.asr_ms:
                row["speech_ms"], row["asr_ms"] = self.asr_ms[utterance]
            self.graph.marks.append(now)
        elif isinstance(event, ev.SpeakingStarted) and event.id:
            self.sentences.setdefault(event.id, {})["first_audio_ms"] = event.first_audio_ms
        elif isinstance(event, (ev.NotTranslated, ev.Error)):
            text = getattr(event, "reason", "") or getattr(event, "message", "")
            if "fell behind" in text or "is behind" in text:
                self.behind_until = now + 30
        elif isinstance(event, ev.Summary):
            self._record_run(event.stats)
        elif isinstance(event, ev.Stopped):
            self.run_began = 0.0
            self.loaded.clear()

    def _record_run(self, stats: dict) -> None:
        role = {e.role: e.name for e in self.loaded.values()}
        firsts = sorted(r["first_audio_ms"] for r in self.sentences.values() if "first_audio_ms" in r)
        self.measured.run(perf.Run(perf.now_text(), role.get("recognizer", ""), role.get("translator", ""),
                                   self.window_.config.mode.kind, stats.get("asr_rtf"), stats.get("translate_ms_median"),
                                   firsts[len(firsts) // 2] if firsts else None, stats.get("sentences", 0),
                                   self.run_peak))

    # -------------------------------------------------------------- drawing

    def refresh(self) -> None:
        sample = self.sampler.latest()
        if sample is not None and sample.gpu is not None and self.run_began:
            self.run_peak = max(self.run_peak, sample.gpu.used)
        if not self.isVisible():
            return
        self.graph.samples = list(self.sampler.history)
        self.graph.update()
        ours_gpu = sum(e.gpu_bytes for e in self.loaded.values())
        L = self.now_labels
        if sample is None:
            return
        g = sample.gpu
        if g is None:
            L["gpu"].setText("no NVIDIA GPU found (nvidia-smi)")
            for key in ("gpu_mem", "gpu_split"):
                L[key].setText("-")
        else:
            L["gpu"].setText(f"{g.name}: {g.load:.0f}% load, {g.temperature:.0f} C, {g.clock_mhz:.0f} MHz, "
                             f"{g.power_w:.0f} W")
            self._set(L["gpu_mem"], f"{gb(g.used)} of {gb(g.total)}", perf.level(g.used, g.total))
            L["gpu_split"].setText(f"{gb(ours_gpu)} / {gb(max(g.used - ours_gpu, 0))} / {gb(g.total - g.used)}")
        self._set(L["ram"], f"{gb(sample.ram_used)} of {gb(sample.ram_total)}",
                  perf.level(sample.ram_used, sample.ram_total))
        L["ram_split"].setText(f"{gb(sample.ram_ours)} / {gb(max(sample.ram_used - sample.ram_ours, 0))} / "
                               f"{gb(sample.ram_total - sample.ram_used)}")
        L["cpu"].setText(f"{sample.cpu:.0f}% of the machine; volis {sample.cpu_ours:.0f}% of one core")
        behind = time.monotonic() < self.behind_until
        self._set(L["speech"], "fell behind in the last 30 s" if behind else "yes", "red" if behind else "ok")
        self._fill(self.models_table, [[e.name, e.device.upper(), gb(e.gpu_bytes), gb(e.cpu_bytes)]
                                       for e in self.loaded.values()])
        rows = list(self.sentences.items())[-20:]
        self._fill(self.sentence_table, [[sid, r.get("speech_ms", ""), r.get("asr_ms", ""), r.get("context", ""),
                                          r.get("translate_ms", ""), r.get("first_audio_ms", "")]
                                         for sid, r in reversed(rows)])

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _set(label: QLabel, text: str, level: str) -> None:
        color = COLORS.get(level, "")
        label.setText(text)
        label.setStyleSheet(f"color: {color}; font-weight: bold" if color and level not in ("ok", "fits") else
                            f"color: {color}" if color else "")

    @staticmethod
    def _fill(table: QTableWidget, rows: list[list]) -> None:
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                item = table.item(r, c)
                if item is None:
                    table.setItem(r, c, QTableWidgetItem(str(value)))
                elif item.text() != str(value):
                    item.setText(str(value))
        table.resizeColumnsToContents()
