"""The new window (`volis-ui-plan.md`): an icon rail, a top bar, and the
conversation filling the rest. It takes over from window.py at U6; until then it
opens with --new-window. It only draws: the colours are in theme.py, what the
conversation shows in bubbles.py, what the events mean in session.py."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton, QSizePolicy,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import paths
from ..config import Config, ConfigError, PythonConfig, save_python_selections
from . import bubbles, sample, theme, view
from . import session as ses
from .chat import ChatView

TALK, SAVED, SETTINGS = 0, 1, 2
NOT_YET = "Coming with the talking controls"
ICON_SIZE = 24


def run(root: Path, config: Config) -> int:
    app = QApplication.instance() or QApplication([])
    try:
        pyconfig, _ = PythonConfig.load(paths.python_config_file(root))
    except ConfigError as e:
        QMessageBox.critical(None, "Volis", str(e))
        return 1
    window = AppWindow(root, config, pyconfig)
    window.show()
    return app.exec()


def _draw_talk(p: QPainter) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(3, 4, 18, 13), 4, 4)
    path.moveTo(8, 17)
    path.lineTo(8, 21)
    path.lineTo(13, 17)
    p.drawPath(path)


def _draw_saved(p: QPainter) -> None:
    path = QPainterPath(QPointF(3, 7))
    path.lineTo(9, 7)
    path.lineTo(11, 9.5)
    path.lineTo(21, 9.5)
    path.lineTo(21, 19)
    path.lineTo(3, 19)
    path.closeSubpath()
    p.drawPath(path)


def _draw_settings(p: QPainter) -> None:
    for y, x in ((7, 15), (12, 8), (17, 13)):
        p.drawLine(QPointF(3, y), QPointF(21, y))
        p.save()
        p.setBrush(QColor(p.pen().color()))
        p.drawEllipse(QPointF(x, y), 2.2, 2.2)
        p.restore()


RAIL = ((TALK, "Talk", _draw_talk), (SAVED, "Saved", _draw_saved), (SETTINGS, "Settings", _draw_settings))


def _icon(draw, off: str, on: str) -> QIcon:
    """A rail icon, drawn here so it needs no image files or icon font."""
    icon = QIcon()
    for colour, state in ((off, QIcon.State.Off), (on, QIcon.State.On)):
        pixmap = QPixmap(ICON_SIZE * 3, ICON_SIZE * 3)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(3, 3)
        p.setPen(QPen(QColor(colour), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        draw(p)
        p.end()
        icon.addPixmap(pixmap, QIcon.Mode.Normal, state)
    return icon


def _named(widget: QWidget, name: str) -> QWidget:
    widget.setObjectName(name)
    return widget


def _text(words: str, name: str = "", points: int = 0) -> QLabel:
    label = QLabel(words)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    if name:
        label.setObjectName(name)
    if points:
        font = label.font()
        font.setPointSize(points)
        label.setFont(font)
    return label


class AppWindow(QMainWindow):
    def __init__(self, root: Path, config: Config, pyconfig: PythonConfig) -> None:
        super().__init__()
        self.root, self.config, self.pyconfig = root, config, pyconfig
        self.session = ses.Session()
        self.setWindowTitle("Volis")
        self.resize(1180, 760)
        self.setFont(QFont("Segoe UI", 10))
        self._build()
        self.apply_theme()
        self._load_sample()

    # -------------------------------------------------------------- layout

    def _build(self) -> None:
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_talk())
        self.pages.addWidget(self._build_saved())
        self.pages.addWidget(self._build_settings())
        whole = QWidget()
        row = QHBoxLayout(whole)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._build_rail())
        row.addWidget(self.pages, 1)
        self.setCentralWidget(whole)

    def _build_rail(self) -> QWidget:
        rail = _named(QWidget(), "rail")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        rail.setFixedWidth(84)
        column = QVBoxLayout(rail)
        column.setContentsMargins(8, 12, 8, 12)
        column.setSpacing(6)
        self.rail_group = QButtonGroup(self)
        self.rail_group.setExclusive(True)
        self.rail_buttons: dict[int, QToolButton] = {}
        for page, words, _draw in RAIL:
            button = _named(QToolButton(), "railButton")
            button.setText(words)
            button.setCheckable(True)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.rail_group.addButton(button, page)
            self.rail_buttons[page] = button
            column.addWidget(button)
        column.addStretch(1)
        self.rail_buttons[TALK].setChecked(True)
        self.rail_group.idClicked.connect(self.pages.setCurrentIndex)
        return rail

    def _build_top_bar(self) -> QWidget:
        bar = _named(QWidget(), "topBar")
        bar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)
        self.languages = _text(bubbles.languages_title(self.config.languages.source, self.config.languages.target),
                               "languages", 12)
        self.languages.setWordWrap(False)
        row.addWidget(self.languages)
        row.addStretch(1)
        self.sound, self.microphone, self.more = QPushButton("Sound"), QPushButton("Microphone"), QPushButton("...")
        for later in (self.sound, self.microphone):
            later.setEnabled(False)
            later.setToolTip(NOT_YET)
            row.addWidget(later)
        self.smaller, self.larger = QPushButton("A-"), QPushButton("A+")
        self.smaller.setToolTip("Smaller text")
        self.larger.setToolTip("Larger text")
        self.smaller.clicked.connect(lambda: self.change_text_size(False))
        self.larger.clicked.connect(lambda: self.change_text_size(True))
        row.addWidget(self.smaller)
        row.addWidget(self.larger)
        self.more.setEnabled(False)
        self.more.setToolTip(NOT_YET)
        row.addWidget(self.more)
        return bar

    def _build_talk(self) -> QWidget:
        page = _named(QWidget(), "page")
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_top_bar())
        self.chat = ChatView()
        column.addWidget(self.chat, 1)
        self.sample_note = _text("A sample conversation. The talking controls come next.", "muted")
        self.sample_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sample_note.setContentsMargins(16, 10, 16, 12)
        column.addWidget(self.sample_note)
        return page

    def _build_saved(self) -> QWidget:
        page = _named(QWidget(), "page")
        column = QVBoxLayout(page)
        column.addStretch(1)
        for words, name, points in (("Saved conversations", "heading", 16),
                                    ("Conversations you save will appear here.", "muted", 0)):
            label = _text(words, name, points)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            column.addWidget(label)
        column.addStretch(1)
        return page

    def _build_settings(self) -> QWidget:
        page = _named(QWidget(), "page")
        column = QVBoxLayout(page)
        column.setContentsMargins(32, 28, 32, 28)
        column.setSpacing(10)
        column.addWidget(_text("Settings", "heading", 16))
        column.addSpacing(10)
        column.addWidget(_text("Appearance", "heading", 12))
        column.addWidget(_text("Theme", "muted"))
        themes = QHBoxLayout()
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_buttons: dict[str, QPushButton] = {}
        for t in theme.THEMES.values():
            button = QPushButton(t.title)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, name=t.name: self.choose_theme(name))
            self.theme_group.addButton(button)
            self.theme_buttons[t.name] = button
            themes.addWidget(button)
        themes.addStretch(1)
        column.addLayout(themes)
        column.addSpacing(6)
        column.addWidget(_text("Text size: use A- and A+ on the Talk page.", "muted"))
        self.settings_problem = _text("", "problem")
        self.settings_problem.hide()
        column.addWidget(self.settings_problem)
        column.addStretch(1)
        return page

    # -------------------------------------------------------------- what it shows

    def _load_sample(self) -> None:
        self.session.begin(self.config.languages.source, self.config.languages.target, False, True)
        self.session.languages = (sample.FA, sample.EN)
        for event in sample.events():
            self.session.apply(event)
        self.languages.setText(bubbles.languages_title(sample.FA, sample.EN))
        self.draw_conversation()

    def draw_conversation(self) -> None:
        self.chat.show_items(bubbles.items(self.session), self.pyconfig.window.text_size)

    def current_theme(self) -> theme.Theme:
        return theme.THEMES[self.pyconfig.window.theme]

    def apply_theme(self) -> None:
        t = self.current_theme()
        self.setStyleSheet(theme.style_sheet(t))
        for page, _words, draw in RAIL:
            self.rail_buttons[page].setIcon(_icon(draw, t.muted, t.accent))
        self.theme_buttons[t.name].setChecked(True)
        self._draw_text_size()

    def _draw_text_size(self) -> None:
        size = self.pyconfig.window.text_size
        self.smaller.setEnabled(view.text_size_step(size, False) != size)
        self.larger.setEnabled(view.text_size_step(size, True) != size)

    # -------------------------------------------------------------- choices

    def choose_theme(self, name: str) -> None:
        self.pyconfig.window.theme = name
        self.apply_theme()
        self.save()

    def change_text_size(self, up: bool) -> None:
        self.pyconfig.window.text_size = view.text_size_step(self.pyconfig.window.text_size, up)
        self._draw_text_size()
        self.draw_conversation()
        self.save()

    def save(self) -> None:
        try:
            save_python_selections(paths.python_config_file(self.root), self.pyconfig)
        except ConfigError as e:
            self.settings_problem.setText(str(e))
            self.settings_problem.show()
        else:
            self.settings_problem.hide()
