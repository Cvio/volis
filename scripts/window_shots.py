"""Pictures of the real window, made without showing it: for HANDOFF.md's before and
after, and (P18) for the help pages, so they can't go out of date.

    .venv\\Scripts\\python.exe scripts\\window_shots.py <folder> [--prefix p14-after]

Opens the window on this machine's models and settings (which are never
written), puts it in each state, and saves one PNG per state into <folder>.
No model is loaded: the "running" pictures are made by giving the window the
events a real conversation would send.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from volis import paths  # noqa: E402

paths.apply_offline_environment(paths.app_root())

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from volis import events as ev  # noqa: E402
from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui.window import MainWindow  # noqa: E402

CONVERSATION = [
    ("1.1", "es", "Buenos días, ¿en qué puedo ayudarle?", "en", "Good morning, how can I help you?"),
    ("2.1", "es", "Necesito renovar mi licencia de conducir.", "en", "I need to renew my driver's license."),
    ("3.1", "es", "¿Trajo una identificación con fotografía?", "en", "Did you bring a photo ID?"),
]

# The test bench's pictures: comparisons as it would show them, with no model run.
HEARD = [
    ["Whisper turbo", "کجا درد می‌کند؟ از دیروز سرم درد می‌کند.", "640 ms", "5.9x faster than speech", "graphics card",
     "1.7 GB", "0.0%", "0.0%", ""],
    ["MMS", "کجا درد میکند از دیروز سرم درد می کند", "410 ms", "9.3x faster than speech", "graphics card", "3.9 GB",
     "2.9%", "25.0%", ""],
]
TRANSLATED = [
    ["کجا درد می‌کند؟", "NLLB-200 1.3B", "Where does it hurt?", "590 ms", "graphics card", "100.0", ""],
    ["کجا درد می‌کند؟", "Gemma 3 4B", "Where is the pain?", "410 ms", "graphics card", "31.4", ""],
]


def running_events(source: str, target: str) -> list:
    """What a short conversation sends the window, without any model."""
    events = [ev.Loading("recognizer"), ev.ModelLoaded("recognizer", "recognizer", "cuda", 1_600_000_000, 0, 2.0),
              ev.ModelLoaded("translator", "translator", "cuda", 2_900_000_000, 0, 1.5), ev.Listening()]
    for n, (sid, _lang, text, _to, translation) in enumerate(CONVERSATION, 1):
        events += [ev.Final(n, text, source, 2400, 310),
                   ev.SentenceMsg(sid, n, text, source, float(n * 5), float(n * 5 + 2.4), False),
                   ev.Translated(sid, translation, target, 480, "cuda", "translator", n - 1)]
    return events


def test_bench(app, window, args) -> None:
    """Each tab of the test bench, showing a comparison. Nothing is run and
    nothing is added to this machine's history."""
    from volis import bench, typed
    from volis.gui.testbench import TestBench

    tb = TestBench(window)
    tb.resize(1040, 780)
    tb.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    tb.show()
    tb.r_reference.setPlainText("کجا درد می‌کند؟ از دیروز سرم درد می‌کند.")
    tb.r_sound.label.setText("a recording, 3.8 s")
    tb.show_record(bench.Record("2026-10-09 10:00", bench.RECOGNIZERS, "Persian, a recording, 3.8 s of speech in 1 part",
                                bench.RECOGNIZER_COLUMNS, HEARD, ["a", "b"], bench.ERROR_NOTE,
                                "کجا درد می‌کند؟ از دیروز سرم درد می‌کند."))
    tb.t_text.setPlainText("کجا درد می‌کند؟")
    tb.t_reference.setPlainText("Where does it hurt?")
    tb.show_record(bench.Record("2026-10-09 10:05", bench.TRANSLATORS, "Persian > English, typed, 1 line",
                                bench.TRANSLATOR_COLUMNS, TRANSLATED, ["a", "b"], typed.SCORE_NOTE, "Where does it hurt?"))
    tb.sampler.history.append(tb.sampler.sample())
    tb.refresh_whole()
    for index, name in enumerate(("recognizers", "translators", "whole-set")):
        tb.tabs.setCurrentIndex(index)
        app.processEvents()
        tb.draw()
        app.processEvents()
        path = args.folder / f"{args.prefix}-testbench-{name}.png"
        tb.grab().save(str(path))
        print(path)
    tb.shutdown()
    tb.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--prefix", default="window")
    parser.add_argument("--size", default="1280x820")
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    root = paths.app_root()
    config, _ = Config.load(paths.config_file(root))
    pyconfig, _ = PythonConfig.load(paths.python_config_file(root))
    config.languages.source, config.languages.target = "es", "en"
    config.mode.kind = "turn"
    config.peer.enabled = False
    app = QApplication.instance() or QApplication([])
    window = MainWindow(root, config, pyconfig)
    window.save = lambda: None  # pictures never change the user's settings
    width, height = (int(n) for n in args.size.split("x"))
    window.resize(width, height)
    # Drawn with the real fonts, but never put on the screen (Qt's "offscreen"
    # mode has no fonts on Windows: every letter comes out as a box).
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()

    def shot(name: str) -> None:
        app.processEvents()
        window.refresh()
        app.processEvents()
        path = args.folder / f"{args.prefix}-{name}.png"
        window.grab().save(str(path))
        print(path)

    shot("stopped")
    if hasattr(window, "advanced_toggle"):  # P14: the settings most people never open
        window.advanced_toggle.setChecked(True)
        shot("advanced")
        window.advanced_toggle.setChecked(False)
    test_bench(app, window, args)
    # A conversation, as the window would show it while running.
    window.session.begin("es", "en", False, True, False)
    window.pipeline = object()  # "running", without a pipeline: nothing here touches it
    for event in running_events("es", "en"):
        window.session.apply(event)
    shot("running")
    window.pipeline = None
    window.perf_panel.sampler.stop()
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
