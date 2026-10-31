"""The new window (`volis-ui-plan.md`): an icon rail, a top bar, and the
conversation filling the rest. It takes over from window.py at U6; until then it
opens with --new-window. It only draws: the colours are in theme.py, what the
conversation shows in bubbles.py, the Talk page's rules in talk.py, what the
events mean in session.py."""

from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import time
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QProgressBar, QPushButton, QSizePolicy, QSlider, QStackedWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from .. import audio, clips, models, paths, playback, typed
from .. import events as ev
from .. import peer as peer_mod
from .. import shared as shared_mod
from ..config import Config, ConfigError, PythonConfig, save_python_selections
from ..pipeline import Options, Pipeline
from . import bubbles, devicetest, talk, theme, view
from . import session as ses
from .chat import ChatView
from .window import KEY_SYMBOLS, TurnKeyFilter, qt_key

log = logging.getLogger(__name__)

TALK, SAVED, SETTINGS = 0, 1, 2
START, LOADING, CONVERSATION = 0, 1, 2
REFRESH_MS = 100
ICON_SIZE = 24
PAUSE_RANGE = (0.3, 3.0)  # seconds; [vad].min_silence_ms


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


def _named(widget, name: str):
    widget.setObjectName(name)
    return widget


def _styled(name: str) -> QWidget:
    widget = _named(QWidget(), name)
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
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


def _restyle(widget: QWidget, name: str, value) -> None:
    """Change a property the style sheet looks at."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class AppWindow(QMainWindow):
    def __init__(self, root: Path, config: Config, pyconfig: PythonConfig) -> None:
        super().__init__()
        self.root, self.config, self.pyconfig = root, config, pyconfig
        self.session = ses.Session()
        self.events: queue.Queue = queue.Queue()
        self.pipeline: Pipeline | None = None
        self.ending = False
        self.clips = clips.Clips()
        self.replay = clips.Replay()
        self.review_player = None  # for listening once the conversation's own player has gone
        self.mic_watch = talk.MicWatch()
        self.mic_silent = False
        self.engines: list = []
        self.voices: list = []
        self.inputs: list = []
        self.outputs: list = []
        self.found = False  # models and devices have been looked for
        self._found_now = None  # what the search thread found, for the window's thread to take
        self.offered = talk.offered_ways(pyconfig)
        self.way = talk.saved_way(config, self.offered)
        self.shared_keys = {side: qt_key(shared_mod.key(side, config.shared)) for side in shared_mod.SIDES}
        self.turn_key = qt_key(config.mode.turn_key)
        self.turn_key_state = ses.TurnKey()
        self.holding = False
        self.side_notes: dict[str, str] = {}
        self.addresses: list[str] = []  # this computer's, for the other person to type
        self.preferred_asr = ""  # the recognizer this conversation prefers, as the pipeline was told
        self.details_open = False
        self.test_message: str | None = None
        self.testing = False
        self._filling = False
        self.setWindowTitle("Volis")
        self.resize(1180, 760)
        self.setFont(QFont("Segoe UI", 10))
        self._build()
        self.apply_theme()
        self._key_filter = TurnKeyFilter(self)
        QApplication.instance().installEventFilter(self._key_filter)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self._timer.start(REFRESH_MS)
        self.refresh()
        # Reading the models takes seconds; the window is open meanwhile.
        threading.Thread(target=self._search, name="volis-discover", daemon=True).start()

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
        rail = _styled("rail")
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
        bar = _styled("topBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(8)
        self.languages = _text("", "languages", 12)
        self.languages.setWordWrap(False)
        row.addWidget(self.languages)
        row.addStretch(1)
        self.sound = QPushButton("Sound on")
        self.sound.setCheckable(True)
        self.sound.setToolTip("Whether Volis speaks the translations. They are always shown.")
        self.sound.clicked.connect(self.sound_clicked)
        row.addWidget(self.sound)
        row.addWidget(_text("Microphone", "muted"))
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setFixedWidth(70)
        row.addWidget(self.level)
        self.smaller, self.larger = QPushButton("A-"), QPushButton("A+")
        self.smaller.setToolTip("Smaller text")
        self.larger.setToolTip("Larger text")
        self.smaller.clicked.connect(lambda: self.change_text_size(False))
        self.larger.clicked.connect(lambda: self.change_text_size(True))
        row.addWidget(self.smaller)
        row.addWidget(self.larger)
        self.end_button = QPushButton("End conversation")
        self.end_button.clicked.connect(self.end_conversation)
        row.addWidget(self.end_button)
        return bar

    def _build_banner(self) -> QFrame:
        banner = _named(QFrame(), "banner")
        layout = QVBoxLayout(banner)
        row = QHBoxLayout()
        words = QVBoxLayout()
        self.banner_title = _text("", "heading")
        self.banner_advice = _text("", "muted")
        words.addWidget(self.banner_title)
        words.addWidget(self.banner_advice)
        row.addLayout(words, 1)
        self.banner_fix, self.banner_details, self.banner_close = QPushButton(), QPushButton("Details"), QPushButton("Close")
        self.banner_fix.clicked.connect(self.problem_fix)
        self.banner_details.clicked.connect(self.toggle_details)
        self.banner_close.clicked.connect(self.dismiss_problem)
        for button in (self.banner_fix, self.banner_details, self.banner_close):
            row.addWidget(button)
        layout.addLayout(row)
        self.banner_more = _text("", "muted")
        self.banner_more.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.banner_more)
        return banner

    def _build_talk(self) -> QWidget:
        page = _named(QWidget(), "page")
        column = QVBoxLayout(page)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.top_bar = self._build_top_bar()
        column.addWidget(self.top_bar)
        self.banner = self._build_banner()
        holder = QHBoxLayout()
        holder.setContentsMargins(16, 10, 16, 0)
        holder.addWidget(self.banner)
        column.addLayout(holder)
        self.talk_stack = QStackedWidget()
        self.talk_stack.addWidget(self._build_start())
        self.talk_stack.addWidget(self._build_loading())
        conversation = _named(QWidget(), "page")
        inner = QVBoxLayout(conversation)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        self.chat = ChatView()
        self.chat.bubble_clicked = self.bubble_clicked
        inner.addWidget(self.chat, 1)
        inner.addWidget(self._build_audio_bar())
        inner.addWidget(self._build_controls())
        self.talk_stack.addWidget(conversation)
        column.addWidget(self.talk_stack, 1)
        return page

    def _build_start(self) -> QWidget:
        page = _named(QWidget(), "page")
        outer = QHBoxLayout(page)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.addStretch(1)
        column.setSpacing(10)
        column.addWidget(_text("New conversation", "heading", 18))
        column.addSpacing(10)
        row = QHBoxLayout()
        self.first_label, self.second_label = _text("", "muted"), _text("", "muted")
        self.first_language, self.second_language = QComboBox(), QComboBox()
        self.swap_button = QPushButton("⇄")
        self.swap_button.setToolTip("Swap the languages")
        self.swap_button.clicked.connect(self.swap_languages)
        for label, combo in ((self.first_label, self.first_language), (self.second_label, self.second_language)):
            part = QVBoxLayout()
            part.addWidget(label)
            part.addWidget(combo)
            combo.setMinimumWidth(240)
            combo.currentIndexChanged.connect(self.start_choices_changed)
            row.addLayout(part)
            if combo is self.first_language:
                row.addWidget(self.swap_button, 0, Qt.AlignmentFlag.AlignBottom)
        column.addLayout(row)
        column.addSpacing(14)
        self.ways_box = QWidget()
        ways_column = QVBoxLayout(self.ways_box)
        ways_column.setContentsMargins(0, 0, 0, 0)
        ways_column.addWidget(_text("How will you talk?", "muted"))
        self.way_group = QButtonGroup(self)
        self.way_group.setExclusive(True)
        self.way_buttons: dict[str, QPushButton] = {}
        for way in self.offered:
            button = _named(QPushButton(f"{way.title}\n{way.blurb}"), "way")
            button.setCheckable(True)
            button.clicked.connect(lambda _checked, name=way.name: self.choose_way(name))
            self.way_group.addButton(button)
            self.way_buttons[way.name] = button
            ways_column.addWidget(button)
        self.way_buttons[self.way.name].setChecked(True)
        self.ways_box.setVisible(len(self.offered) > 1)
        column.addWidget(self.ways_box)
        column.addSpacing(14)
        self.start_note = _text("", "problem")
        column.addWidget(self.start_note)
        self.start_button = _named(QPushButton("Start"), "primary")
        self.start_button.clicked.connect(self.start)
        column.addWidget(self.start_button)
        column.addStretch(2)
        outer.addLayout(column)
        outer.addStretch(1)
        return page

    def _build_loading(self) -> QWidget:
        page = _named(QWidget(), "page")
        outer = QHBoxLayout(page)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.addStretch(1)
        column.addWidget(_text("Getting ready to translate", "heading", 16))
        self.loading_languages = _text("This can take a minute.", "muted")
        column.addWidget(self.loading_languages)
        bar = QProgressBar()
        bar.setRange(0, 0)  # how long a model takes can't be known beforehand
        bar.setTextVisible(False)
        bar.setFixedWidth(420)
        column.addWidget(bar)
        self.loading_words = _text("", "muted")
        column.addWidget(self.loading_words)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.end_conversation)
        column.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignLeft)
        column.addStretch(2)
        outer.addLayout(column)
        outer.addStretch(1)
        return page

    def _build_peer_box(self) -> QFrame:
        box = _named(QFrame(), "peerBox")
        column = QVBoxLayout(box)
        self.peer_mine = _text("", "muted")
        self.peer_mine.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        column.addWidget(self.peer_mine)
        row = QHBoxLayout()
        self.peer_input = QLineEdit()
        self.peer_input.setPlaceholderText("The other computer's address")
        self.peer_input.returnPressed.connect(self.connect_peer)
        self.peer_input.setText(self.config.peer.peer_addr)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self.connect_peer)
        row.addWidget(self.peer_input, 1)
        row.addWidget(self.connect_button)
        column.addLayout(row)
        return box

    def _build_audio_bar(self) -> QWidget:
        """The one player: play or pause, a bar, and the time. Clicking a bubble fills it."""
        self.audio_bar = _styled("audioBar")
        row = QHBoxLayout(self.audio_bar)
        row.setContentsMargins(16, 8, 16, 8)
        self.bar_play = QPushButton("Play")
        self.bar_play.setFixedWidth(76)
        self.bar_play.clicked.connect(self.bar_play_clicked)
        self.bar_slider = QSlider(Qt.Orientation.Horizontal)
        self.bar_slider.setRange(0, 1000)
        self.bar_slider.sliderReleased.connect(self.bar_seek)
        self.bar_time = _text("", "muted")
        self.bar_time.setWordWrap(False)
        self.bar_note = _text("", "muted")
        self.bar_close = _named(QPushButton("Close"), "link")
        self.bar_close.clicked.connect(self.close_bar)
        row.addWidget(self.bar_play)
        row.addWidget(self.bar_slider, 1)
        row.addWidget(self.bar_time)
        row.addWidget(self.bar_note, 1)
        row.addWidget(self.bar_close)
        self.audio_bar.hide()
        return self.audio_bar

    def _build_controls(self) -> QWidget:
        controls = _styled("controls")
        column = QVBoxLayout(controls)
        column.setContentsMargins(16, 10, 16, 10)
        column.setSpacing(8)
        self.link_words = _text("", "muted")
        column.addWidget(self.link_words)
        self.peer_box = self._build_peer_box()
        column.addWidget(self.peer_box)
        self.side_note = _text("", "muted")
        column.addWidget(self.side_note)
        self.hands_free = _text("", "heading", 12)
        self.hands_free.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.hands_free)
        buttons = QHBoxLayout()
        self.speak_left, self.speak_right, self.speak_one = [_named(QPushButton(), "speak") for _ in range(3)]
        self.speak_left.clicked.connect(lambda: self.shared_key("left"))
        self.speak_right.clicked.connect(lambda: self.shared_key("right"))
        self.speak_one.clicked.connect(self.talk_clicked)
        for button in (self.speak_left, self.speak_right, self.speak_one):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # Space and the arrows are the keys, never a focused button
            buttons.addWidget(button, 1)
        column.addLayout(buttons)
        self.type_box = QWidget()
        typing = QHBoxLayout(self.type_box)
        typing.setContentsMargins(0, 0, 0, 0)
        self.type_text = QLineEdit()
        self.type_text.setPlaceholderText("Type a sentence")
        self.type_text.returnPressed.connect(lambda: self.submit_typed("left" if self.way.name == talk.TOGETHER else ""))
        typing.addWidget(self.type_text, 1)
        self.type_left, self.type_right, self.type_one = QPushButton(), QPushButton(), QPushButton("Translate")
        self.type_left.clicked.connect(lambda: self.submit_typed("left"))
        self.type_right.clicked.connect(lambda: self.submit_typed("right"))
        self.type_one.clicked.connect(lambda: self.submit_typed(""))
        for button in (self.type_left, self.type_right, self.type_one):
            typing.addWidget(button)
        self.type_box.hide()
        column.addWidget(self.type_box)
        self.type_toggle = _named(QPushButton("Type a sentence instead"), "link")
        self.type_toggle.clicked.connect(self.toggle_typing)
        self.new_button = _named(QPushButton("New conversation"), "primary")
        self.new_button.clicked.connect(self.new_conversation)
        column.addWidget(self.type_toggle, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(self.new_button, 0, Qt.AlignmentFlag.AlignHCenter)
        return controls

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
        self.settings_busy = _text("End the conversation to change the sound settings.", "muted")
        column.addWidget(self.settings_busy)
        column.addSpacing(6)
        column.addWidget(_text("Sound", "heading", 12))
        self.input_device, self.output_device = QComboBox(), QComboBox()
        self.test_microphone, self.test_speakers = QPushButton("Test"), QPushButton("Test")
        self.test_microphone.clicked.connect(self.run_microphone_test)
        self.test_speakers.clicked.connect(self.run_speaker_test)
        for words, combo, test in (("Microphone", self.input_device, self.test_microphone),
                                   ("Speakers", self.output_device, self.test_speakers)):
            row = QHBoxLayout()
            label = _text(words, "muted")
            label.setFixedWidth(110)
            combo.setMinimumWidth(320)
            combo.currentIndexChanged.connect(self.sound_settings_changed)
            row.addWidget(label)
            row.addWidget(combo)
            row.addWidget(test)
            row.addStretch(1)
            column.addLayout(row)
        self.test_status = _text("", "muted")
        column.addWidget(self.test_status)
        self.headset = QCheckBox("Using a headset")
        self.headset.setToolTip("Leave this off with speakers, or Volis would hear itself.")
        self.headset.setChecked(not self.config.tts.half_duplex)
        self.headset.toggled.connect(self.sound_settings_changed)
        column.addWidget(self.headset)
        column.addSpacing(10)
        self.pause_box = QWidget()
        pause_row = QHBoxLayout(self.pause_box)
        pause_row.setContentsMargins(0, 0, 0, 0)
        pause_column = QVBoxLayout()
        pause_column.addWidget(_text("Hands-free", "heading", 12))
        pause_line = QHBoxLayout()
        self.pause = QDoubleSpinBox()
        self.pause.setRange(*PAUSE_RANGE)
        self.pause.setSingleStep(0.1)
        self.pause.setDecimals(1)
        self.pause.setSuffix(" s")
        self.pause.setValue(self.config.vad.min_silence_ms / 1000)
        self.pause.valueChanged.connect(self.sound_settings_changed)
        pause_words = _text("Pause before a sentence ends", "muted")
        pause_words.setWordWrap(False)
        pause_line.addWidget(pause_words)
        pause_line.addWidget(self.pause)
        pause_line.addStretch(1)
        pause_column.addLayout(pause_line)
        pause_row.addLayout(pause_column)
        self.pause_box.setVisible(talk.WAYS[talk.HANDS_FREE] in self.offered)
        column.addWidget(self.pause_box)
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
        column.addWidget(_text("Text size: use A- and A+ during a conversation.", "muted"))
        self.settings_problem = _text("", "problem")
        self.settings_problem.hide()
        column.addWidget(self.settings_problem)
        column.addStretch(1)
        return page

    # -------------------------------------------------------------- what is installed

    def _search(self) -> None:
        """On its own thread: what is in models\\ and which devices exist."""
        problem = ""
        found_asr = models.discover(paths.asr_dir(self.root), models.Role.ASR)
        found_tts = models.discover(paths.tts_dir(self.root), models.Role.TTS)
        try:
            inputs, outputs = audio.list_input_devices(), audio.list_output_devices()
        except audio.AudioError as e:
            inputs, outputs, problem = [], [], str(e)
        self._found_now = ([e for e in found_asr if isinstance(e, models.Engine)],
                           [e for e in found_tts if isinstance(e, models.Engine)], inputs, outputs, problem)

    def _take_found(self) -> None:
        self.engines, self.voices, self.inputs, self.outputs, problem = self._found_now
        self._found_now = None
        self.found = True
        if problem:
            self.session.last_error = problem
        self._filling = True
        for combo, devices, chosen in ((self.input_device, self.inputs, self.config.audio.input_device),
                                       (self.output_device, self.outputs, self.config.audio.output_device)):
            combo.clear()
            combo.addItem("Windows' default", "")
            for device in devices:
                combo.addItem(device.name, device.name)
            combo.setCurrentIndex(max(0, combo.findData(chosen)))
        self._filling = False
        self._fill_languages()

    def _fill_languages(self) -> None:
        """The two lists, for the way chosen, with its last languages selected."""
        offered = talk.languages_offered(self.pyconfig, self.engines)
        self.language_tags = offered
        first, second = talk.languages_of(self.config, self.way.name)
        self._filling = True
        for combo, chosen, tags in ((self.first_language, first, offered),
                                    (self.second_language, second, self._seconds(offered))):
            combo.clear()
            for tag in tags:
                combo.addItem(talk.language_choice(tag), tag)
            combo.setCurrentIndex(max(0, combo.findData(chosen)))
        self._filling = False
        self.first_label.setText(self.way.first)
        self.second_label.setText(self.way.second)
        self.refresh()

    def _seconds(self, offered: list[str]) -> list[str]:
        """Hands-free only translates into the second language, so it needn't be one Volis can hear."""
        if self.way.name != talk.HANDS_FREE:
            return offered
        from .. import varieties

        wanted = {t.lower() for t in self.pyconfig.setup.languages}
        return [v.tag for v in varieties.TABLE if not wanted or v.tag.lower() in wanted]

    # -------------------------------------------------------------- choices before a conversation

    def choose_way(self, name: str) -> None:
        self.way = talk.WAYS[name]
        self._fill_languages()

    def start_choices_changed(self) -> None:
        if not self._filling:
            self.refresh()

    def swap_languages(self) -> None:
        first, second = self.first_language.currentData(), self.second_language.currentData()
        self._filling = True
        self.first_language.setCurrentIndex(max(0, self.first_language.findData(second)))
        self.second_language.setCurrentIndex(max(0, self.second_language.findData(first)))
        self._filling = False
        self.refresh()

    def start_problem(self) -> str:
        if not self.found:
            return "Getting ready..."
        return talk.can_start(self.way.name, self.first_language.currentData() or "",
                              self.second_language.currentData() or "", self.language_tags)

    def start(self) -> None:
        """Start a conversation with what is chosen on the start screen."""
        if self.start_problem() or self.pipeline is not None:
            return
        first, second = self.first_language.currentData(), self.second_language.currentData()
        talk.choose(self.config, self.way.name, first, second)
        self.save()
        paired = self.way.name == talk.TWO_COMPUTERS
        self.session.begin(first, second, False, True, paired)
        self.session.clear()
        self.side_notes = {}
        self.ending = False
        self.mic_watch = talk.MicWatch()
        self.close_bar()
        self._close_review_player()
        self.clips = clips.Clips()
        ev.restart_clock()
        self.events = queue.Queue()
        self.preferred_asr = talk.recognizer_choice(first, self.engines, self.config.asr.engine)
        self.addresses = talk.addresses_to_show(peer_mod.local_addresses()) if paired else []
        options = Options(speak=True, pair=paired, asr=self.preferred_asr, clips=self.clips)
        self.pipeline = Pipeline(self.root, dataclasses.replace(self.config), options, self.events, None,
                                 self.pyconfig)
        self.pipeline.muted = not self.config.tts.enabled
        self.pipeline.start()
        self.refresh()

    def end_conversation(self) -> None:
        if self.pipeline is not None:
            self.ending = True
            self.close_bar()  # its player goes with the conversation
            self.pipeline.stop()
            self.refresh()

    def new_conversation(self) -> None:
        self.close_bar()
        self.clips = clips.Clips()
        self.session.clear()
        self.session.last_error = None
        self.refresh()

    # -------------------------------------------------------------- during a conversation

    def tick(self) -> None:
        """Every 100 ms: take the pipeline's events, then redraw."""
        if self._found_now is not None:
            self._take_found()
        changed = False
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            changed = True
            self.session.apply(event)
            if isinstance(event, ev.Level):
                self.mic_watch.heard(event.db, time.monotonic())
            elif isinstance(event, ev.SpeakingStarted):
                self.replay.forget()  # a new sentence is queued: closing the bar mustn't clear it
                self.close_bar()
            elif isinstance(event, ev.Stopped):
                self._finished()
        silent = self.mic_watch.silent(talk.microphone_open(self.session), time.monotonic())
        if silent != self.mic_silent:
            self.mic_silent, changed = silent, True
        if self.replay.active():
            self.replay.update()
            self._draw_audio_bar()
        if self.test_message is not None:
            self.test_status.setText(self.test_message)
            self.test_message = None
            changed = True
        if changed:
            self.refresh()

    def _finished(self) -> None:
        if self.pipeline is not None:
            self.pipeline.join(2.0)
        self.pipeline, self.ending = None, False

    def shared_keys_active(self) -> bool:
        return self.pipeline is not None and self.session.mode == "shared" and self.session.state == ses.LISTENING

    def shared_key_for(self, key) -> str:
        for side, wanted in self.shared_keys.items():
            if wanted is not None and key == wanted:
                return side
        return "escape" if key == Qt.Key.Key_Escape and self.session.shared_can_cancel() else ""

    def shared_key(self, which: str) -> None:
        """A side's button or key, or Escape, as a turn."""
        if self.pipeline is None:
            return
        if which == "escape":
            self.pipeline.cancel()
            return
        action, why = self.session.shared_press(which)
        if action == "end":
            self.pipeline.end_turn()
        elif action == "ignore":
            log.info("shared machine: %s ignored: %s", which, why)
        else:
            direction = self._direction(which)
            if direction is not None:
                self.close_bar()
                self.pipeline.begin_shared_turn(direction)
        self.refresh()

    def _direction(self, side: str):
        """Where one person's words go; None, with the reason shown, if nowhere."""
        try:
            resolved = shared_mod.direction(side, self.config.shared, self.engines, self.preferred_asr, self.voices)
        except shared_mod.SharedError as e:
            self.side_notes[side] = str(e)
            return None
        self.side_notes[side] = " ".join(resolved.warnings)
        return resolved.direction

    def turn_key_active(self) -> bool:
        link = talk.link(self.session)
        return self.pipeline is not None and self.session.mode == "turn" and self.session.state == ses.LISTENING \
            and link.connected

    def turn_key_event(self, raw: ses.KeyEdges) -> None:
        edges = self.turn_key_state.update(raw, self.isActiveWindow())
        if edges.pressed and self.speak_one.isEnabled():
            self.talk_clicked()

    def talk_clicked(self) -> None:
        if self.pipeline is None:
            return
        if self.session.turn in (ses.RECORDING, ses.WAITING):
            self.pipeline.end_turn()
        else:
            self.close_bar()
            self.pipeline.begin_turn()

    def connect_peer(self) -> None:
        if self.pipeline is None:
            return
        typed_address = self.peer_input.text().strip()
        try:
            address = peer_mod.parse_address(typed_address)
        except peer_mod.AddressError as e:
            self.session.last_error = str(e)
            self.refresh()
            return
        if self.config.peer.peer_addr != typed_address:
            self.config.peer.peer_addr = typed_address
            self.save()
        self.pipeline.connect(address)

    def sound_clicked(self, on: bool) -> None:
        """Applies at once, from the next sentence, and is remembered."""
        self.config.tts.enabled = on
        if self.pipeline is not None:
            self.pipeline.muted = not on
        self.save()
        self.refresh()

    def toggle_typing(self) -> None:
        self.type_box.setVisible(not self.type_box.isVisible())
        if self.type_box.isVisible():
            self.type_text.setFocus()

    def submit_typed(self, side: str) -> None:
        """Translate what is typed, as that person's words; `side` is "" with only one person here."""
        lines = typed.lines_of(self.type_text.text())
        if not lines or self.pipeline is None:
            return
        direction = None
        if side:
            direction = self._direction(side)
            if direction is None:
                self.refresh()
                return
        self.pipeline.translate_typed(lines, direction)
        self.type_text.clear()

    # -------------------------------------------------------------- listening again

    def _output(self):
        """What to play through: the conversation's player, or our own after it."""
        if self.pipeline is not None:
            return self.pipeline.output()
        if self.review_player is None:
            self.review_player = playback.Player(self.config.audio.output_device, playback.Gate(False))
        return self.review_player

    def _close_review_player(self) -> None:
        if self.review_player is not None:
            self.review_player.close()
            self.review_player = None

    def bubble_clicked(self, key: str) -> None:
        item = next((i for i in bubbles.items(self.session) if i.key == key), None)
        if item is None or not item.translation:
            return
        if not talk.can_replay(self.session):
            self._show_bar_note(talk.WAIT_TO_LISTEN)
            return
        clip = self.clips.spoken(item.speech)
        if clip is None:
            self.replay.stop()
            self._show_bar_note(talk.no_clip_words(self.session, item.side))
            self.draw_conversation()
            return
        try:
            player = self._output()
            if player is None:
                self._show_bar_note(talk.NOTHING_TO_PLAY)
                return
            self.replay.play(item.speech, clip, player)
        except playback.PlaybackError as e:
            self.session.last_error = str(e)
        self.refresh()

    def _show_bar_note(self, words: str) -> None:
        self.bar_note.setText(words)
        self.audio_bar.show()
        self._draw_audio_bar()

    def _draw_audio_bar(self) -> None:
        r = self.replay
        for widget in (self.bar_play, self.bar_slider, self.bar_time):
            widget.setVisible(r.active())
        self.bar_note.setVisible(not r.active())
        if not r.active():
            return
        was = r.key
        self.bar_play.setText("Pause" if r.playing() else "Play")
        duration = r.clip.seconds or 1.0
        position = r.position()
        if not self.bar_slider.isSliderDown():
            self.bar_slider.setValue(int(1000 * position / duration))
        self.bar_time.setText(talk.bar_time(position, r.clip.seconds))
        if was and r.finished:
            self.bar_slider.setValue(1000)

    def bar_play_clicked(self) -> None:
        self.replay.toggle()
        self._draw_audio_bar()

    def bar_seek(self) -> None:
        if self.replay.active():
            self.replay.seek(self.bar_slider.value() / 1000 * self.replay.clip.seconds)
            self._draw_audio_bar()

    def close_bar(self) -> None:
        had = self.replay.active()
        self.replay.stop()
        self.audio_bar.hide()
        self.bar_note.setText("")
        if had:
            self.draw_conversation()

    # -------------------------------------------------------------- problems

    def current_problem(self) -> talk.Problem | None:
        if self.session.last_error:
            return talk.problem_for(self.session.last_error)
        return talk.MIC_SILENT if self.mic_silent else None

    def problem_fix(self) -> None:
        self.rail_buttons[SETTINGS].click()

    def toggle_details(self) -> None:
        self.details_open = not self.details_open
        self.refresh()

    def dismiss_problem(self) -> None:
        self.session.last_error = None
        self.details_open = False
        self.refresh()

    # -------------------------------------------------------------- settings

    def sound_settings_changed(self) -> None:
        if self._filling:
            return
        c = self.config
        c.audio.input_device = self.input_device.currentData() or ""
        c.audio.output_device = self.output_device.currentData() or ""
        c.tts.half_duplex = not self.headset.isChecked()
        c.vad.min_silence_ms = round(self.pause.value() * 1000)
        self.close_bar()
        self._close_review_player()  # it may be playing to the old speakers
        self.save()

    def _run_test(self, work) -> None:
        if self.testing or self.pipeline is not None:
            return
        self.testing = True

        def say(words: str) -> None:
            self.test_message = words

        def run_it() -> None:
            try:
                work(say)
            except Exception as e:  # the reason is the result
                say(f"The test failed: {e}")
            finally:
                self.testing = False

        threading.Thread(target=run_it, name="volis-device-test", daemon=True).start()

    def run_speaker_test(self) -> None:
        language, device, voices = self.config.languages.target, self.output_device.currentData() or "", list(self.voices)
        self._run_test(lambda say: devicetest.speakers(voices, language, device, say))

    def run_microphone_test(self) -> None:
        language = self.config.languages.source
        folder = talk.recognizer_choice(language, self.engines, self.config.asr.engine)
        engine = next((e for e in self.engines if e.dir_name == folder), None)
        mic, out = self.input_device.currentData() or "", self.output_device.currentData() or ""
        self._run_test(lambda say: devicetest.microphone(engine, language, mic, out, say))

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
            self.config.save_selections(paths.config_file(self.root))
            save_python_selections(paths.python_config_file(self.root), self.pyconfig)
        except ConfigError as e:
            self.settings_problem.setText(str(e))
            self.settings_problem.show()
        else:
            self.settings_problem.hide()

    # -------------------------------------------------------------- drawing

    def draw_conversation(self) -> None:
        self.chat.show_items(bubbles.items(self.session, self.replay.key), self.pyconfig.window.text_size)

    def refresh(self) -> None:
        s = self.session
        running = self.pipeline is not None
        screen = LOADING if s.state == ses.STARTING else CONVERSATION if running or s.lines else START
        self.talk_stack.setCurrentIndex(screen)
        self.top_bar.setVisible(screen == CONVERSATION)
        self._draw_banner()
        if screen == START:
            self._draw_start()
        elif screen == LOADING:
            self.loading_words.setText(talk.loading_words(s.loading))
            self.cancel_button.setEnabled(not self.ending)
        else:
            self._draw_top_bar(running)
            self._draw_controls(running)
            self.draw_conversation()
            if not self.audio_bar.isHidden():
                self._draw_audio_bar()
            elif self.replay.active():
                self.audio_bar.show()
                self._draw_audio_bar()
        self.settings_busy.setVisible(running)
        for widget in (self.input_device, self.output_device, self.headset, self.pause, self.test_microphone,
                       self.test_speakers):
            widget.setEnabled(not running)

    def _draw_banner(self) -> None:
        problem = self.current_problem()
        self.banner.setVisible(problem is not None)
        if problem is None:
            return
        self.banner_title.setText(problem.title)
        self.banner_advice.setText(problem.advice)
        self.banner_fix.setText(problem.fix)
        self.banner_fix.setVisible(bool(problem.fix))
        self.banner_details.setVisible(bool(problem.details))
        self.banner_close.setVisible(bool(self.session.last_error))
        self.banner_more.setText(problem.details)
        self.banner_more.setVisible(self.details_open and bool(problem.details))

    def _draw_start(self) -> None:
        why = self.start_problem()
        self.start_button.setEnabled(not why)
        self.start_note.setText(why)
        self.start_note.setVisible(bool(why))

    def _draw_top_bar(self, running: bool) -> None:
        self.languages.setText(bubbles.languages_title(*self.session.languages))
        on = self.config.tts.enabled
        self.sound.setChecked(on)
        self.sound.setText("Sound on" if on else "Sound off")
        self.level.setValue(talk.level_share(self.session.level_db))
        _restyle(self.level, "silent", self.mic_silent)
        self.end_button.setVisible(running)
        self.end_button.setEnabled(not self.ending)
        self.end_button.setText("Ending..." if self.ending else "End conversation")

    def _draw_speak(self, button: QPushButton, state: talk.Speak) -> None:
        button.setText(f"{state.label}\n{state.hint}")
        button.setEnabled(state.enabled and not self.ending)
        _restyle(button, "tone", state.tone)

    def _draw_controls(self, running: bool) -> None:
        s = self.session
        name = self.way.name
        together, two = running and name == talk.TOGETHER, running and name == talk.TWO_COMPUTERS
        self.speak_left.setVisible(together)
        self.speak_right.setVisible(together)
        self.speak_one.setVisible(two)
        self.hands_free.setVisible(running and name == talk.HANDS_FREE)
        self.type_toggle.setVisible(running)
        self.type_box.setVisible(self.type_box.isVisible() and running)
        self.new_button.setVisible(not running)
        if together:
            for side, button, typing in (("left", self.speak_left, self.type_left),
                                         ("right", self.speak_right, self.type_right)):
                words = bubbles.native_name(shared_mod.language(side, self.config.shared))
                key = shared_mod.key(side, self.config.shared)
                self._draw_speak(button, talk.side_button(s, side, words, KEY_SYMBOLS.get(key, key)))
                typing.setText(words)
        self.type_left.setVisible(together)
        self.type_right.setVisible(together)
        self.type_one.setVisible(running and not together)
        notes = [n for n in (*self.side_notes.values(), *s.side_problems.values()) if n] if together else []
        self.side_note.setText(" ".join(dict.fromkeys(notes)))
        self.side_note.setVisible(bool(notes))
        self.hands_free.setText(talk.hands_free_words(s))
        link = talk.link(s)
        self.link_words.setVisible(two)
        self.peer_box.setVisible(two and link.can_connect)
        if two:
            self._draw_speak(self.speak_one, talk.talk_button(s))
            words = link.words + (f" {s.floor_note}" if s.floor_note else "")
            self.link_words.setText(words)
            self.link_words.setObjectName("problem" if link.bad else "status" if link.good else "muted")
            self.link_words.style().unpolish(self.link_words)
            self.link_words.style().polish(self.link_words)
            self.peer_mine.setText("This computer's address: " + (", ".join(self.addresses) or "no network"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.pipeline is not None:
            self.pipeline.stop()
            self.pipeline.join(5.0)
        self._timer.stop()
        self.replay.stop()
        self._close_review_player()
        QApplication.instance().removeEventFilter(self._key_filter)
        event.accept()
