"""Two people can talk with no voice for one language: its translations are
shown, not spoken. No model is loaded."""

import time
from types import SimpleNamespace

from volis import events as ev
from volis.config import PythonConfig
from volis.pipeline import SpeakThread


def test_a_language_with_no_voice_is_said_once_then_shown_without_a_word(tmp_path):
    events: list = []
    speaker = SpeakThread(SimpleNamespace(root=tmp_path, pyconfig=PythonConfig(), emit=events.append, generation=0,
                                          source=SimpleNamespace(lossless=False)),
                          player=None)
    try:
        speaker.prepare("fa")
        speaker.submit("1.1", "سلام", "fa", 0.0)
        speaker.submit("1.2", "خوبی؟", "fa", 0.0)
        deadline = time.monotonic() + 5
        while sum(isinstance(e, ev.NotSpoken) for e in events) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
    finally:
        speaker.queue.put(None)
    errors = [e.message for e in events if isinstance(e, ev.Error)]
    assert errors == ["No voice is installed for Persian: translations into it are shown on the screen but not spoken."]
    assert [(e.id, e.language) for e in events if isinstance(e, ev.NotSpoken)] == [("1.1", "fa"), ("1.2", "fa")]
