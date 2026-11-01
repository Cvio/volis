"""The conversation's keys: names as `volis.toml` writes them, and a filter that
keeps them from also pressing whatever has the focus."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLineEdit, QPlainTextEdit

from . import session as ses

# [mode].turn_key in volis.toml uses egui's key names (it is Rust's file).
KEY_NAMES = {
    "Space": Qt.Key.Key_Space, "Enter": Qt.Key.Key_Return, "Tab": Qt.Key.Key_Tab, "Escape": Qt.Key.Key_Escape,
    "ArrowLeft": Qt.Key.Key_Left, "ArrowRight": Qt.Key.Key_Right, "ArrowUp": Qt.Key.Key_Up,
    "ArrowDown": Qt.Key.Key_Down, "Backspace": Qt.Key.Key_Backspace, "Insert": Qt.Key.Key_Insert,
    "Delete": Qt.Key.Key_Delete, "Home": Qt.Key.Key_Home, "End": Qt.Key.Key_End,
    "PageUp": Qt.Key.Key_PageUp, "PageDown": Qt.Key.Key_PageDown,
}


KEY_SYMBOLS = {"ArrowLeft": "←", "ArrowRight": "→", "ArrowUp": "↑", "ArrowDown": "↓"}


def qt_key(name: str):
    """The Qt key for a [mode].turn_key name, or None if it isn't one."""
    if name in KEY_NAMES:
        return KEY_NAMES[name]
    sequence = QKeySequence.fromString(name)
    return sequence[0].key() if sequence.count() == 1 else None


class TurnKeyFilter(QObject):
    """Takes the turn key out of the application's input before any widget
    sees it, and says what it did. A focused button treats Space as a click;
    the turn key must never also press whatever has focus. Auto-repeats of a
    held key are swallowed too, and are not presses. Installed on the
    application, so it works wherever the focus is inside the window."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window

    def eventFilter(self, _watched, event) -> bool:  # noqa: N802 - Qt's name
        kind = event.type()
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease, QEvent.Type.ShortcutOverride):
            w = self.window
            if w.shared_keys_active() and w.isActiveWindow():
                # Shared machine: each person's key, and Escape while there is
                # something to cancel (otherwise it still closes a dropdown).
                which = w.shared_key_for(event.key())
                if which:
                    # A text box with the focus keeps its arrow keys; clicking
                    # anywhere outside it gives them back.
                    if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)):
                        return False
                    if kind == QEvent.Type.ShortcutOverride:
                        event.accept()
                    elif kind == QEvent.Type.KeyPress and not event.isAutoRepeat():
                        w.shared_key(which)
                    return True
            if event.key() != w.turn_key or not w.turn_key_active() or not w.isActiveWindow():
                return False
            if isinstance(QApplication.focusWidget(), (QLineEdit, QPlainTextEdit)):
                return False  # typing a space in a text box is not a turn (P15)
            if kind == QEvent.Type.ShortcutOverride:
                event.accept()  # ours: no shortcut or button may claim it
                return True
            if not event.isAutoRepeat():
                w.turn_key_event(ses.KeyEdges(pressed=kind == QEvent.Type.KeyPress,
                                              released=kind == QEvent.Type.KeyRelease))
            return True
        return False
