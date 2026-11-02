"""Download a Hugging Face model into models/asr/, models/mt/ or models/tts/. Run through
fetch-model.ps1. A development tool: it uses the internet, and a ready-made
folder doesn't have it.

The equivalent of `hf download <id> --local-dir models/<role>/<name>` with a
chosen file list, done through huggingface_hub's Python API so the file list
can be decided from the repo's contents first.

The developer page in the window runs this too, as a program of its own: --lookup
answers in JSON, --files names exactly what to fetch, and --progress reports the
bytes as `PROGRESS <done> <total>` lines.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The token and download cache stay in the repo, never in the user profile,
# and never in the app's own cache/ (which is shipped).
os.environ["HF_HOME"] = str(REPO / ".uv" / "hf")
os.environ.pop("HF_HUB_OFFLINE", None)
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
if "--progress" in sys.argv:  # Xet writes a file nearly all at once, so there would be nothing to measure
    os.environ["HF_HUB_DISABLE_XET"] = "1"

from huggingface_hub import HfApi, auth_check, login, snapshot_download  # noqa: E402
from huggingface_hub.errors import GatedRepoError, RepositoryNotFoundError  # noqa: E402

sys.path.insert(0, str(REPO))
from volis.download import choose, remove_leftovers  # noqa: E402

def piper_engine(name: str, language: str, model: str, variety: str = "", note: str = "") -> str:
    """The engine.toml of a Piper voice."""
    variety_line = f'varieties = ["{variety}"]   # the dialect this voice speaks\n' if variety else ""
    return (f'name = "{name}"\nkind = "segment"\nbackend = "vits"\nlanguages = ["{language}"]\n{variety_line}\n'
            "# espeak-ng does the pronunciation for Piper voices. It is a directory, so it\n"
            '# cannot be declared under [files].\ndata_dir = "espeak-ng-data"\n\n[files]\n'
            f'{note}model  = "{model}"\ntokens = "tokens.txt"\n')


RAW_PIPER = ("# The download is a raw Piper model. sherpa-onnx needs a few fields inside the model file,\n"
             "# so this is a copy with them added; the .onnx beside it is the original, untouched.\n")


def convert_piper(folder: Path, language: str = "") -> None:
    """A voice as Piper publishes it (X.onnx + X.onnx.json) lacks three things
    sherpa-onnx needs: tokens.txt, a few fields inside the model file, and
    espeak-ng-data. Writes tokens.txt and X.sherpa.onnx (the original is left
    untouched), and copies espeak-ng-data from another installed voice."""
    for config_path in folder.glob("*.onnx.json"):
        model = config_path.with_suffix("")  # X.onnx
        out = model.with_name(model.stem + ".sherpa.onnx")
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not (folder / "tokens.txt").exists():
            with open(folder / "tokens.txt", "w", encoding="utf-8", newline="\n") as f:
                for symbol, ids in config["phoneme_id_map"].items():
                    f.write(f"{symbol} {ids[0]}\n")
        if not out.exists():
            # ONNX is protobuf: ModelProto.metadata_props is repeated field 14,
            # and appending entries to the file adds them to the list.
            meta = {"model_type": "vits", "comment": "piper",
                    # sherpa-onnx refuses a model with no language named; any name will do
                    "language": language or (config.get("language") or {}).get("name_english")
                    or config["espeak"]["voice"],
                    "voice": config["espeak"]["voice"], "has_espeak": 1, "n_speakers": config["num_speakers"],
                    "sample_rate": config["audio"]["sample_rate"]}
            out.write_bytes(model.read_bytes() + b"".join(_metadata_entry(k, v) for k, v in meta.items()))
            print(f"    wrote {out} and tokens.txt")
    if not (folder / "espeak-ng-data").is_dir():
        donors = [p for p in folder.parent.glob("*/espeak-ng-data") if (p / "phontab").is_file()]
        if not donors:
            raise SystemExit(f"STOP: {folder} needs espeak-ng-data, and no other voice in {folder.parent} has it to "
                             "copy. Fetch a sherpa-onnx Piper voice first (.\\fetch-models.ps1 -Only lessac).")
        shutil.copytree(donors[0], folder / "espeak-ng-data")
        print(f"    copied espeak-ng-data from {donors[0].parent.name}")


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _metadata_entry(key: str, value) -> bytes:
    k, v = key.encode(), str(value).encode()
    body = b"\x0a" + _varint(len(k)) + k + b"\x12" + _varint(len(v)) + v
    return b"\x72" + _varint(len(body)) + body


def finish_voice(folder: Path, display_name: str = "") -> None:
    """After a voice is downloaded: convert it if it is a raw Piper model, and
    write an engine.toml if it has none. The language is taken from the
    voice's own .onnx.json; no variety is declared."""
    raw = not (folder / "tokens.txt").is_file()
    if raw:
        convert_piper(folder)
    if (folder / "engine.toml").exists():
        return
    configs = sorted(folder.glob("*.onnx.json"))
    models = sorted(folder.glob("*.sherpa.onnx")) or sorted(folder.glob("*.onnx"))
    if not models:
        raise SystemExit(f"STOP: {folder} has no .onnx file, so it is not a Piper voice volis can load")
    language = ""
    if configs:
        config = json.loads(configs[0].read_text(encoding="utf-8"))
        language = (config.get("language") or {}).get("family") or str(config.get("espeak", {}).get("voice", ""))[:2]
    (folder / "engine.toml").write_text(
        piper_engine(display_name or folder.name, language, models[0].name, note=RAW_PIPER if raw else ""), encoding="utf-8",
        newline="\n")
    print(f"wrote {folder / 'engine.toml'}: check its name and languages"
          + ("" if language else ' (languages is empty: set it, e.g. ["ar"])'))


def lookup(repo: str) -> dict:
    """What the window needs to know about a repo, downloading nothing. A gated
    repo's file list is still readable; `can_download` says if the token gets in."""
    try:
        info = HfApi().model_info(repo, files_metadata=True)
    except RepositoryNotFoundError:
        return {"id": repo, "error": "not_found"}
    except GatedRepoError:
        return {"id": repo, "gated": True, "can_download": False, "license": None, "files": []}
    except Exception as e:  # no connection, a server error: the window says so
        return {"id": repo, "error": "unreachable", "detail": str(e)}
    try:
        auth_check(repo)
        can_download = True
    except GatedRepoError:
        can_download = False
    except Exception as e:
        return {"id": repo, "error": "unreachable", "detail": str(e)}
    return {"id": repo, "gated": bool(info.gated), "can_download": can_download,
            "license": getattr(info.card_data, "license", None) if info.card_data else None,
            "files": [{"name": s.rfilename, "size": s.size or 0} for s in info.siblings or []]}


def downloaded_bytes(target: Path, sizes: dict[str, int]) -> int:
    """How much of these files has arrived: finished files and the partial ones."""
    done = sum(size for name, size in sizes.items()
               if (target / name).is_file() and (target / name).stat().st_size == size)
    partial = target / ".cache" / "huggingface" / "download"
    done += sum(p.stat().st_size for p in partial.glob("*.incomplete"))
    return min(done, sum(sizes.values()))


def report_progress(target: Path, sizes: dict[str, int], stop: threading.Event) -> None:
    total = sum(sizes.values())
    while not stop.wait(0.5):
        print(f"PROGRESS {downloaded_bytes(target, sizes)} {total}", flush=True)


def write_display_name(target: Path, name: str) -> None:
    """The name the window's lists show. A settings file already there is left alone."""
    path = target / "volis-python.toml"
    if not path.exists():
        path.write_text("# Settings for this model in volis. The name is what the window's lists show.\n"
                        f"name = {json.dumps(name, ensure_ascii=False)}\n", encoding="utf-8", newline="\n")
        print(f"wrote {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("id", nargs="?")
    parser.add_argument("--role", choices=["asr", "mt", "tts"])
    parser.add_argument("--include", action="append", default=[])
    parser.add_argument("--name", help="folder name, if the model's own name is taken")
    parser.add_argument("--login", action="store_true")
    parser.add_argument("--lookup", action="store_true", help="print what the repo holds as JSON; download nothing")
    parser.add_argument("--files", action="append", default=[], help="exactly these files, instead of choosing")
    parser.add_argument("--display-name", default="", help="the name the window's lists show")
    parser.add_argument("--progress", action="store_true", help="report the bytes as they arrive")
    args = parser.parse_args()

    if args.login:
        login()
        print(f"token saved under {os.environ['HF_HOME']}")
        return 0
    if args.lookup:
        answer = lookup(args.id)
        print(json.dumps(answer))
        return 1 if "error" in answer else 0

    target = REPO / "models" / args.role / (args.name or args.id.split("/")[-1])
    if args.role != "tts" and (target / "engine.toml").is_file():
        print(f"STOP: {target} is an engine.toml (sherpa-onnx) model folder. Give the download "
              "its own folder name with -Name.", file=sys.stderr)
        return 1
    api = HfApi()
    try:
        info = api.model_info(args.id, files_metadata=True)
    except GatedRepoError:
        print(f"STOP: {args.id} is gated. Accept its terms at https://huggingface.co/{args.id} "
              "in your browser, then run: .\\fetch-model.ps1 -Login", file=sys.stderr)
        return 1
    except RepositoryNotFoundError:
        print(f"STOP: no model {args.id} on Hugging Face (or it is private: run .\\fetch-model.ps1 -Login)",
              file=sys.stderr)
        return 1
    sizes = {s.rfilename: s.size or 0 for s in info.siblings or []}
    if missing := [f for f in args.files if f not in sizes]:
        print(f"STOP: {args.id} has no file {missing[0]}", file=sys.stderr)
        return 1
    wanted = args.files or choose(list(sizes), args.role, args.include)
    print(f"{args.id} -> {target}", flush=True)
    for f in wanted:
        print(f"  {f}", flush=True)
    remove_leftovers(target)
    stop = threading.Event()
    if args.progress:
        threading.Thread(target=report_progress, args=(target, {f: sizes[f] for f in wanted}, stop),
                         daemon=True).start()
    try:
        snapshot_download(args.id, local_dir=target, allow_patterns=wanted)
    except GatedRepoError:
        print(f"STOP: {args.id} is gated. Accept its terms at https://huggingface.co/{args.id} "
              "in your browser, then run: .\\fetch-model.ps1 -Login", file=sys.stderr)
        return 1
    except Exception as e:  # the connection dropped, the disk filled: what was finished stays
        print(f"STOP: downloading {args.id} into {target} failed: {e}", file=sys.stderr)
        return 1
    finally:
        stop.set()
    if args.role == "tts":
        finish_voice(target, args.display_name)
    elif args.display_name:
        write_display_name(target, args.display_name)
    print(f"\ndone. Check it with: .\\.venv\\Scripts\\python.exe -m volis --report")
    return 0


if __name__ == "__main__":
    sys.exit(main())
