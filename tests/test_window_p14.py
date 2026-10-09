"""The window for non-technical users (P14): what is shown, folded away,
remembered and explained. Qt offscreen, a temporary models folder, no model
loaded, no settings written."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from volis import audio  # noqa: E402
from volis import events as ev  # noqa: E402
from volis.gui import view  # noqa: E402

from test_models import CARD, PARAKEET, PARAKEET_FILES, QWEN, hf_folder, model, write_gguf  # noqa: E402


@pytest.fixture
def window(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from volis import paths
    from volis.config import Config, PythonConfig
    from volis.gui.window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio, "list_input_devices", lambda: [audio.Device("Mic", True, None)])
    monkeypatch.setattr(audio, "list_output_devices", lambda: [audio.Device("Speakers", True, None)])
    monkeypatch.setattr(paths, "performance_file", lambda root: tmp_path / "performance.json")
    asr = tmp_path / "models" / "asr"
    model(asr, "parakeet-tdt-0.6b-v3-onnx-int8", PARAKEET, PARAKEET_FILES)
    hf_folder(asr, "whisper-large-v3-turbo-es", README__md=CARD,  # the model card says: Spanish
              volis_python__toml='name = "Whisper turbo — Spanish"\n')
    hf_folder(asr, "whisper-large-v3-turbo")
    mt = tmp_path / "models" / "mt"
    (mt / "gemma-3-4b-it-GGUF").mkdir(parents=True)
    write_gguf(mt / "gemma-3-4b-it-GGUF" / "gemma-3-4b-it-Q4_K_M.gguf", dict(QWEN, **{"general.name": "Gemma-3-4B-It"}))
    (tmp_path / "models" / "tts").mkdir()
    config = Config()
    config.languages.source, config.languages.target = "es", "en"
    w = MainWindow(tmp_path, config, PythonConfig())
    saved = []
    w.save = lambda: saved.append(True)  # a test never writes settings
    w.saved = saved
    w.show()
    yield w
    w.pipeline = None
    w.perf_panel.sampler.stop()
    w.close()


def texts(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def run(window) -> None:
    """As if Start had been pressed and the models had loaded."""
    window.session.begin("es", "en", False, True, False)
    window.pipeline = object()
    window.session.apply(ev.Listening())
    window.refresh()


def test_only_the_basics_show_and_advanced_starts_closed_and_is_remembered(window):
    for basic in (window.source_lang, window.target_lang, window.swap_button, window.recognizer, window.translator,
                  window.input_device, window.output_device, window.test_microphone, window.test_speakers,
                  window.speak, window.mode_turn, window.mode_continuous, window.mode_shared):
        assert basic.isVisibleTo(window), basic
    for advanced in (window.half_duplex, window.diacritize, window.streaming, window.use_context,
                     window.revise, window.hold_speech, window.hold_fragments, window.glossary, window.pair):
        assert not advanced.isVisibleTo(window), advanced.text() if hasattr(advanced, "text") else advanced
    window.advanced_toggle.setChecked(True)
    assert window.half_duplex.isVisibleTo(window) and window.pair.isVisibleTo(window)
    assert window.pyconfig.window.advanced_open is False, "the fixture's save is a stand-in"
    assert window.saved, "opening Advanced is saved"


def test_advanced_opens_as_the_settings_left_it(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from volis import paths
    from volis.config import Config, PythonConfig
    from volis.gui.window import MainWindow

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(audio, "list_input_devices", lambda: [])
    monkeypatch.setattr(audio, "list_output_devices", lambda: [])
    monkeypatch.setattr(paths, "performance_file", lambda root: tmp_path / "performance.json")
    py = PythonConfig()
    py.window.advanced_open, py.window.text_size = True, 18
    w = MainWindow(tmp_path, Config(), py)
    w.save = lambda: None
    w.show()
    try:
        assert w.advanced_toggle.isChecked() and w.half_duplex.isVisibleTo(w)
        assert w.table.font().pointSize() == 18
    finally:
        w.perf_panel.sampler.stop()
        w.close()


def test_the_lists_show_plain_names_and_keep_the_details_in_a_tooltip(window):
    from PySide6.QtCore import Qt

    names = texts(window.recognizer)
    assert "Whisper turbo — Spanish" in names, "the name its settings file gives"
    assert "Whisper large v3 turbo" in names, "a cleaned-up folder name"
    assert not any("transformers" in n or "GGUF" in n or "safetensors" in n for n in names)
    index = window.recognizer.findData("whisper-large-v3-turbo")
    tip = window.recognizer.itemData(index, Qt.ItemDataRole.ToolTipRole)
    assert "Folder: whisper-large-v3-turbo" in tip and "Runs with: transformers" in tip
    assert texts(window.translator) == ["Gemma 3 4b it"]
    tip = window.translator.itemData(0, Qt.ItemDataRole.ToolTipRole)
    assert "File: gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf" in tip and "Compression: Q4_K_M" in tip


def test_swap_exchanges_the_languages_and_reranks_the_recognizers(window):
    assert (window.source_lang.currentData(), window.target_lang.currentData()) == ("es", "en")
    window.swap_button.click()
    assert (window.source_lang.currentData(), window.target_lang.currentData()) == ("en", "es")
    assert (window.config.languages.source, window.config.languages.target) == ("en", "es")
    assert "Whisper turbo — Spanish" not in texts(window.recognizer), "a Spanish-only model doesn't hear English"
    window.swap_button.click()
    assert window.source_lang.currentData() == "es" and "Whisper turbo — Spanish" in texts(window.recognizer)


def test_the_big_control_is_the_state_and_ctrl_enter_presses_it(window):
    assert window.start_state.text() == "START" and "Ctrl+Enter" in window.start_hint.text()
    assert window.start_button.minimumHeight() >= 60
    run(window)
    assert window.start_state.text() != "START" and window.start_hint.text().startswith("Press to stop")


def test_while_running_the_settings_fold_into_a_bar_and_come_back(window):
    assert window.settings_box.isVisibleTo(window) and not window.show_settings.isVisibleTo(window)
    run(window)
    assert not window.settings_box.isVisibleTo(window)
    assert window.bar_label.text().startswith("Spanish  →  English") and "Gemma 3 4b it" in window.bar_label.text()
    window.show_settings.setChecked(True)
    assert window.settings_box.isVisibleTo(window), "the Settings button unfolds them"
    assert not window.recognizer.isEnabled() and window.recognizer.toolTip() == view.RUNNING
    window.pipeline = None
    window.session.apply(ev.Stopped())
    window.refresh()
    assert window.settings_box.isVisibleTo(window) and window.bar_label.text() == ""
    assert not window.show_settings.isChecked()


def test_the_text_size_buttons_change_the_transcript_and_are_remembered(window):
    before = window.table.font().pointSize()
    window.larger.click()
    assert window.table.font().pointSize() == view.text_size_step(before, True) == window.pyconfig.window.text_size
    window.smaller.click()
    window.smaller.click()
    assert window.table.font().pointSize() == view.text_size_step(before, False)
    assert window.larger.isVisibleTo(window), "kept in the bar, running or not"


def test_every_greyed_out_control_says_why_as_a_tooltip_and_beside_it(window):
    window.advanced_toggle.setChecked(True)
    window.revise.setChecked(False)
    window.refresh()
    assert not window.hold_speech.isEnabled()
    assert window.hold_speech.toolTip() == 'Needs "Revise earlier translations".'
    label = window.reason_labels["hold_speech"]
    assert label.isVisibleTo(window) and label.text() == 'Needs "Revise earlier translations".'
    window.revise.setChecked(True)
    window.refresh()
    assert window.hold_speech.isEnabled() and not label.isVisibleTo(window)
    assert "Wait" in window.hold_speech.text() and "2 s" in window.hold_speech.toolTip(), "its own tooltip is back"
    window.use_context.setChecked(False)
    window.refresh()
    assert window.reason_labels["revise"].text() == 'Needs "Translate with the earlier sentences as context".'


def test_shared_mode_hides_swap_and_explains_the_languages(window):
    window.mode_shared.setChecked(True)
    window.refresh()
    assert not window.swap_button.isVisibleTo(window)
    assert not window.source_lang.isEnabled()
    assert "each side has its own language" in window.reason_labels["languages"].text()


def test_the_test_buttons_are_off_while_running_and_report_into_the_window(window, monkeypatch):
    from volis.gui import devicetest

    said = []
    monkeypatch.setattr(devicetest, "speakers", lambda voices, language, device, say: say("Played the test."))
    window.run_speaker_test()
    for _ in range(50):  # the test's thread
        if not window._test_running:
            break
        import time

        time.sleep(0.02)
    window.tick()
    assert window.test_status.text() == "Played the test." and window.test_status.isVisibleTo(window)
    run(window)
    window.show_settings.setChecked(True)
    assert not window.test_speakers.isEnabled() and not window.test_microphone.isEnabled()
    assert window.test_speakers.toolTip() == view.RUNNING
    monkeypatch.setattr(devicetest, "speakers", lambda *a: said.append("ran"))
    window.run_speaker_test()
    assert said == [], "nothing runs while a conversation does"


def test_a_warning_shows_before_start_when_the_models_will_not_fit(window, monkeypatch):
    from volis import perf

    GiB = 1024 ** 3
    small = perf.Sample(0.0, perf.Gpu("RTX", 7 * GiB, 8 * GiB, 5, 50, 1000, 20), 32 * GiB, 8 * GiB, GiB, 5.0, 2.0)
    monkeypatch.setattr(window.perf_panel.sampler, "latest", lambda: small)
    monkeypatch.setattr(perf, "estimate_translator",
                        lambda entry, measured, gpu: perf.Estimate("translator", entry.id, "cuda", 5 * GiB, 0, False))
    window.update_fit_warning()
    assert window.fit_warning.isVisibleTo(window) and "won't fit" in window.fit_warning.text()
    assert "graphics memory" in window.fit_warning.toolTip()
    roomy = perf.Sample(0.0, perf.Gpu("RTX", 0, 24 * GiB, 5, 50, 1000, 20), 64 * GiB, 8 * GiB, GiB, 5.0, 2.0)
    monkeypatch.setattr(window.perf_panel.sampler, "latest", lambda: roomy)
    window.update_fit_warning()
    assert not window.fit_warning.isVisibleTo(window)
