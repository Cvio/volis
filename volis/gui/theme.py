"""The window's colours and its style sheet. No Qt in this file: it is plain
text, unit-tested (including that the words stay readable on every background),
and `app_window.py` hands it to Qt."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    name: str  # as [window].theme in volis-python.toml
    title: str  # as shown in Settings
    background: str  # the conversation, behind everything
    rail: str  # the icon rail and the top bar
    surface: str  # buttons, and the bubbles on the left
    bubble: str  # the bubbles on the right
    border: str
    text: str
    muted: str  # originals, labels, anything secondary
    disabled: str  # controls that can't be used yet
    accent: str
    on_accent: str  # words on the accent colour
    problem: str  # a sentence with no translation, a silent microphone
    listening: str  # the speak button while the microphone is open; white words on it


GRAPHITE = Theme("graphite", "Graphite", "#111214", "#17181B", "#1E1F23", "#1B2F52", "#2A2B30",
                 "#E8E9EC", "#A6A8AE", "#85878E", "#4C8DFF", "#0B1220", "#FF8A80", "#B3261E")
MIDNIGHT = Theme("midnight", "Midnight", "#0F172A", "#131C31", "#1E293B", "#134E4A", "#2B3A52",
                 "#E2E8F0", "#B4C2D3", "#8393A8", "#2DD4BF", "#06201D", "#FDA4AF", "#B3261E")
WARM_CHARCOAL = Theme("warm-charcoal", "Warm charcoal", "#171412", "#1D1916", "#26211D", "#4A3413", "#3A332C",
                      "#F0EAE2", "#C8BCAE", "#94897D", "#F5A524", "#231602", "#FFA08A", "#B3261E")

THEMES: dict[str, Theme] = {t.name: t for t in (GRAPHITE, MIDNIGHT, WARM_CHARCOAL)}


def style_sheet(t: Theme) -> str:
    """The whole window's style. Sizes of text aren't here: a style sheet's
    font would override the text size the user chose."""
    return f"""
QMainWindow, QStackedWidget, QWidget#page, QWidget#chatBody, QScrollArea {{
    background: {t.background}; border: none;
}}
QWidget {{ color: {t.text}; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; }}

QWidget#rail {{ background: {t.rail}; border-right: 1px solid {t.border}; }}
QToolButton#railButton {{
    background: transparent; border: none; border-radius: 10px; color: {t.muted}; padding: 8px 2px;
}}
QToolButton#railButton:hover {{ background: {t.surface}; }}
QToolButton#railButton:checked {{ background: {t.surface}; color: {t.accent}; }}

QWidget#topBar {{ background: {t.rail}; border-bottom: 1px solid {t.border}; }}
QLabel#languages {{ font-weight: 600; }}
QPushButton {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px 12px;
}}
QPushButton:hover {{ border-color: {t.accent}; }}
QPushButton:checked {{ background: {t.accent}; border-color: {t.accent}; color: {t.on_accent}; }}
QPushButton:disabled {{ background: transparent; color: {t.disabled}; }}

QPushButton#speak {{ border-radius: 12px; padding: 14px; font-weight: 600; }}
QPushButton#speak[tone="ready"], QPushButton#primary {{
    background: {t.accent}; border-color: {t.accent}; color: {t.on_accent};
}}
QPushButton#primary {{ font-weight: 600; padding: 9px 24px; }}
QPushButton#primary:disabled {{ background: {t.surface}; border-color: {t.border}; color: {t.muted}; }}
QPushButton#speak[tone="listening"] {{ background: {t.listening}; border-color: {t.listening}; color: #FFFFFF; }}
QPushButton#speak:disabled {{ background: {t.rail}; border-color: {t.border}; color: {t.muted}; }}
QPushButton#way {{ padding: 14px; text-align: left; }}
QPushButton#link {{ background: transparent; border: none; color: {t.muted}; padding: 4px; }}
QPushButton#link:hover {{ color: {t.accent}; }}

QComboBox, QLineEdit, QDoubleSpinBox {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {t.accent}; selection-color: {t.on_accent};
}}
QComboBox:disabled, QDoubleSpinBox:disabled, QLineEdit:disabled {{ color: {t.muted}; background: {t.rail}; }}
QComboBox QAbstractItemView {{
    background: {t.surface}; border: 1px solid {t.border};
    selection-background-color: {t.accent}; selection-color: {t.on_accent};
}}
QCheckBox {{ spacing: 8px; }}

QProgressBar {{ background: {t.surface}; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
QProgressBar[silent="true"] {{ background: {t.listening}; }}

QWidget#savedList {{ background: {t.rail}; border-right: 1px solid {t.border}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; color: {t.text}; }}
QListWidget::item:hover {{ background: {t.surface}; }}
QListWidget::item:selected {{ background: {t.accent}; color: {t.on_accent}; }}

QFrame#banner {{ background: {t.surface}; border: 1px solid {t.problem}; border-radius: 10px; }}
QFrame#peerBox {{ background: {t.rail}; border: 1px solid {t.border}; border-radius: 10px; }}
QWidget#controls, QWidget#audioBar {{ background: {t.rail}; border-top: 1px solid {t.border}; }}
QSlider::groove:horizontal {{ background: {t.surface}; height: 6px; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; height: 6px; border-radius: 3px; }}
QSlider::handle:horizontal {{ background: {t.text}; width: 14px; margin: -4px 0; border-radius: 7px; }}

QLabel#heading {{ font-weight: 600; }}
QLabel#muted, QLabel#speaker, QLabel#original, QLabel#note {{ color: {t.muted}; }}
QLabel#status {{ color: {t.accent}; }}
QLabel#problem {{ color: {t.problem}; }}

QFrame#bubbleLeft, QFrame#bubbleRight {{
    border-radius: 12px; border: 1.5px solid transparent;
}}
QFrame#bubbleLeft {{ background: {t.surface}; }}
QFrame#bubbleRight {{ background: {t.bubble}; }}
QFrame#bubbleLeft[speaking="true"], QFrame#bubbleRight[speaking="true"] {{ border-color: {t.accent}; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {t.muted}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
"""
