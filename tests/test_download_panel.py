"""The "Download a model" section. Qt offscreen, and a stand-in program in place of
scripts/fetch_model.py, so nothing goes online."""

import json
import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from volis import download, paths  # noqa: E402
from volis.gui.download_panel import DownloadPanel  # noqa: E402

GGUFS = {"id": "a/gemma", "gated": False, "can_download": True, "license": "apache-2.0",
         "files": [{"name": "g-Q4.gguf", "size": 2_000_000_000}, {"name": "g-Q8.gguf", "size": 4_000_000_000},
                   {"name": "README.md", "size": 100}]}
WHOLE = {"id": "a/whisper", "gated": False, "can_download": True, "license": "cc-by-nc-4.0",
         "files": [{"name": "config.json", "size": 10}, {"name": "model.safetensors", "size": 1000}]}


@pytest.fixture
def panel(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    stand_in = tmp_path / "stand_in.py"
    stand_in.write_text(
        "import os, sys, time\n"
        "mode = os.environ['STAND_IN']\n"
        "print(os.environ.get('HF_HUB_OFFLINE', 'unset'), file=sys.stderr, flush=True)\n"
        "if mode == 'answer': print(open(sys.argv[1]).read())\n"
        "if mode == 'ok': print('PROGRESS 50 100', flush=True); time.sleep(0.2); print('PROGRESS 100 100', flush=True)\n"
        "if mode == 'fail': print('STOP: the disk filled', file=sys.stderr); sys.exit(1)\n"
        "if mode == 'hang': print('PROGRESS 10 100', flush=True); time.sleep(60)\n", encoding="utf-8")
    answer = tmp_path / "answer.json"
    monkeypatch.setattr(download, "available", lambda root: True)
    calls: list[list[str]] = []

    def lookup_command(root, repo):
        calls.append(["lookup", repo])
        return [sys.executable, str(stand_in), str(answer)]

    def download_command(root, repo, role, folder, files, display_name=""):
        calls.append([repo, role, folder, *files, display_name])
        return [sys.executable, str(stand_in), str(answer)]
    monkeypatch.setattr(download, "lookup_command", lookup_command)
    monkeypatch.setattr(download, "download_command", download_command)
    rescans = []
    built = DownloadPanel(tmp_path, lambda: rescans.append(1))
    built.calls, built.rescans = calls, rescans

    def answers(what):
        answer.write_text(json.dumps(what), encoding="utf-8")
        monkeypatch.setenv("STAND_IN", "answer")
    built.answers = answers
    built.mode = lambda mode: monkeypatch.setenv("STAND_IN", mode)
    yield built
    built.shutdown()


def wait(panel, until=None) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and (until() if until else panel.busy()):
        QApplication.processEvents()
        time.sleep(0.01)
    QApplication.processEvents()
    assert time.monotonic() < deadline, "the stand-in never finished"


def look_up(panel, what, role="mt", text=None) -> None:
    panel.answers(what)
    panel.paste.setText(text or f"https://huggingface.co/{what['id']}")
    panel.role_buttons[role].setChecked(True)
    panel.look_up()
    wait(panel)


def pick(panel, words: str) -> None:
    panel.version.setCurrentIndex(next(i for i in range(panel.version.count()) if words in panel.version.itemText(i)))


def test_it_starts_closed_and_opens(panel):
    assert panel.toggle.text().startswith("▸") and panel.body.isHidden()
    panel.toggle.click()
    assert panel.toggle.text().startswith("▾") and not panel.body.isHidden()
    panel.toggle.click()
    assert panel.body.isHidden()


def test_a_download_opens_the_section(panel):
    look_up(panel, WHOLE, "asr")
    panel.mode("ok")
    panel.start_download()
    assert not panel.body.isHidden()
    wait(panel)


def test_a_ready_made_folder_only_says_why_not(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(download, "available", lambda root: False)
    built = DownloadPanel(tmp_path, lambda: None)
    assert not hasattr(built, "paste")
    assert built.may_close()
    built.shutdown()


def test_look_up_needs_a_real_id_and_a_role(panel):
    panel.paste.setText("not a model")
    panel.role_buttons["mt"].setChecked(True)
    panel._refresh()
    assert not panel.look_up_button.isEnabled()
    panel.paste.setText("a/b")
    panel._refresh()
    assert panel.look_up_button.isEnabled()


def test_several_versions_wait_for_a_choice(panel):
    look_up(panel, GGUFS)
    assert panel.calls == [["lookup", "a/gemma"]]
    assert panel.version.count() == 3 and panel.version.currentData() is None
    assert not panel.download_button.isEnabled()
    pick(panel, "g-Q4")
    assert panel.version.currentText() == "g-Q4, 2.0 GB"
    assert panel.download_button.isEnabled() and "2.0 GB" in panel.summary.text()
    assert panel.folder.text() == "gemma"


def test_changing_the_role_does_not_go_online_again(panel):
    look_up(panel, GGUFS)
    panel.role_buttons["tts"].setChecked(True)
    assert len(panel.calls) == 1 and panel.version.isHidden() and "g-Q4.gguf" in panel.files.text()


def test_the_licence_warns(panel):
    look_up(panel, WHOLE, "asr")
    assert "non-commercial" in panel.licence.text() and panel.licence.objectName() == "problem"
    look_up(panel, GGUFS)
    assert panel.licence.objectName() == "muted"


def test_a_gated_model_shows_the_steps_and_cannot_be_downloaded(panel):
    look_up(panel, {**WHOLE, "gated": True, "can_download": False}, "asr")
    assert not panel.access.isHidden()
    words = panel.access_words.text()
    assert "1." in words and "huggingface.co/a/whisper" in words and "fetch-model.ps1 -Login" in words
    assert not panel.download_button.isEnabled()
    panel.copy_login.click()
    assert QApplication.clipboard().text() == ".\\fetch-model.ps1 -Login"


def test_a_failed_look_up_says_so(panel):
    look_up(panel, {"id": "a/b", "error": "not_found"})
    assert "no model a/b" in panel.status.text() and panel.status.objectName() == "problem"
    assert panel.form_holder.isHidden()


def test_a_bad_folder_name_stops_the_download(panel):
    look_up(panel, WHOLE, "asr")
    panel.folder.setText("a:b")
    panel._refresh()
    assert not panel.download_button.isEnabled() and "folder name" in panel.summary.text()


def test_not_enough_room_stops_the_download(panel, monkeypatch):
    monkeypatch.setattr(download, "free_on", lambda target: 1000)
    look_up(panel, GGUFS)
    pick(panel, "g-Q4")
    assert not panel.download_button.isEnabled() and "Not enough room" in panel.summary.text()


def test_a_download_shows_progress_and_rescans(panel, monkeypatch, tmp_path):
    look_up(panel, WHOLE, "asr")
    panel.display_name.setText("Mine")
    panel.mode("ok")
    panel.start_download()
    assert panel.busy() and not panel.bar.isHidden() and not panel.folder.isEnabled()
    wait(panel, lambda: panel.bar.value() == 0)
    assert panel.bar.value() == 500 and "(50%)" in panel.status.text()
    wait(panel)
    assert panel.calls[-1] == ["a/whisper", "asr", "whisper", "config.json", "model.safetensors", "Mine"]
    assert panel.rescans == [1], "the lists are read again"
    assert "doesn't see a model" in panel.status.text(), "the stand-in made no files"
    assert panel.folder.isEnabled() and panel.bar.isHidden()


def test_what_a_rescan_finds_is_reported(panel, monkeypatch, tmp_path):
    from volis import models
    look_up(panel, WHOLE, "asr")
    target = paths.asr_dir(tmp_path) / "whisper"
    found = models.Engine("whisper", target, "Whisper", "segment", "whisper", [])
    monkeypatch.setattr(models, "discover", lambda directory, role: [found])
    panel.mode("ok")
    panel.start_download()
    wait(panel)
    assert panel.status.text() == "Added: Whisper. Choose it above to use it." and panel.status.objectName() == "status"


def test_the_offline_setting_is_not_passed_to_the_program(panel, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    look_up(panel, WHOLE, "asr")
    assert panel.err.strip() == "unset"
    assert os.environ["HF_HUB_OFFLINE"] == "1", "Volis keeps it"


def test_a_failed_download_gives_its_reason_and_rescans_nothing(panel):
    look_up(panel, WHOLE, "asr")
    panel.mode("fail")
    panel.start_download()
    wait(panel)
    assert panel.status.text() == "the disk filled" and panel.status.objectName() == "problem"
    assert not panel.rescans and panel.download_button.isEnabled()


def leftover(panel, tmp_path) -> Path:
    folder = paths.asr_dir(tmp_path) / "whisper" / ".cache" / "huggingface" / "download"
    folder.mkdir(parents=True)
    (folder / "x.incomplete").write_bytes(b"x")
    return folder / "x.incomplete"


def test_cancel_stops_it_and_removes_the_partial_file(panel, tmp_path):
    look_up(panel, WHOLE, "asr")
    panel.mode("hang")
    panel.start_download()
    part = leftover(panel, tmp_path)
    wait(panel, lambda: panel.bar.value() == 0)
    panel.cancel_button.click()
    wait(panel)
    assert "Cancelled" in panel.status.text() and not part.exists() and not panel.rescans


def test_closing_during_a_download_asks_first(panel, monkeypatch, tmp_path):
    look_up(panel, WHOLE, "asr")
    assert panel.may_close(), "nothing to ask about yet"
    panel.mode("hang")
    panel.start_download()
    part = leftover(panel, tmp_path)
    wait(panel, lambda: panel.bar.value() == 0)
    monkeypatch.setattr(panel, "_ask_to_close", lambda: False)
    assert not panel.may_close() and panel.busy(), "still going"
    monkeypatch.setattr(panel, "_ask_to_close", lambda: True)
    assert panel.may_close()
    panel.shutdown()
    assert not panel.busy() and not part.exists()


def test_everything_here_needs_no_download(panel, tmp_path):
    target = paths.asr_dir(tmp_path) / "whisper"
    target.mkdir(parents=True)
    (target / "config.json").write_bytes(b"x" * 10)
    (target / "model.safetensors").write_bytes(b"x" * 1000)
    look_up(panel, WHOLE, "asr")
    assert panel.summary.text() == "Everything is already here." and not panel.download_button.isEnabled()


def test_a_folder_that_has_a_name_keeps_it(panel, tmp_path):
    target = paths.asr_dir(tmp_path) / "whisper"
    target.mkdir(parents=True)
    (target / "volis-python.toml").write_text('name = "Kept"\n')
    look_up(panel, WHOLE, "asr")
    panel.display_name.setText("New")
    panel.mode("ok")
    panel.start_download()
    wait(panel)
    assert panel.calls[-1][-1] == "", "not passed on"
