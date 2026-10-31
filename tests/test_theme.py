"""The themes (U1): every word must stay readable on what it sits on."""

import dataclasses

import pytest

from volis import config as config_mod
from volis.config import ConfigError, PythonConfig, save_python_selections
from volis.gui import theme


def luminance(colour: str) -> float:
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("t", theme.THEMES.values(), ids=lambda t: t.name)
def test_words_are_readable(t):
    """WCAG AA: 4.5 to 1 for ordinary text."""
    for ground in (t.background, t.rail, t.surface, t.bubble):
        assert contrast(t.text, ground) >= 4.5, ground
        assert contrast(t.muted, ground) >= 4.5, ground
    for ground in (t.background, t.surface, t.bubble):
        assert contrast(t.problem, ground) >= 4.5, ground
    for ground in (t.background, t.surface):
        assert contrast(t.accent, ground) >= 4.5, ground
    assert contrast(t.on_accent, t.accent) >= 4.5


@pytest.mark.parametrize("t", theme.THEMES.values(), ids=lambda t: t.name)
def test_every_colour_is_a_colour_and_used_by_the_sheet(t):
    sheet = theme.style_sheet(t)
    for field in dataclasses.fields(t):
        if field.name in ("name", "title"):
            continue
        assert getattr(t, field.name) in sheet, field.name


def test_config_lists_exactly_the_themes():
    assert set(config_mod.ENUMS[("window", "theme")]) == set(theme.THEMES)


def test_graphite_is_the_default():
    assert PythonConfig().window.theme == "graphite"


def test_a_chosen_theme_is_remembered(tmp_path):
    path = tmp_path / "volis-python.toml"
    config = PythonConfig()
    config.window.theme = "midnight"
    save_python_selections(path, config)
    assert PythonConfig.load(path)[0].window.theme == "midnight"


def test_a_theme_that_does_not_exist_is_refused(tmp_path):
    path = tmp_path / "volis-python.toml"
    path.write_text('[window]\ntheme = "neon"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="theme"):
        PythonConfig.load(path)
