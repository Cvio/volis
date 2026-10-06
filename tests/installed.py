"""Which models are installed, for tests that run a real one. A test names
the model it would like and takes another when that one isn't there, so the
tests depend neither on one machine's models folder nor on the user's own
settings."""

import pytest

from volis import models, paths


def recognizer(language: str, prefer: str = "") -> str:
    """The folder of an installed, usable recognizer for `language`:
    `prefer` when it is there, else the best-ranked one, a large GGUF speech
    model only when nothing else covers the language. Skips the test when
    there is none."""
    engines = [e for e in models.discover(paths.asr_dir(paths.app_root()), models.Role.ASR)
               if isinstance(e, models.Engine) and e.enabled()]
    if any(e.dir_name == prefer for e in engines):
        return prefer
    ranked = [r.engine for r in models.rank(language, engines) if r.engine.languages_known]
    ranked.sort(key=lambda e: e.backend == models.LLAMACPP_AUDIO)  # stable: light ones first
    if not ranked:
        pytest.skip(f"no installed recognizer covers {language!r}")
    return ranked[0].dir_name


def translator(prefer: str = "") -> str:
    """The id of an installed, usable translator: `prefer` when it is there,
    else the smallest. Skips the test when there is none."""
    found = [t for t in models.discover_translators(paths.mt_dir(paths.app_root()))
             if isinstance(t, models.Translator) and t.enabled()]
    if any(t.id == prefer for t in found):
        return prefer
    if not found:
        pytest.skip("no usable translator is installed")
    return min(found, key=lambda t: t.size_bytes or float("inf")).id
