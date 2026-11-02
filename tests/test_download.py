"""The logic behind the developer page's "Download a model" section."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from volis import download, models, paths
from volis.download import RepoFile


def repo(*names, size=10):
    return [RepoFile(n, size) for n in names]


@pytest.mark.parametrize("text, expected", [
    ("openai/whisper-tiny", "openai/whisper-tiny"),
    ("  openai/whisper-tiny\n", "openai/whisper-tiny"),
    ("https://huggingface.co/openai/whisper-tiny", "openai/whisper-tiny"),
    ("https://huggingface.co/openai/whisper-tiny/", "openai/whisper-tiny"),
    ("https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/tree/main", "unsloth/gemma-3-4b-it-GGUF"),
    ("https://huggingface.co/a/b/blob/main/c.gguf?download=true", "a/b"),
    ("https://hf.co/a/b.1_2#readme", "a/b.1_2"),
    ("https://huggingface.co/datasets/a/b", None),
    ("https://huggingface.co/whisper-tiny", None),
    ("https://example.com/a/b", None),
    ("whisper-tiny", None),
    ("a/b/c", None),
    ("--login/x", None),
    ("", None),
])
def test_what_was_pasted(text, expected):
    assert download.repo_id(text) == expected


def test_several_quantized_versions_are_a_choice_with_nothing_chosen():
    files = [RepoFile("a-Q4.gguf", 40), RepoFile("a-Q8.gguf", 80), RepoFile("README.md", 1), RepoFile("mmproj-a.gguf", 5)]
    chosen = download.offer(files, "mt")
    assert [(v.label, v.size) for v in chosen.versions] == [("a-Q4", 40), ("a-Q8", 80)]
    assert download.selection(chosen) == [], "nothing until one is picked"
    assert download.selection(chosen, chosen.versions[1]) == ["a-Q8.gguf", "README.md"]


def test_a_split_version_is_one_choice_and_brings_all_its_parts():
    files = repo("a-Q4-00001-of-00002.gguf", "a-Q4-00002-of-00002.gguf", "a-Q8.gguf")
    chosen = download.offer(files, "mt")
    assert [(v.label, v.size) for v in chosen.versions] == [("a-Q4 (2 parts)", 20), ("a-Q8", 10)]
    assert download.selection(chosen, chosen.versions[0]) == ["a-Q4-00001-of-00002.gguf", "a-Q4-00002-of-00002.gguf"]


def test_a_version_in_a_folder_inside_the_repo_cannot_be_chosen():
    chosen = download.offer(repo("Q4/a.gguf", "a-Q8.gguf"), "mt")
    inside = next(v for v in chosen.versions if v.files == ["Q4/a.gguf"])
    assert not inside.usable and download.selection(chosen, inside) == []
    assert any("inside the repo" in n for n in chosen.notes)


def test_a_speech_gguf_brings_its_only_encoder():
    chosen = download.offer(repo("s-Q4.gguf", "mmproj-s.gguf", "README.md"), "asr")
    assert download.selection(chosen, chosen.versions[0]) == ["s-Q4.gguf", "mmproj-s.gguf", "README.md"]


def test_a_speech_gguf_with_several_encoders_waits_for_a_choice():
    chosen = download.offer(repo("s-Q4.gguf", "mmproj-f16.gguf", "mmproj-f32.gguf"), "asr")
    assert download.selection(chosen, chosen.versions[0]) == []
    assert download.selection(chosen, chosen.versions[0], chosen.encoders[1]) == ["s-Q4.gguf", "mmproj-f32.gguf"]


def test_a_speech_gguf_with_no_encoder_says_so():
    assert any("audio encoder" in n for n in download.offer(repo("s-Q4.gguf"), "asr").notes)


def test_a_translator_leaves_the_encoder_out():
    chosen = download.offer(repo("t-Q4.gguf", "mmproj-t.gguf"), "mt")
    assert download.selection(chosen, chosen.versions[0]) == ["t-Q4.gguf"]


def test_a_repo_with_the_whole_model_offers_no_versions():
    chosen = download.offer(repo("config.json", "model.safetensors", "a-Q4.gguf", "a-Q8.gguf", "pytorch_model.bin"), "mt")
    assert not chosen.versions and chosen.notes
    assert download.selection(chosen) == ["config.json", "model.safetensors"]


def test_the_role_changes_the_files_without_going_online():
    files = repo("voice.onnx", "voice.onnx.json", "tokens.txt", ".gitattributes")
    assert download.selection(download.offer(files, "tts")) == ["voice.onnx", "voice.onnx.json", "tokens.txt"]
    assert "voice.onnx" not in download.selection(download.offer(files, "asr"))


def test_a_repo_with_nothing_usable_says_so():
    chosen = download.offer(repo("onnx/model.onnx"), "asr")
    assert download.selection(chosen) == [] and chosen.notes


def test_what_is_here_at_its_published_size_is_not_fetched_again(tmp_path):
    (tmp_path / "here.gguf").write_bytes(b"x" * 10)
    (tmp_path / "short.gguf").write_bytes(b"x" * 3)
    files = repo("here.gguf", "short.gguf", "gone.gguf")
    assert download.to_fetch(tmp_path, files, ["here.gguf", "short.gguf", "gone.gguf"]) == {"short.gguf": 10, "gone.gguf": 10}


@pytest.mark.parametrize("name", ["", "  ", "a/b", "a\\b", "..", ".hidden", "a:b", "CON", "nul.txt", "name.", "a?"])
def test_folder_names_windows_refuses(tmp_path, name):
    assert download.folder_problem(tmp_path, "mt", name)


def test_an_ordinary_folder_name_will_do(tmp_path):
    assert download.folder_problem(tmp_path, "mt", "gemma-3-4b-it-GGUF") == ""


def test_a_folder_holding_an_engine_toml_model_is_refused_except_for_a_voice(tmp_path):
    for role in ("asr", "tts"):
        target = download.target_folder(tmp_path, role, "m")
        target.mkdir(parents=True)
        (target / "engine.toml").write_text("")
    assert str(download.target_folder(tmp_path, "asr", "m")) in download.folder_problem(tmp_path, "asr", "m")
    assert download.folder_problem(tmp_path, "tts", "m") == ""


def test_the_folder_is_under_models_for_its_role(tmp_path):
    assert download.target_folder(tmp_path, "mt", "m") == paths.mt_dir(tmp_path) / "m"
    assert download.target_folder(tmp_path, "tts", "m") == paths.tts_dir(tmp_path) / "m"


def test_available_only_with_the_environment_and_the_script(tmp_path):
    assert not download.available(tmp_path)
    (tmp_path / ".venv" / "Scripts").mkdir(parents=True)
    (tmp_path / ".venv" / "Scripts" / "python.exe").write_text("")
    assert not download.available(tmp_path), "a ready-made folder has no script"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "fetch_model.py").write_text("")
    assert download.available(tmp_path)


def test_the_download_command(tmp_path):
    command = download.download_command(tmp_path, "a/b", "mt", "b", ["x.gguf", "README.md"], " My name ")
    assert command[2:] == ["a/b", "--role", "mt", "--name", "b", "--progress", "--files", "x.gguf",
                           "--files", "README.md", "--display-name", "My name"]
    assert "--display-name" not in download.download_command(tmp_path, "a/b", "mt", "b", ["x"], "  ")


def test_reading_the_look_up():
    answer = download.read_lookup("a/b", "a warning\n" + json.dumps({
        "id": "a/b", "gated": True, "can_download": False, "license": "mit", "files": [{"name": "x", "size": 3}]}))
    assert answer.gated and not answer.can_download and answer.license == "mit"
    assert answer.files == [RepoFile("x", 3)] and download.lookup_problem(answer) == ""


def test_a_look_up_that_failed_says_what_to_do():
    missing = download.read_lookup("a/b", json.dumps({"id": "a/b", "error": "not_found"}))
    assert "a/b" in download.lookup_problem(missing)
    assert "connection" in download.lookup_problem(download.read_lookup("a/b", ""))
    assert "connection" in download.lookup_problem(download.read_lookup("a/b", "Traceback: boom"))


def test_the_steps_for_a_gated_model_name_the_page_and_the_command():
    steps = download.access_steps("a/b")
    assert "https://huggingface.co/a/b" in steps[0] and ".\\fetch-model.ps1 -Login" in steps[1] and "Look up" in steps[2]


@pytest.mark.parametrize("license, warned", [
    ("apache-2.0", False), ("mit", False), ("gemma", False), ("cc-by-nc-4.0", True), ("cc-by-nc-sa-4.0", True),
    ("Non-Commercial", True), ("research-only", True), (None, True), ([], True), (["mit", "cc-by-nc-4.0"], True),
])
def test_the_licence_warning(license, warned):
    words, warning = download.license_line(license)
    assert warning is warned and words.startswith("Licence:")
    assert "safe" not in words


def test_no_licence_listed_is_said_plainly():
    assert "not listed" in download.license_line(None)[0]


def test_not_enough_room_names_both_sizes_and_the_place(tmp_path):
    words = download.space_problem(2_000_000_000, 1_000_000_000, tmp_path)
    assert "2.0 GB" in words and "1.0 GB" in words and str(tmp_path) in words
    assert download.space_problem(1_000_000_000, 2_000_000_000, tmp_path) == ""


def test_a_folder_with_settings_keeps_its_name(tmp_path):
    assert not download.name_is_settled(tmp_path)
    (tmp_path / "volis-python.toml").write_text("")
    assert download.name_is_settled(tmp_path)


def test_reading_progress():
    assert download.read_progress("PROGRESS 52 151") == (52, 151)
    assert download.read_progress("  model.gguf") is None
    assert download.read_progress("PROGRESS a b") is None
    assert download.progress_words(52_428_800, 151_061_672) == "52 MB of 151 MB (34%)"
    assert download.progress_words(0, 0).endswith("(0%)")


def test_the_reason_a_download_failed():
    assert download.problem_in("x\nSTOP: no room\nTraceback") == "no room"
    assert download.problem_in("one\nlast line\n") == "last line"
    assert "without saying" in download.problem_in("")


def engine(directory: Path, **k):
    return models.Engine(directory.name, directory, "My model", "segment", "whisper", [], **k)


def test_finished_and_found(tmp_path):
    words, ok = download.finished_words(tmp_path, ["x"], [engine(tmp_path)])
    assert ok and "Added: My model" in words


def test_finished_but_not_seen(tmp_path):
    words, ok = download.finished_words(tmp_path, ["x"], [engine(tmp_path.parent / "other")])
    assert not ok and str(tmp_path) in words


def test_finished_but_unusable(tmp_path):
    words, ok = download.finished_words(tmp_path, ["x"], [engine(tmp_path, unusable="no processor")])
    assert not ok and "no processor" in words
    words, ok = download.finished_words(tmp_path, ["x"], [models.Failed("m", tmp_path, "bad config")])
    assert not ok and "bad config" in words


def test_finished_reports_the_version_just_fetched(tmp_path):
    old = models.Translator("m/old.gguf", tmp_path / "old.gguf", "Old", "llamacpp", False, unusable="no template")
    new = models.Translator("m/new.gguf", tmp_path / "new.gguf", "New", "llamacpp", False)
    for t in (old, new):
        t.path.write_bytes(b"GGUF")
    words, ok = download.finished_words(tmp_path, ["new.gguf"], [old, new])
    assert ok and "New" in words


def test_leftovers_go_and_nothing_else(tmp_path):
    folder = tmp_path / ".cache" / "huggingface" / "download"
    folder.mkdir(parents=True)
    (folder / "a.incomplete").write_bytes(b"x")
    (folder / "a.metadata").write_bytes(b"x")
    (tmp_path / "model.gguf").write_bytes(b"x")
    download.remove_leftovers(tmp_path)
    assert not (folder / "a.incomplete").exists() and (folder / "a.metadata").exists() and (tmp_path / "model.gguf").exists()
    download.remove_leftovers(tmp_path / "never-made")


def test_this_module_brings_no_hugging_face_library_into_volis():
    code = ("import sys, volis.download\n"
            "print([m for m in sys.modules if m.split('.')[0] in ('huggingface_hub', 'transformers', 'torch')])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=paths.app_root(), check=True)
    assert out.stdout.strip() == "[]"
