"""Pictures of the new window, made without showing it or saving any setting.

    .venv\\Scripts\\python.exe scripts\\app_shots.py <folder> [--prefix new] [--size 1180x760]
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

from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui import app_window, theme  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--prefix", default="new")
    parser.add_argument("--size", default="1180x760")
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    window = app_window.AppWindow(paths.app_root(), Config(), PythonConfig())
    window.save = lambda: None  # pictures never change the user's settings
    window.resize(*(int(n) for n in args.size.split("x")))
    # Drawn with the real fonts, but never put on the screen.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()

    def shot(name: str) -> None:
        for _ in range(3):  # the conversation scrolls to its end on the next turn of the loop
            app.processEvents()
        path = args.folder / f"{args.prefix}-{name}.png"
        window.grab().save(str(path))
        print(path)

    for name in theme.THEMES:
        window.choose_theme(name)
        shot(f"talk-{name}")
    window.choose_theme("graphite")
    for page, name in ((app_window.SAVED, "saved"), (app_window.SETTINGS, "settings")):
        window.rail_buttons[page].click()
        shot(name)
    window.rail_buttons[app_window.TALK].click()
    for _ in range(4):
        window.change_text_size(True)
    shot("talk-large-text")
    return 0


if __name__ == "__main__":
    sys.exit(main())
