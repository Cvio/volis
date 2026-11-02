"""What the developer page's "Download a model" section decides: reading a link,
which files a repo offers for a role, what is already here, and what to tell
the person. No Qt, and no Hugging Face library: importing them here would bring
network code into the app. The downloading is scripts/fetch_model.py, a program
of its own that shares `choose` and `remove_leftovers` with this module."""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import models, paths

ROLES = {"asr": "Recognizer", "mt": "Translator", "tts": "Voice"}
MARGIN = 1.1  # room to leave on the disk, as fetch-models does

# Never wanted: other frameworks' weights and exports.
ALWAYS_SKIP = ["*.h5", "*.msgpack", "*.ot", "*.onnx", "*.onnx_data", "onnx/*", "flax_model*", "tf_model*",
               "*.mlmodel", "*.tflite", "coreml/*", "openvino/*",
               # training logs some repos publish
               "runs/*", "*.tfevents.*"]
DUPLICATE_WEIGHTS = ["*.bin", "*.pt", "*.pth", "*.ckpt"]
DOCUMENTS = ("README.md", "LICENSE", "LICENSE.md")


def _is_encoder(name: str) -> bool:
    return os.path.basename(name).lower().startswith("mmproj")


def _has_whole_model(files: list[str]) -> bool:
    """config.json and its weights: any .gguf beside them is a copy for another program."""
    return "config.json" in files and any(f in ("model.safetensors", "pytorch_model.bin")
                                          or f.startswith(("model-0", "pytorch_model-0")) for f in files)


def choose(files: list[str], role: str, include: list[str]) -> list[str]:
    """The files to download from a repo's file list."""
    if role == "tts":  # a voice: everything it was published with (the .onnx is the model)
        return [f for f in files if f != ".gitattributes"]
    ggufs = [f for f in files if f.lower().endswith(".gguf")]
    # A repo that holds the whole model (config.json and its weights) and some .gguf copies
    # beside it, like google/madlad400-3b-mt: the model is what is wanted. Those copies are
    # often for another program and volis can't run them. Naming a .gguf with -Include still
    # gets that file.
    if ggufs and _has_whole_model(files) and not any(fnmatch.fnmatch(f, p) for f in ggufs for p in include):
        print(f"note: this repo has the full model and {len(ggufs)} .gguf copies of it. Downloading the full "
              "model; the .gguf files are left out.")
        files = [f for f in files if f not in ggufs]
        ggufs = []
    if ggufs:
        ggufs_models = [f for f in ggufs if not _is_encoder(f)]
        if include:
            wanted = [f for f in ggufs if any(fnmatch.fnmatch(f, p) for p in include)]
        elif len(ggufs_models) == 1:
            wanted = ggufs_models
        else:
            names = "\n  ".join(ggufs_models)
            raise SystemExit(
                f"STOP: this repo has {len(ggufs_models)} .gguf files. Pick one with -Include, e.g. "
                f'-Include "*Q4_K_M.gguf":\n  {names}'
            )
        if role == "asr" and not any(_is_encoder(f) for f in wanted):
            mmproj = [f for f in ggufs if _is_encoder(f)]
            if mmproj:
                print(f"note: a speech model also needs its audio encoder; add -Include for one of: {mmproj}")
        if not wanted:
            raise SystemExit(f"STOP: nothing in the repo matches {include}")
        return wanted + [f for f in files if f in DOCUMENTS]

    skip = list(ALWAYS_SKIP)
    if any(f.endswith(".safetensors") for f in files):
        skip += DUPLICATE_WEIGHTS  # the same weights twice; take safetensors
    chosen = [f for f in files if not any(fnmatch.fnmatch(f, p) for p in skip)]
    if include:
        chosen = [f for f in chosen if any(fnmatch.fnmatch(f, p) for p in include)] + [
            f for f in chosen if f.endswith(".json") or f == "README.md"
        ]
    return sorted(set(chosen))


def remove_leftovers(target: Path) -> None:
    """A stopped download's partial files. huggingface_hub starts a stopped file
    again under a new name and never removes the old one."""
    for part in (target / ".cache" / "huggingface" / "download").glob("*.incomplete"):
        try:
            part.unlink()
        except OSError:  # another download of this model has it open
            pass


# ---------------------------------------------------------------- what was pasted


_REPO_ID = re.compile(r"[A-Za-z0-9][\w.-]*/[A-Za-z0-9][\w.-]*")
_LINK = re.compile(r"https?://(?:www\.)?(?:huggingface\.co|hf\.co)/([^?#]+)", re.I)
_NOT_MODELS = ("datasets", "spaces", "docs", "blog", "organizations", "settings")


def repo_id(text: str) -> str | None:
    """The `owner/name` in what was pasted: an id or a link to the model, or to a
    page inside it. None if it is neither."""
    text = text.strip()
    if link := _LINK.fullmatch(text.split("?")[0].split("#")[0]):
        parts = link.group(1).strip("/").split("/")
        if len(parts) < 2 or parts[0].lower() in _NOT_MODELS:
            return None
        text = "/".join(parts[:2])
    return text if _REPO_ID.fullmatch(text) else None


_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def folder_problem(root: Path, role: str, name: str) -> str:
    """Why this folder name won't do, or "" if it will."""
    if not name.strip():
        return "Give the folder a name."
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.startswith(".") or name != name.strip(" .") \
            or name.split(".")[0].lower() in _RESERVED:
        return f'"{name}" can\'t be a folder name on Windows.'
    target = target_folder(root, role, name)
    if role != "tts" and (target / "engine.toml").is_file():
        return f"{target} holds a model of another kind. Give this one its own folder name."
    return ""


def target_folder(root: Path, role: str, name: str) -> Path:
    directory = {"asr": paths.asr_dir, "mt": paths.mt_dir, "tts": paths.tts_dir}[role]
    return directory(root) / name


# ---------------------------------------------------------------- the downloader


def available(root: Path) -> bool:
    """Only from the source folder: a ready-made folder has neither of these."""
    return _python(root).is_file() and _script(root).is_file()


def _python(root: Path) -> Path:
    return root / ".venv" / "Scripts" / "python.exe"


def _script(root: Path) -> Path:
    return root / "scripts" / "fetch_model.py"


def lookup_command(root: Path, repo: str) -> list[str]:
    return [str(_python(root)), str(_script(root)), repo, "--lookup"]


def download_command(root: Path, repo: str, role: str, folder: str, files: list[str], display_name: str = "") -> list[str]:
    command = [str(_python(root)), str(_script(root)), repo, "--role", role, "--name", folder, "--progress"]
    for name in files:
        command += ["--files", name]
    if display_name.strip():
        command += ["--display-name", display_name.strip()]
    return command


def login_command() -> str:
    return ".\\fetch-model.ps1 -Login"


@dataclass
class RepoFile:
    name: str
    size: int


@dataclass
class Lookup:
    repo: str
    error: str = ""  # "not_found" | "unreachable"
    detail: str = ""
    gated: bool = False
    can_download: bool = True
    license: str | list[str] | None = None
    files: list[RepoFile] = field(default_factory=list)


def read_lookup(repo: str, output: str) -> Lookup:
    """The answer `fetch_model.py --lookup` printed: its last line of output."""
    lines = output.strip().splitlines()
    try:
        answer = json.loads(lines[-1])
    except (IndexError, ValueError):
        return Lookup(repo, error="unreachable", detail=output.strip()[-300:] or "the look-up gave no answer")
    return Lookup(repo, error=answer.get("error", ""), detail=answer.get("detail", ""),
                  gated=bool(answer.get("gated")), can_download=bool(answer.get("can_download", True)),
                  license=answer.get("license"),
                  files=[RepoFile(f["name"], f["size"]) for f in answer.get("files", [])])


def lookup_problem(answer: Lookup) -> str:
    if answer.error == "not_found":
        return (f"There is no model {answer.repo} on Hugging Face. Check the name. "
                f"If it is private, run {login_command()} in PowerShell first.")
    if answer.error:
        return f"Couldn't reach Hugging Face. Check the connection and try again. ({answer.detail[:300]})"
    return ""


def access_steps(repo: str) -> list[str]:
    """What to do about a gated model the saved token can't open."""
    return [f"Open https://huggingface.co/{repo} in your browser, sign in, and accept its terms.",
            f"Run this once in PowerShell, in the Volis folder: {login_command()}",
            "Press Look up again."]


_NON_COMMERCIAL = re.compile(r"(^|-)nc(-|$)|non-?commercial|research", re.I)


def license_line(license: str | list[str] | None) -> tuple[str, bool]:
    """(the words to show, whether they are a warning). What Hugging Face lists can
    be missing or wrong, so nothing here says a model is safe to use."""
    names = [license] if isinstance(license, str) else list(license or [])
    if not names:
        return "Licence: not listed. Read the model's page before giving it to anyone.", True
    words = ", ".join(names)
    if any(_NON_COMMERCIAL.search(name) for name in names):
        return f"Licence: {words}. This looks like non-commercial use only: read it before giving this to a customer.", True
    return f"Licence: {words}, as listed on Hugging Face.", False


# ---------------------------------------------------------------- what a repo offers


@dataclass
class Version:
    """One way to have the model: a .gguf, or all the parts of a split one."""

    label: str
    files: list[str]
    size: int
    usable: bool = True  # False: in a folder inside the repo, where Volis doesn't look


@dataclass
class Offer:
    versions: list[Version] = field(default_factory=list)  # to choose from; empty when there is no choice to make
    encoders: list[RepoFile] = field(default_factory=list)  # a speech .gguf's audio encoder, to choose from
    plain: list[str] = field(default_factory=list)  # always fetched
    notes: list[str] = field(default_factory=list)


_SPLIT = re.compile(r"-\d{5}-of-\d{5}\.gguf$", re.I)


def _versions(ggufs: list[RepoFile]) -> list[Version]:
    groups: dict[str, list[RepoFile]] = {}
    for f in ggufs:
        groups.setdefault(_SPLIT.sub("", f.name) if _SPLIT.search(f.name) else f.name, []).append(f)
    versions = []
    for key, parts in sorted(groups.items()):
        label = os.path.basename(key).removesuffix(".gguf")
        if len(parts) > 1:
            label += f" ({len(parts)} parts)"
        versions.append(Version(label, sorted(p.name for p in parts), sum(p.size for p in parts),
                                usable="/" not in key))
    return versions


def offer(files: list[RepoFile], role: str) -> Offer:
    """What this repo offers for this role, by the rules of `choose`. Asks nothing
    of the network, so changing the role doesn't look the repo up again."""
    names = [f.name for f in files]
    ggufs = [f for f in files if f.name.lower().endswith(".gguf")]
    result = Offer()
    if role == "tts":
        result.plain = choose(names, role, [])
    elif ggufs and _has_whole_model(names):
        result.plain = choose([n for n in names if not n.lower().endswith(".gguf")], role, [])
        result.notes.append(f"This repo has the full model and {len(ggufs)} .gguf copies of it. "
                            "The full model will be downloaded.")
    elif ggufs:
        result.versions = _versions([f for f in ggufs if not _is_encoder(f.name)])
        result.plain = [n for n in names if n in DOCUMENTS]
        if role == "asr":
            result.encoders = [f for f in ggufs if _is_encoder(f.name)]
            if not result.encoders:
                result.notes.append("A speech model in .gguf form needs an audio encoder (mmproj), "
                                    "and this repo has none. It won't run without one.")
    else:
        result.plain = choose(names, role, [])
    if any(not v.usable for v in result.versions):
        result.notes.append("Files in a folder inside the repo can't be chosen: "
                            "Volis only looks at the top of a model's folder.")
    if not result.plain and not result.versions:
        result.notes.append("This repo has nothing Volis could use for this role.")
    return result


def selection(chosen: Offer, version: Version | None = None, encoder: RepoFile | None = None) -> list[str]:
    """The files to fetch, or [] while a choice is still to be made."""
    if chosen.versions and (version is None or not version.usable):
        return []
    if len(chosen.encoders) > 1 and encoder is None:
        return []
    if len(chosen.encoders) == 1:
        encoder = chosen.encoders[0]
    wanted = list(version.files) if version else []
    if encoder is not None:
        wanted.append(encoder.name)
    return wanted + chosen.plain


def to_fetch(target: Path, files: list[RepoFile], wanted: list[str]) -> dict[str, int]:
    """Of the wanted files, those not here at their published size, with their sizes."""
    sizes = {f.name: f.size for f in files}
    return {name: sizes[name] for name in wanted
            if not (target / name).is_file() or (sizes[name] and (target / name).stat().st_size != sizes[name])}


def space_problem(need: int, free: int, target: Path) -> str:
    if need * MARGIN > free:
        return f"Not enough room: this needs {size_words(need)}, and the drive holding {target} has {size_words(free)} free."
    return ""


def size_words(size: int) -> str:
    if size >= 1e9:
        return f"{size / 1e9:.1f} GB"
    return f"{size / 1e6:.0f} MB" if size >= 1e6 else f"{size / 1e3:.0f} KB"


def free_on(target: Path) -> int:
    """Free bytes on the drive this folder is on, or will be on."""
    place = target
    while not place.exists() and place != place.parent:
        place = place.parent
    return shutil.disk_usage(place).free


def name_is_settled(target: Path) -> bool:
    """The folder has a settings file already, which a download never changes.
    It names every version in the folder, so the name box has nothing to do."""
    return (target / "volis-python.toml").exists() or (target / "engine.toml").exists()


# ---------------------------------------------------------------- while and after


def read_progress(line: str) -> tuple[int, int] | None:
    parts = line.split()
    if len(parts) == 3 and parts[0] == "PROGRESS" and parts[1].isdigit() and parts[2].isdigit():
        return int(parts[1]), int(parts[2])
    return None


def progress_words(done: int, total: int) -> str:
    percent = done * 100 // total if total else 0
    return f"{size_words(done)} of {size_words(total)} ({percent}%)"


def problem_in(output: str) -> str:
    """The reason a failed download printed; its last STOP line if it has one."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    stops = [line for line in lines if line.startswith("STOP:")]
    if stops:
        return stops[-1].removeprefix("STOP:").strip()
    return lines[-1] if lines else "The download stopped without saying why."


def finished_words(target: Path, wanted: list[str], found: list) -> tuple[str, bool]:
    """(what to say once the files are here, whether it worked), from what a
    rescan found. This finds and reads the model; it doesn't load or run it."""
    here = [entry for entry in found if _location(entry) == target or target in _location(entry).parents]
    named = [entry for entry in here if not _location(entry).is_file() or _location(entry).name in wanted]
    if not named:
        return f"The files arrived, but Volis doesn't see a model in {target}.", False
    entry = named[0]
    if isinstance(entry, models.Failed):
        return f"The files arrived, but Volis can't use them: {entry.error}", False
    if not entry.enabled():
        missing = entry.missing if isinstance(entry, models.Translator) else entry.missing_files()
        why = entry.unusable or ("missing " + ", ".join(missing))
        return f"{entry.name} arrived, but Volis can't use it: {why}", False
    return f"Added: {entry.name}. Choose it above to use it.", True


def _location(entry) -> Path:
    return entry.path if isinstance(entry, models.Translator) else entry.dir
