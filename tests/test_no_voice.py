"""Two people can talk with no voice for one language: its translations are
shown, not spoken, and the conversation can be saved. Here: the speaking
thread, and the window. No model is loaded."""

import time
from types import SimpleNamespace

from volis import events as ev
from volis.config import PythonConfig
from volis.pipeline import SpeakThread

from test_window_p15 import ES, settle, window  # noqa: F401 - the window fixture: es > en, no voices installed


def test_a_language_with_no_voice_is_said_once_then_shown_without_a_word(tmp_path):
    events: list = []
    speaker = SpeakThread(SimpleNamespace(root=tmp_path, pyconfig=PythonConfig(), emit=events.append, generation=0),
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


def test_the_window_says_before_start_which_language_will_be_shown_not_spoken(window):
    window.speak.setChecked(True)
    window.refresh()
    assert window.voice_note.isVisibleTo(window)
    assert window.voice_note.text().startswith("No voice is installed for English")
    window.speak.setChecked(False)
    window.refresh()
    assert not window.voice_note.isVisibleTo(window)


def test_a_conversation_on_the_screen_can_be_saved_to_read_later(window, tmp_path):
    from volis import paths

    assert not window.export_button.isVisibleTo(window), "nothing to save yet"
    window.speak.setChecked(False)
    window.typed_text.setPlainText(ES)
    window.submit_typed()
    settle(window)
    window.refresh()
    assert window.export_button.isVisibleTo(window) and window.export_button.text() == "Save conversation..."
    vad = paths.vad_model_file(window.root)  # the saved settings name the speech detector's file
    vad.parent.mkdir(parents=True, exist_ok=True)
    vad.write_bytes(b"stand-in")
    window.export_to(tmp_path / "saved")
    text = (tmp_path / "saved" / "conversation.txt").read_text(encoding="utf-8")
    assert f"[typed] Spanish: {ES}" in text and "English: Where does it hurt?" in text
    assert "Saved to" in window.status.text()
