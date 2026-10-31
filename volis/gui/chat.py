"""The conversation, drawn: one scrolling column of what `bubbles.items` says.
It only draws; every rule about what appears, and where, is in bubbles.py."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget

from . import bubbles, talk
from .session import has_rtl

MAX_BUBBLE_WIDTH = 680
BUBBLE_SHARE = 0.72  # of the conversation's width
MAX_COLUMN_WIDTH = 1040
PADDING_X, PADDING_Y = 12, 9
FOLLOW_MARGIN = 80  # this close to the bottom counts as reading the newest line
MAX_SPEAKER_POINTS = 11
LRM = "‎"  # keeps a label with Persian in it reading left to right
# Absolute: without it, a layout mirrors a plain left or right for a right-to-left widget.
ON_LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute
ON_RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute


def _label(name: str) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setTextFormat(Qt.TextFormat.PlainText)  # what people say is never markup
    label.setWordWrap(True)
    return label


def _fit(label: QLabel, text: str, points: int, width: int) -> None:
    """Size a line to its text, up to `width`. A wrapped label left to Qt breaks
    even a short sentence in two, whatever room it has. The height is measured
    the way the label draws, since its own estimate can add a blank line."""
    label.setVisible(bool(text))
    if not text:
        return
    label.setText(text)
    label.ensurePolished()  # or a page not shown yet is measured in the wrong font
    font = label.font()
    font.setPointSize(points)
    label.setFont(font)
    if label.objectName() != "speaker":  # the speaker's label is laid out by its side, not its script
        label.setLayoutDirection(Qt.LayoutDirection.RightToLeft if has_rtl(text) else Qt.LayoutDirection.LeftToRight)
    metrics = label.fontMetrics()
    used = min(metrics.horizontalAdvance(text) + 4, width)
    tall = metrics.boundingRect(QRect(0, 0, used, 100_000), Qt.TextFlag.TextWordWrap, text).height()
    label.setFixedSize(used, tall)


class ClickableBubble(QFrame):
    def __init__(self, clicked) -> None:
        super().__init__()
        self.clicked = clicked

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt's name
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked()
        super().mouseReleaseEvent(event)


class BubbleRow(QWidget):
    """A speaker's label and their bubble, on their side of the conversation."""

    def __init__(self, side: str, clicked=lambda key: None) -> None:
        super().__init__()
        self.side = side
        self.key = ""
        self._drawn = None
        self.speaker = _label("speaker")
        self.bubble = ClickableBubble(lambda: clicked(self.key))
        self.bubble.setObjectName("bubbleLeft" if side == bubbles.LEFT else "bubbleRight")
        self.original = _label("original")
        self.translation = _label("translation")
        self.status = _label("status")
        self.problem = _label("problem")
        self.note = _label("note")
        self._lines = QVBoxLayout(self.bubble)
        self._lines.setContentsMargins(PADDING_X, PADDING_Y, PADDING_X, PADDING_Y)
        self._lines.setSpacing(4)
        for line in (self.original, self.translation, self.status, self.problem, self.note):
            self._lines.addWidget(line)
        along = QHBoxLayout()
        along.setContentsMargins(0, 0, 0, 0)
        if side == bubbles.RIGHT:
            along.addStretch(1)
        along.addWidget(self.bubble)
        if side == bubbles.LEFT:
            along.addStretch(1)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addWidget(self.speaker, 0, ON_RIGHT if side == bubbles.RIGHT else ON_LEFT)
        column.addLayout(along)

    def draw(self, item: bubbles.Bubble, points: int, width: int) -> None:
        if self._drawn == (item, points, width):
            return
        self._drawn = (item, points, width)
        self.key = item.key
        self.bubble.setCursor(Qt.CursorShape.PointingHandCursor if item.translation else Qt.CursorShape.ArrowCursor)
        inner = width - 2 * PADDING_X
        small = max(points - 2, 8)
        _fit(self.speaker, LRM + "  ·  ".join(p for p in (item.speaker, item.when) if p),
             min(small, MAX_SPEAKER_POINTS), width)
        _fit(self.original, item.original, max(points - 1, 8), inner)
        _fit(self.translation, item.translation, points + 3, inner)
        _fit(self.status, item.status, small, inner)
        _fit(self.problem, item.problem, points, inner)
        _fit(self.note, item.note, small, inner)
        for line in (self.original, self.translation, self.status, self.problem, self.note):
            # Each line sits on the side its own script starts from.
            right = line.layoutDirection() == Qt.LayoutDirection.RightToLeft
            self._lines.setAlignment(line, ON_RIGHT if right else ON_LEFT)
        if self.bubble.property("speaking") != item.speaking:
            self.bubble.setProperty("speaking", item.speaking)
            self.bubble.style().unpolish(self.bubble)
            self.bubble.style().polish(self.bubble)


class NoteRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._drawn = None
        self.text = _label("muted")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.text, 0, Qt.AlignmentFlag.AlignHCenter)

    def draw(self, item: bubbles.Note, points: int, width: int) -> None:
        if self._drawn != (item, points, width):
            self._drawn = (item, points, width)
            _fit(self.text, item.text, max(points - 2, 8), width)


class ChatView(QScrollArea):
    """The whole conversation. It follows the newest line, unless the reader
    has scrolled up to read an earlier one."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("chatBody")
        self._column = QVBoxLayout(body)
        self._column.setSpacing(12)
        self._column.addStretch(1)  # a short conversation sits at the bottom, by the controls
        self.setWidget(body)
        self.rows: dict[str, QWidget] = {}
        self.bubble_clicked = lambda key: None  # the window's
        self._items: list = []
        self._points = 12
        self.verticalScrollBar().rangeChanged.connect(self._range_changed)
        self._following = True
        self.verticalScrollBar().valueChanged.connect(self._scrolled)

    def _scrolled(self, value: int) -> None:
        self._following = value >= self.verticalScrollBar().maximum() - FOLLOW_MARGIN

    def _range_changed(self, _low: int, high: int) -> None:
        if self._following:
            QTimer.singleShot(0, lambda: self.verticalScrollBar().setValue(self.verticalScrollBar().maximum()))

    def bubble_width(self) -> int:
        return max(200, min(MAX_BUBBLE_WIDTH, int(self._column_width() * BUBBLE_SHARE)))

    def _column_width(self) -> int:
        return min(self.viewport().width() - 40, MAX_COLUMN_WIDTH)

    def show_items(self, items: list, points: int) -> None:
        keys = [i.key for i in items]
        if keys[: len(self.rows)] != list(self.rows):  # lines were removed: start again
            for row in self.rows.values():
                self._column.removeWidget(row)
                row.deleteLater()
            self.rows = {}
        self._items, self._points = items, points
        width = self.bubble_width()
        for item in items:
            row = self.rows.get(item.key)
            if row is None:
                row = BubbleRow(item.side, lambda key: self.bubble_clicked(key)) if item.kind == "bubble" else NoteRow()
                self.rows[item.key] = row
                self._column.addWidget(row)
            row.draw(item, points, width)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt's name
        """Everything measured while hidden is measured again, for real."""
        super().showEvent(event)
        for row in self.rows.values():
            row._drawn = None
        self.show_items(self._items, self._points)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt's name
        super().resizeEvent(event)
        margin = max(20, (self.viewport().width() - MAX_COLUMN_WIDTH) // 2)
        self._column.setContentsMargins(margin, 16, margin, 16)
        self.show_items(self._items, self._points)


class AudioBar(QWidget):
    """The one player: play or pause, a bar, and the time, or a line saying
    why there is nothing to play. `extras` is for what only one page has."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("audioBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.extras = QHBoxLayout(self)
        self.extras.setContentsMargins(16, 8, 16, 8)
        self.play = QPushButton("Play")
        self.play.setFixedWidth(76)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.time = QLabel()
        self.time.setObjectName("muted")
        self.note = _label("muted")
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("link")
        self.extras.addWidget(self.play)
        self.extras.addWidget(self.slider, 1)
        self.extras.addWidget(self.time)
        self.extras.addWidget(self.note, 1)
        self.extras.addWidget(self.close_button)

    def draw(self, replay) -> None:
        for widget in (self.play, self.slider, self.time):
            widget.setVisible(replay.active())
        self.note.setVisible(not replay.active())
        self.note.setWordWrap(True)
        if not replay.active():
            return
        self.play.setText("Pause" if replay.playing() else "Play")
        position, duration = replay.position(), replay.clip.seconds
        if not self.slider.isSliderDown():
            self.slider.setValue(1000 if replay.finished else int(1000 * position / (duration or 1.0)))
        self.time.setText(talk.bar_time(position, duration))
