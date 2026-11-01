"""Pictures of the window, made without showing it or saving any setting, and
with any conversations in a throwaway folder. No model is loaded: the pictures of
a conversation are made by giving the window the events a real one would send.
README.md's pictures:

    .venv\\Scripts\\python.exe scripts\\app_shots.py docs\\images --prefix volis
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from volis import paths  # noqa: E402

paths.apply_offline_environment(paths.app_root())

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from volis import clips, conversations  # noqa: E402
from volis import events as ev  # noqa: E402
from volis.config import Config, PythonConfig  # noqa: E402
from volis.gui import app_window, bubbles, sample, talk, theme  # noqa: E402


class Stand:
    """The pipeline, for the window to believe in."""

    muted = False

    def stop(self) -> None:
        pass

    def join(self, timeout=None) -> None:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--prefix", default="new")
    parser.add_argument("--size", default="1180x760")
    args = parser.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    root = paths.app_root()
    throwaway = Path(tempfile.mkdtemp())
    paths.conversations_dir = lambda _root: throwaway  # never the user's conversations
    window = app_window.AppWindow(root, Config.load(paths.config_file(root))[0], PythonConfig.load(paths.python_config_file(root))[0])
    window.save = lambda: None  # pictures never change the user's settings
    window.choose_theme("graphite")
    window.resize(*(int(n) for n in args.size.split("x")))
    # Drawn with the real fonts, but never put on the screen.
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    while not window.found:
        window.tick()
        time.sleep(0.05)

    def shot(name: str) -> None:
        window.refresh()
        for _ in range(3):  # the conversation scrolls to its end on the next turn of the loop
            app.processEvents()
        path = args.folder / f"{args.prefix}-{name}.png"
        window.grab().save(str(path))
        print(path)

    def feed(*events) -> None:
        for event in events:
            window.session.apply(event)

    def begin(way: str, first: str, second: str, *events) -> None:
        window.way = talk.WAYS[way]
        window.session = app_window.ses.Session()
        window.session.begin(first, second, False, True, way == talk.TWO_COMPUTERS)
        window.config.shared.left_language, window.config.shared.right_language = first, second
        window.pipeline = Stand()
        feed(*events)

    for name in ("together", "two-computers", "hands-free"):
        window.choose_way(name)
        shot(f"start-{name}")
    begin(talk.TOGETHER, "fa", "en", ev.Loading("translator x"))
    shot("loading")
    begin(talk.TOGETHER, "fa", "en", *sample.events())
    feed(ev.SpeakingEnded(), ev.Translated("6.1", "It is very good.", "en", 400, "cuda", "x"), ev.SpeakingEnded())
    window.session.turn = app_window.ses.IDLE
    keeper = conversations.Keeper(root, ("fa", "en"), talk.TOGETHER, clips.Clips())
    keeper.update(bubbles.lines_from(window.session))
    keeper.save("At the restaurant", True, {"left": "Sara"})
    shot("ready")
    feed(ev.TurnStarted("left"), ev.Level(-20.0))
    shot("listening")
    feed(ev.TurnEnded())
    shot("translating")
    window.session.speaking = True
    shot("speaking")
    window.session.speaking = False
    feed(ev.TurnCancelled(), ev.Error("cannot start a turn: PortAudio error -9996"))
    shot("problem")
    window.session.last_error = None
    begin(talk.TWO_COMPUTERS, "fa", "en", ev.Listening(), ev.Mode("turn"), ev.PeerMsg("waiting", port=47800))
    shot("connect")
    feed(ev.PeerMsg("connected", name="Front desk"))
    shot("connected")
    begin(talk.HANDS_FREE, "fa", "en", ev.Listening(), ev.Mode("continuous"))
    shot("hands-free")
    window.pipeline = None
    window.session = app_window.ses.Session()
    for name in theme.THEMES:
        window.choose_theme(name)
        window.rail_buttons[app_window.SETTINGS].click()
        shot(f"settings-{name}")
    window.choose_theme("graphite")
    window.rail_buttons[app_window.SAVED].click()
    window.saved_items.setCurrentRow(0)
    shot("saved")
    window.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
