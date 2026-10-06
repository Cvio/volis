"""The P15 check: a Persian, an Arabic and a Spanish sentence, each through
two translators with a reference, show both outputs, the scores and the
timings.

    .venv\\Scripts\\python.exe scripts\\p15_check.py [translator-id translator-id]

The sentences are the first clip of each language's test recordings (FLEURS),
and the reference is its English translation (FLORES+). It runs the real
command, `--translate --compare-mt ... --reference ...`, once per language.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FLEURS = REPO / "tests" / "fixtures" / "fleurs"
DEFAULT = ["gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf", "translategemma-4b-it-GGUF/translategemma-4b-it.Q4_K_M.gguf"]


def first_sentence(folder: str) -> tuple[str, str]:
    row = json.loads((FLEURS / folder / "refs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    references = row["references"]
    if isinstance(references, str):
        references = ast.literal_eval(references)
    return row["raw_transcript"], references["en"]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    translators = sys.argv[1:] or DEFAULT
    ok = True
    for folder, language in (("fa_ir", "fa"), ("ar_eg", "ar"), ("es_419", "es")):
        if not (FLEURS / folder / "refs.jsonl").is_file():
            print(f"(no {FLEURS / folder}; run tests\\fetch-fixtures.ps1)")
            ok = False
            continue
        text, reference = first_sentence(folder)
        done = subprocess.run(
            [sys.executable, "-m", "volis", "--translate", text, "--from", language, "--to", "en",
             "--compare-mt", ",".join(translators), "--reference", reference],
            cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
        body = done.stdout[done.stdout.find(f"{language} -> en"):]
        print(f"\n=== {language}\n{body.strip()}")
        good = done.returncode == 0 and body.count("chrF") >= len(translators) and body.count(" ms on the ") >= len(translators)
        ok &= good
        if not good:
            print(f"FAIL (exit {done.returncode})\n{done.stderr[-1500:]}")
    print("\nall passed" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
