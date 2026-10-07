"""The P16 measurement: does the Persian clean-up help translation?

    .venv\\Scripts\\python.exe scripts\\p16_check.py [--mt id ...] [--skip id-part ...]

On the ten Persian test clips (FLEURS, with English references from FLORES+):

1. each installed recognizer that covers Persian transcribes them; so does
   nobody, for the row "reference text" (the clips' own transcripts);
2. each transcript is cleaned (volis/persian.py), and the script counts how
   many it changes and what it does to the transcript's error rate;
3. each installed translator translates every transcript twice, as heard and
   cleaned, each sentence on its own, and chrF against the English reference
   is reported both ways.

Ten sentences: a difference of a point or two is noise. Results are written
to logs\\p16-check.json as well, so HANDOFF.md can quote them.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from volis import paths  # noqa: E402

paths.apply_offline_environment(paths.app_root())
for stream in (sys.stdout, sys.stderr):
    stream.reconfigure(encoding="utf-8", errors="replace")

import logging  # noqa: E402

logging.disable(logging.WARNING)

from volis import asr, models, persian, scoring  # noqa: E402
from volis import translate as tr  # noqa: E402
from volis.config import PythonConfig  # noqa: E402
from volis.filesource import read_16k_mono  # noqa: E402
from volis.translate import prompts  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "fleurs" / "fa_ir"


def clips() -> list[dict]:
    rows = [json.loads(line) for line in (FIXTURE / "refs.jsonl").read_text(encoding="utf-8").splitlines()]
    for row in rows:
        if isinstance(row["references"], str):
            row["references"] = ast.literal_eval(row["references"])
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mt", nargs="*", default=[], help="only these translators (ids)")
    parser.add_argument("--skip", nargs="*", default=[], help="leave out translators whose id contains this")
    args = parser.parse_args()
    if not (FIXTURE / "refs.jsonl").is_file():
        print(f"STOP: no {FIXTURE}; run tests\\fetch-fixtures.ps1")
        return 1
    root = paths.app_root()
    pyconfig, _ = PythonConfig.load(paths.python_config_file(root))
    rows = clips()
    references = [r["references"]["en"] for r in rows]
    truth = [r["raw_transcript"] for r in rows]
    verbs = persian.load_verbs(paths.persian_verbs_file(root))

    # ---- 1. transcripts
    transcripts: dict[str, list[str]] = {"reference text": truth}
    engines = [e for e in models.discover(paths.asr_dir(root), models.Role.ASR)
               if isinstance(e, models.Engine) and e.enabled() and e.languages_known and "fa" in e.languages]
    audio = [read_16k_mono(FIXTURE / r["file"]) for r in rows]
    for engine in engines:
        print(f"transcribing with {engine.dir_name}...", file=sys.stderr)
        try:
            recognizer = asr.load(engine)
            transcripts[engine.dir_name] = [recognizer.transcribe(a, "fa", False).text for a in audio]
            recognizer.close()
        except Exception as e:
            print(f"  {engine.dir_name} failed: {e}", file=sys.stderr)

    # ---- 2. what the clean-up changes
    cleaned = {name: [persian.clean(t, verbs).text for t in texts] for name, texts in transcripts.items()}
    result = {"sentences": len(rows), "transcripts": {}, "translators": {}}
    print(f"\nPersian clean-up on {len(rows)} FLEURS clips\n")
    print(f"{'transcript from':34s} {'changed':>8s} {'CER as heard':>13s} {'CER cleaned':>12s}")
    for name, texts in transcripts.items():
        changed = sum(a != b for a, b in zip(texts, cleaned[name]))
        before = scoring.cer(" ".join(truth), " ".join(texts), "fa")
        after = scoring.cer(" ".join(truth), " ".join(cleaned[name]), "fa")
        result["transcripts"][name] = {"changed": changed, "cer_heard": round(before, 2), "cer_cleaned": round(after, 2)}
        print(f"{name:34s} {changed:>5d}/{len(texts)} {before:>12.1f}% {after:>11.1f}%")
    shown = 0
    for name, texts in transcripts.items():
        for a, b in zip(texts, cleaned[name]):
            if a != b and shown < 4:
                shown += 1
                print(f"\n  {name}, as heard: {a}\n  {'':{len(name)}}  cleaned:  {b.replace(persian.ZWNJ, '|')}")

    # ---- 3. translation, both ways
    found = [t for t in models.discover_translators(paths.mt_dir(root)) if isinstance(t, models.Translator) and t.enabled()]
    wanted = [t for t in found if (not args.mt or t.id in args.mt) and not any(s in t.id for s in args.skip)]
    prompt = prompts.load(paths.prompts_dir(root), pyconfig.translate.prompt)
    print(f"\n{'translator':44s} {'transcript from':28s} {'chrF as heard':>14s} {'chrF cleaned':>13s} {'change':>7s} {'ms':>6s}")
    for entry in wanted:
        print(f"loading {entry.id}...", file=sys.stderr)
        try:
            translator = tr.load(entry, prompt, pyconfig.translate.device)
        except Exception as e:
            print(f"{entry.id}: could not be loaded: {e}")
            continue
        memo: dict[str, str] = {}
        times: list[float] = []

        def translate(text: str) -> str:
            if text not in memo:
                began = time.perf_counter()
                try:
                    memo[text] = translator.translate(tr.TranslationRequest(text, "fa", "en")).text
                except (tr.Refused, tr.TranslateError):
                    memo[text] = ""
                times.append(time.perf_counter() - began)
            return memo[text]

        result["translators"][entry.id] = {}
        for name, texts in transcripts.items():
            heard = scoring.chrf(" ".join(references), " ".join(translate(t) for t in texts), "en")
            clean = scoring.chrf(" ".join(references), " ".join(translate(t) for t in cleaned[name]), "en")
            ms = int(sorted(times)[len(times) // 2] * 1000) if times else 0
            result["translators"][entry.id][name] = {"chrf_heard": round(heard, 1), "chrf_cleaned": round(clean, 1)}
            result["translators"][entry.id]["ms"] = ms
            print(f"{entry.id:44s} {name:28s} {heard:>14.1f} {clean:>13.1f} {clean - heard:>+7.1f} {ms:>6d}")
        translator.close()
    out = paths.logs_dir(root) / "p16-check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    merged = json.loads(out.read_text(encoding="utf-8")) if out.is_file() and args.mt else {}
    merged.setdefault("translators", {})
    merged.update({k: v for k, v in result.items() if k != "translators"})
    merged["translators"].update(result["translators"])
    out.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwritten: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
