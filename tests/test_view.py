"""What the window says (P14), without Qt: volis/gui/view.py."""

from volis import perf
from volis.gui import session as ses
from volis.gui import view
from volis.gui.view import Situation

GiB = 1024 ** 3


# ---------------------------------------------------------------- plain names


def test_a_folder_or_file_name_is_cleaned_into_a_readable_one():
    assert view.clean_name("gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf") == "Gemma 3 4b it"
    assert view.clean_name("aya-expanse-8b-Q4_K_M-GGUF/aya-expanse-8b-q4_k_m.gguf") == "Aya expanse 8b"
    assert view.clean_name("qwen3-1.7b-q4_k_m.gguf") == "Qwen3 1.7b"
    assert view.clean_name("whisper-large-v3-turbo") == "Whisper large v3 turbo"
    assert view.clean_name("whisper-large-v3-turbo-onnx-int8") == "Whisper large v3 turbo"
    assert view.clean_name("Qwen3-ASR-0.6B-GGUF") == "Qwen3 ASR 0.6B"
    assert view.clean_name("translategemma-4b-it.Q4_K_M.gguf") == "Translategemma 4b it"
    assert view.clean_name("cohere-transcribe-arabic-07-2026") == "Cohere transcribe arabic 07 2026"


def test_a_name_given_in_a_settings_file_wins():
    assert view.plain_name(True, "Gemma 4 E4B — good for Arabic", "gemma-4-E4B-it-GGUF/x.gguf") == (
        "Gemma 4 E4B — good for Arabic")
    assert view.plain_name(False, "Gemma-4-E4B-It", "gemma-4-E4B-it-GGUF/x.gguf") == "Gemma 4 E4B it"
    assert view.plain_name(True, "  ", "whisper-small") == "Whisper small"


def test_details_and_quantization_for_the_tooltip():
    assert view.quantization("gemma-3-4b-it-Q4_K_M.gguf") == "Q4_K_M"
    assert view.quantization("Qwen3-ASR-0.6B-Q8_0.gguf") == "Q8_0"
    assert view.quantization("model.safetensors") == ""
    assert view.details([("Folder", "x"), ("Quantization", ""), ("Size", view.size_text(2_490_000_000))]) == (
        "Folder: x\nSize: 2.5 GB")
    assert view.size_text(64_000_000) == "64 MB"


# ---------------------------------------------------------------- the big control


def session(state=ses.STOPPED, mode="continuous") -> ses.Session:
    s = ses.Session()
    s.state, s.mode = state, mode
    return s


def test_the_big_control_says_start_then_the_state_and_how_to_stop():
    stopped = view.start_control(session(), "Space", False)
    assert stopped.label == "START" and "start a conversation" in stopped.hint and "Ctrl+Enter" in stopped.hint
    assert "translate the file" in view.start_control(session(), "Space", False, file_mode=True).hint
    listening = view.start_control(session(ses.LISTENING), "Space", False)
    assert listening.label == "LISTENING" and listening.hint.startswith("Press to stop")
    assert listening.colour != stopped.colour or listening.label != stopped.label
    loading = session(ses.STARTING)
    loading.loading = "recognizer"
    assert view.start_control(loading, "Space", False).hint.startswith("Press to cancel")
    assert view.start_control(session(ses.LISTENING), "Space", False, paused=True).label == "PAUSED"
    turn = view.start_control(session(ses.LISTENING, "turn"), "Space", False)
    assert turn.label == "READY - press Space to talk"


# ---------------------------------------------------------------- reasons


def test_every_locked_control_says_to_stop_first_while_running():
    why = view.disabled_reasons(Situation(running=True))
    for name in ("recognizer", "translator", "speak", "swap", "test_speakers", "test_microphone", "pair"):
        assert why[name] == view.RUNNING, name
    assert "mode" not in why, "the mode can change while running"


def test_revision_and_hold_speech_name_what_they_need():
    assert "revise" not in view.disabled_reasons(Situation(context=True))
    assert view.disabled_reasons(Situation(context=False))["revise"] == (
        'Needs "Translate with the earlier sentences as context".')
    assert view.disabled_reasons(Situation(revise=False))["hold_speech"] == 'Needs "Revise earlier translations".'
    assert view.disabled_reasons(Situation(revise=True, speak=False))["hold_speech"] == 'Needs "Speak translations".'
    assert "hold_speech" not in view.disabled_reasons(Situation(revise=True, speak=True))
    paired = view.disabled_reasons(Situation(pair=True, revise=True))
    assert "pairing" in paired["revise"] and "pairing" in paired["hold_speech"]
    assert "Pair with another PC" in paired["mode_shared"]


def test_shared_mode_and_file_mode_explain_themselves():
    shared = view.disabled_reasons(Situation(shared=True, turn_mode=False))
    assert "each side has its own language" in shared["source_lang"] and shared["swap"] == shared["source_lang"]
    assert "Shared machine" in shared["pair"] and "Shared machine" in shared["streaming"]
    assert shared["turn_style"] == "Only when taking turns."
    file = view.disabled_reasons(Situation(file_mode=True))
    for name in ("input_device", "half_duplex", "test_microphone", "mode"):
        assert "file" in file[name]
    assert "source_lang" not in file and "swap" not in file


def test_nothing_is_greyed_out_in_the_ordinary_case():
    assert view.disabled_reasons(Situation(revise=True)) == {}


# ---------------------------------------------------------------- the warning


def verdict(need_gpu: float, room_gpu: float = 6.0, need_ram: float = 0.5):
    sample = perf.Sample(0.0, perf.Gpu("RTX", int((8 - room_gpu) * GiB), 8 * GiB, 5, 50, 1000, 20) if room_gpu else None,
                         32 * GiB, 8 * GiB, GiB, 5.0, 2.0)
    return perf.verdict([perf.Estimate("translator", "t", "cuda", int(need_gpu * GiB), 0, False),
                         perf.Estimate("voice", "v", "cpu", 0, int(need_ram * GiB), False)], sample)


def test_no_warning_when_the_models_fit_and_the_numbers_are_in_the_tooltip():
    w = view.fit_warning(verdict(3.0))
    assert w.text == "" and "graphics memory" in w.detail and "hasn't been run" in w.detail


def test_a_plain_sentence_when_they_will_not_fit_or_only_just():
    assert "won't fit" in view.fit_warning(verdict(9.0)).text and "smaller translator" in view.fit_warning(verdict(9.0)).text
    assert "only just fit" in view.fit_warning(verdict(5.7)).text
    assert "NVIDIA graphics card" in view.fit_warning(verdict(3.0, room_gpu=0)).text


def test_too_slow_is_said_only_when_it_was_measured_here():
    fast = {"runs": 2, "asr_rtf": 0.3, "translate_ms": 600, "first_audio_ms": 900}
    assert view.fit_warning(verdict(3.0), fast).text == ""
    assert "Measured here in 2 run(s)" in view.fit_warning(verdict(3.0), fast).detail
    slow = view.fit_warning(verdict(3.0), dict(fast, translate_ms=6400))
    assert "about 6 seconds a sentence" in slow.text
    assert "slower than the speech itself" in view.fit_warning(verdict(3.0), dict(fast, asr_rtf=1.4)).text
    assert "won't fit" in view.fit_warning(verdict(9.0), dict(fast, translate_ms=6400)).text, "not fitting comes first"


# ---------------------------------------------------------------- the bar, the text size, the test sentence


def test_the_bar_shown_while_running_names_the_languages_and_the_models():
    assert view.conversation_bar("Spanish", "English", "Whisper turbo", "Gemma 3 4B") == (
        "Spanish  →  English      Whisper turbo  ·  Gemma 3 4B")
    assert view.conversation_bar("", "", "", "Gemma", shared=True, sides=("English", "Arabic")).startswith(
        "English  ⇄  Arabic")


def test_the_text_size_steps_up_and_down_and_stops_at_the_ends():
    assert view.text_size_step(12, True) == 14 and view.text_size_step(12, False) == 11
    assert view.text_size_step(32, True) == 32 and view.text_size_step(9, False) == 9
    assert view.text_size_step(13, True) == 14, "a size not in the list still steps"


def test_a_test_sentence_for_each_language_and_its_varieties():
    assert view.test_sentence("es-MX") == view.test_sentence("es") != ""
    assert view.test_sentence("ar-IQ").startswith("هذا")
    assert view.test_sentence("xx") == ""
    from volis import varieties

    for tag in {varieties.language_of(v.tag) for v in varieties.TABLE}:
        assert view.test_sentence(tag), tag
