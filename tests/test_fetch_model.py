"""scripts/fetch_model.py as the developer page uses it, with Hugging Face replaced."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from volis import paths

sys.path.insert(0, str(paths.app_root() / "scripts"))
import fetch_model  # noqa: E402
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError  # noqa: E402


def error(kind):
    return kind.__new__(kind)


def info(gated=False, license="apache-2.0", files=(("model.gguf", 40), ("README.md", 2))):
    return SimpleNamespace(gated=gated, card_data=SimpleNamespace(license=license) if license else None,
                           siblings=[SimpleNamespace(rfilename=n, size=s) for n, s in files])


def api(monkeypatch, answer):
    def model_info(self, repo, files_metadata=False):
        assert files_metadata, "the page shows sizes"
        if isinstance(answer, Exception):
            raise answer
        return answer
    monkeypatch.setattr(fetch_model.HfApi, "model_info", model_info)


def run(monkeypatch, capsys, *args) -> tuple[int, str, str]:
    monkeypatch.setattr(sys, "argv", ["fetch_model.py", *args])
    code = fetch_model.main()
    out, err = capsys.readouterr()
    return code, out, err


def test_lookup_answers_with_the_files_sizes_and_licence(monkeypatch, capsys):
    api(monkeypatch, info())
    monkeypatch.setattr(fetch_model, "auth_check", lambda repo: None)
    code, out, _ = run(monkeypatch, capsys, "a/b", "--lookup")
    assert code == 0
    assert json.loads(out) == {"id": "a/b", "gated": False, "can_download": True, "license": "apache-2.0",
                               "files": [{"name": "model.gguf", "size": 40}, {"name": "README.md", "size": 2}]}


def test_lookup_of_a_gated_repo_still_lists_it_and_says_no_access(monkeypatch, capsys):
    api(monkeypatch, info(gated="manual"))

    def refused(repo):
        raise error(GatedRepoError)
    monkeypatch.setattr(fetch_model, "auth_check", refused)
    code, out, _ = run(monkeypatch, capsys, "a/b", "--lookup")
    answer = json.loads(out)
    assert code == 0 and answer["gated"] is True and answer["can_download"] is False and answer["files"]


def test_lookup_with_no_licence_listed_says_none(monkeypatch, capsys):
    api(monkeypatch, info(license=None))
    monkeypatch.setattr(fetch_model, "auth_check", lambda repo: None)
    _, out, _ = run(monkeypatch, capsys, "a/b", "--lookup")
    assert json.loads(out)["license"] is None


def test_lookup_of_no_such_repo_and_with_no_connection_are_told_apart(monkeypatch, capsys):
    api(monkeypatch, error(RepositoryNotFoundError))
    code, out, _ = run(monkeypatch, capsys, "a/b", "--lookup")
    assert code == 1 and json.loads(out)["error"] == "not_found"
    api(monkeypatch, OSError("no route"))
    code, out, _ = run(monkeypatch, capsys, "a/b", "--lookup")
    assert code == 1 and json.loads(out) == {"id": "a/b", "error": "unreachable", "detail": "no route"}


@pytest.fixture
def downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(fetch_model, "REPO", tmp_path)
    calls = []
    monkeypatch.setattr(fetch_model, "snapshot_download",
                        lambda repo, local_dir, allow_patterns: calls.append((repo, Path(local_dir), allow_patterns)))
    return calls


def test_files_names_exactly_what_is_fetched(monkeypatch, capsys, downloads, tmp_path):
    api(monkeypatch, info(files=(("a-Q4.gguf", 1), ("a-Q8.gguf", 2), ("README.md", 3))))
    code, _, _ = run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "a-Q8.gguf")
    assert code == 0
    assert downloads == [("x/a", tmp_path / "models" / "mt" / "a", ["a-Q8.gguf"])]


def test_a_file_the_repo_does_not_have_stops_it(monkeypatch, capsys, downloads):
    api(monkeypatch, info())
    code, _, err = run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "gone.gguf")
    assert code == 1 and "gone.gguf" in err and not downloads


def test_without_files_it_still_chooses_as_before(monkeypatch, capsys, downloads):
    api(monkeypatch, info(files=(("a-Q4.gguf", 1), ("a-Q8.gguf", 2), ("README.md", 3))))
    code, _, _ = run(monkeypatch, capsys, "x/a", "--role", "mt", "--include", "*Q4.gguf")
    assert code == 0 and downloads[0][2] == ["a-Q4.gguf", "README.md"]


def test_a_failed_download_is_a_message_naming_the_folder(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(fetch_model, "REPO", tmp_path)
    api(monkeypatch, info())

    def fails(*a, **k):
        raise OSError("connection dropped")
    monkeypatch.setattr(fetch_model, "snapshot_download", fails)
    code, _, err = run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "model.gguf")
    assert code == 1 and "connection dropped" in err and str(tmp_path / "models" / "mt" / "a") in err


def partial(target: Path, name: str, size: int) -> Path:
    folder = target / ".cache" / "huggingface" / "download"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"x" * size)
    return folder / name


def test_starting_again_removes_only_the_partial_files(monkeypatch, capsys, downloads, tmp_path):
    target = tmp_path / "models" / "mt" / "a"
    stale = partial(target, "abc.ffe7.incomplete", 5)
    kept = partial(target, "model.gguf.metadata", 5)
    (target / "other.gguf").write_bytes(b"GGUF")
    api(monkeypatch, info())
    run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "model.gguf")
    assert not stale.exists() and kept.exists() and (target / "other.gguf").exists()


def test_bytes_count_finished_files_and_partial_ones(tmp_path):
    (tmp_path / "done.gguf").write_bytes(b"x" * 10)
    (tmp_path / "wrong.gguf").write_bytes(b"x" * 3)
    partial(tmp_path, "abc.incomplete", 4)
    assert fetch_model.downloaded_bytes(tmp_path, {"done.gguf": 10, "wrong.gguf": 20, "none.gguf": 5}) == 14
    assert fetch_model.downloaded_bytes(tmp_path, {"done.gguf": 10}) == 10, "never over the total"


def test_the_display_name_is_written_once(monkeypatch, capsys, downloads, tmp_path):
    api(monkeypatch, info())
    target = tmp_path / "models" / "mt" / "a"
    target.mkdir(parents=True)
    run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "model.gguf", "--display-name", 'My "best" گزینه')
    settings = (target / "volis-python.toml").read_text(encoding="utf-8")
    assert 'name = "My \\"best\\" گزینه"' in settings
    run(monkeypatch, capsys, "x/a", "--role", "mt", "--files", "model.gguf", "--display-name", "Other")
    assert (target / "volis-python.toml").read_text(encoding="utf-8") == settings
