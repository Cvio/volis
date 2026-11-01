# Development

For people changing Volis or building it for others. To install and use it, see
[README.md](README.md). `CLAUDE.md` has the hard constraints and working rules, and `HANDOFF.md`
what is open and why the code is the way it is.

## The environment

`.\setup.ps1` installs Python 3.12 and every package into this folder (`.uv\`, `.venv\`) with
`uv sync --locked`, then runs `.\doctor.ps1`. A package is only ever added by editing
`pyproject.toml` and running `uv lock`, never by `pip install`.

```powershell
.\.venv\Scripts\python.exe -m volis       # run it from the source code
.\.venv\Scripts\python.exe -m pytest      # the tests; they must pass at every commit
.\doctor.ps1                              # the environment: libraries present, versions, GPU
```

If security software removes DLLs, give it an exclusion for this folder and run
`.\setup.ps1 -Reinstall`.

## The translator on the graphics card

The translator runs through llama.cpp, by way of the `llama-cpp-python` package. It is compiled
here, once, and the result (a wheel) is kept in `wheels\`. `setup.ps1` installs the wheel and needs
no compiler.

The wheel in the repository is a **CPU build**. The GPU wheel is several times faster, too large to
commit (344 MB), and built on each machine, or copied into `wheels\cuda\` from one that has it.
**README.md, step 3 of "Set it up", has the full instructions.** In short:

```powershell
.\build-llama.ps1 -Cuda
.\setup.ps1
```

Running it needs no toolkit: it uses the CUDA files PyTorch already ships. `.\doctor.ps1` then
reports `GPU offload: yes`. `.\build-llama.ps1` with no option rebuilds the CPU wheel; do that only
to change the llama.cpp version or its build options.

## Building the ready-made folder

| Command | What it does |
|---|---|
| `.\build.ps1` | Builds the folder with this machine's models, keeping developer mode. |
| `.\build.ps1 -NoModels` | The same without the models. Put a `models\` folder in `dist\volis\` afterwards. |
| `.\build.ps1 -NoModels -Customer` | Builds a customer's copy without the models. |

This makes `dist\volis\`: `volis.exe`, the libraries it needs in `_internal\`, and `models\`,
`config\`, `prompts\` and this machine's `volis.toml` and `volis-python.toml` beside it. Copy or zip
that whole folder; on another Windows PC with an NVIDIA GPU and driver it runs with no Python, no
setup and no internet.

- **Size:** about 5.6 GB plus the models. On the same drive as the repository, models are
  hard-linked into `dist\`, so they take no more disk until the folder is copied.
- `volis.exe --doctor` checks the folder on the other PC.
- `scripts\p12_check.py` runs the built program on the test recordings and watches it for network
  connections.

To check a customer's copy, start it in developer mode. It should open the ordinary window, with no
developer pages:

```powershell
.\dist\volis\volis.exe --developer
```

## Developer mode

`Volis (developer).cmd` opens the same window with four more pages (`--developer`, in
`gui\developer.py`). A customer's copy has neither the file nor the mode: the build writes
`[setup] developer = false`.

| Page | What is there |
|---|---|
| **Models** | The recognizer and translator, with a warning if they won't fit or were too slow here; each side's recognizer and voice for two people on one computer; rescanning models and devices (F5). |
| **Test bench** (Ctrl+Shift+T) | Comparing models; below. |
| **Performance** (Ctrl+Shift+P) | The last sentence's timings and the run's summary, **Export this run**, and the panel below. |
| **Developer** | Streaming, joining fragments, holding the key while speaking, context, revision, waiting before speaking, vowel marks, the glossary, and how a recording is read. |

### The test bench

| Tab | The question it answers | What you give it |
|---|---|---|
| **Recognizers** | Which one hears this best? | A recording you make there, or an audio file. If you also type what was really said, each recognizer is marked against it. |
| **Translators** | Which one translates this best? | Text, a recording or an audio file (one recognizer writes it down first). If you also paste a translation you trust, each is scored against it. |
| **Whole set** | Will this recognizer, translator and voice run together on this computer? | Your choice of the three. It answers without loading anything, and can then time the set on a recording. |

Each tab has numbered steps on the left and the answer on the right. Each model's result is a card,
the closest to your text first; **Use in the conversation** on a card chooses it. Comparisons stay
under **Earlier comparisons**, where they can be searched and deleted.

- **Letters wrong** and **Words wrong:** how far what was heard is from your text. Lower is better.
- **Score:** from 0 to 100, how close the translation is to the one you pasted. Higher means closer,
  not "correct": a good translation in different words scores lower.
- **Time** and **Speed:** how long the model took, without the time to load it.

In the code, `bench.py` has the work and no Qt, and `gui\testbench.py` paints what it decides. A clip
is cut into utterances once, so every recognizer gets the same pieces. Models load one at a time,
because they might not fit together and a time measured beside another model measures the crowding.
It works only while no conversation runs, since both need the same memory. Comparisons are kept in
`logs\test-bench.json` (the last 200).

### The performance panel

`perf.py` and `gui\perf_panel.py`. GPU figures come from `nvidia-smi`, read once a second while the
panel is open. Every run is recorded in `logs\performance.json`: the memory each model took and the
run's speed. The Models page's warning and the Whole set tab read those measurements once a model
has been loaded here, and its file sizes before that.

## Test recordings and checks

```powershell
.\tests\fetch-fixtures.ps1                                   # test clips: FLEURS, with references
.\.venv\Scripts\python.exe scripts\make_fixture_file.py es_419 en   # join clips into one recording
.\.venv\Scripts\python.exe scripts\transcribe.py es_419 ar_eg       # every recognizer on the clips
.\.venv\Scripts\python.exe scripts\mt_bench.py                      # every translator on reference text
.\.venv\Scripts\python.exe scripts\obey_check.py                    # does a translator translate questions, or answer them?
.\.venv\Scripts\python.exe scripts\vad_cuts.py --mic 20 --wav       # where speech is cut, with and without pre-roll
```

The `scripts\p*_check.py` files run real models through a whole feature. `scripts\app_shots.py` draws
the pictures in `docs\images\`.

## The model download list

`.\fetch-models.ps1` reads its list from the `LIST` at the top of `scripts\fetch_models.py`. Add an
entry there and it is on the list, with the settings file it needs. Each entry is in a group (`use`,
`bigger`, `untested`, `tested`); only `use` and `bigger` download by default.

## Translators that only translate (seq2seq)

`translate\seq2seq.py` runs MADLAD-400 (`t5`), NLLB-200 (`m2m_100`) and Marian models through
`AutoModelForSeq2SeqLM`, with beam search (4). `models.py` recognizes them by `model_type`. Every
language code is checked against the loaded tokenizer's vocabulary, and the model list reads the
codes from `tokenizer.json` without loading anything.

## The Persian clean-up

`persian.py` runs between recognition and translation when the source language is Persian
(`[text] persian_cleanup`). Its tables are ported from
[hazm](https://github.com/roshan-research/hazm)'s normalizer (MIT); the module's docstring lists
exactly what was ported. `scripts\p16_check.py` measures its effect, clean-up off and on.
