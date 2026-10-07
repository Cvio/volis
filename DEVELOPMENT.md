# Development

For people changing Volis or building it for others. To install and use it, see
[README.md](README.md).

| Document | What it holds |
|---|---|
| `CLAUDE.md` | The hard constraints (never online at runtime, everything in one folder) and working rules. |
| `HANDOFF.md` | Where the work stands, its history, and every difference from volis-rust with the reason. |
| `volis-build.md` | The original build specification, milestone by milestone (P0 to P12, done). |
| `volis-next-features.md` | The current specification: P13 to P20. |
| `MODELS.md` | Models: recommendations, choosing your own, and every test result. |
| `SETTINGS.md` | Every setting and command-line option. |

## The environment

`.\setup.ps1` installs Python 3.12 and every package into this folder (`.uv\`, `.venv\`) with
`uv sync --locked`, then runs `.\doctor.ps1`. Every package version is pinned in `uv.lock`; a
package is only ever added by editing `pyproject.toml` and running `uv lock`, never by
`pip install`. `HANDOFF.md` ("Versions") lists the pins that matter and why.

```powershell
.\.venv\Scripts\python.exe -m pytest      # the tests; they must pass at every commit
.\doctor.ps1                              # the environment: libraries present, versions, GPU
```

If security software removes DLLs, give it an exclusion for this folder and run
`.\setup.ps1 -Reinstall`.

## The translator on the graphics card

The translator runs through llama.cpp, by way of the `llama-cpp-python` package. That package
is published as source only for the version Volis needs, so it is compiled here, once, and
the result (a wheel) is kept in `wheels\`. `setup.ps1` installs the wheel and needs no compiler.

The wheel in the repository is a **CPU build**. For translation on the graphics card, which is
several times faster, the GPU wheel is built on each machine. **README.md, step 3 of "Set it
up", has the full instructions,** written for someone who has never done it: Visual Studio
Build Tools (the C++ workload), NVIDIA's CUDA Toolkit 12.8 or 12.9 (not 13; Custom install,
only the `CUDA` box ticked, so the driver isn't replaced), then:

```powershell
.\build-llama.ps1 -Cuda
.\setup.ps1
```

`setup.ps1` ends by saying where the translator will run. The wheel is not in the repository
(too large), so **a fresh clone has only the CPU build** until this is done, or until
`wheels\cuda\` is copied from a machine that has it.

The wheel goes in `wheels\cuda\` (344 MB, not committed). Running it needs no toolkit: it uses
the CUDA files PyTorch already ships. `.\doctor.ps1` then reports `GPU offload: yes`, and
`[translate] device = "auto"` uses the card.

`.\build-llama.ps1` with no option rebuilds the CPU wheel; do that only to change the
llama.cpp version or its build options.

## Building the ready-made folder

```powershell
.\build.ps1
```

This makes `dist\volis\`: `volis.exe`, the libraries it needs in `_internal\`, and `models\`,
`config\`, `prompts\` and this machine's `volis.toml` and `volis-python.toml` beside it. Copy
or zip that whole folder; on another Windows PC it runs with no Python, no setup and no
internet.

- **Size:** about 5.6 GB for the program (PyTorch with CUDA is most of it) plus the models.
  `.\build.ps1 -NoModels` builds the program alone; put a `models\` folder beside it
  afterwards. On the same drive as the repository, models are hard-linked into `dist\`, so
  they take no more disk until the folder is copied.
- **The other PC needs an NVIDIA GPU** and its driver when the GPU translator wheel is
  installed here. The CUDA libraries themselves are in the folder.
- **It is a console program:** a double-click opens the window with a console behind it, and
  the same exe takes every command-line option.
- `volis.exe --doctor` checks the folder on the other PC: every library present, the right
  version, and loaded from the folder itself.
- `scripts\p12_check.py` runs the built program on the test recordings and watches it for
  network connections.

It uses PyInstaller in one-folder mode (`volis.spec`), installed from `uv.lock`'s `build` group.

## The performance panel

`volis\perf.py` and `volis\gui\perf_panel.py`. GPU figures come from `nvidia-smi`, read once a
second while the panel is open. Windows doesn't report one program's GPU memory, so Volis's
share is the sum of what its loaded models take, and "others" is the rest. Every run is
recorded in `logs\performance.json`: the memory each model took when it loaded, and the run's
speed. The What if tab uses those measurements once a model has been loaded here, and its file
sizes before that.

## Test recordings and checks

```powershell
.\tests\fetch-fixtures.ps1                                   # test clips: FLEURS, with references
.\.venv\Scripts\python.exe scripts\make_fixture_file.py es_419 en   # join clips into one recording
.\.venv\Scripts\python.exe scripts\transcribe.py es_419 ar_eg       # every recognizer on the clips
.\.venv\Scripts\python.exe scripts\mt_bench.py                      # every translator on reference text
.\.venv\Scripts\python.exe scripts\obey_check.py                    # does a translator translate questions, or answer them?
.\.venv\Scripts\python.exe scripts\vad_cuts.py --mic 20 --wav       # where speech is cut, with and without pre-roll
```

`scripts\p7_check.py`, `p8_check.py`, `p11_check.py` and `p12_check.py` are the checks each
milestone ended with; `HANDOFF.md` records their results.

## The model download list

`.\fetch-models.ps1` reads its list from the `LIST` at the top of `scripts\fetch_models.py`.
Add an entry there and it is on the list, with the settings file it needs. Each entry is in a
group (`use`, `bigger`, `untested`, `tested`); only `use` and `bigger` download by default.
`MODELS.md` explains the groups.

Two recognizers on the development machine are not downloadable:
`whisper-large-v3-turbo-es-adriszmar-onnx-int8` and
`whisper-large-v3-turbo-arabic-dialectal-onnx-int8` are fine-tunes converted to 8-bit ONNX by
[model-converter](../model-converter/README.md) for volis-rust. Volis runs the originals
instead, which score better.

## Translators that only translate (seq2seq)

`volis\translate\seq2seq.py` runs MADLAD-400 (`t5`), NLLB-200 (`m2m_100`) and Marian models
through `AutoModelForSeq2SeqLM`, with beam search (4). `models.py` recognizes them by
`model_type` and never takes a speech model for one. The language-code tables are in the
module; every code is checked against the loaded tokenizer's vocabulary, and the model list
reads the codes from `tokenizer.json` without loading anything. Half precision on the GPU when
the model fits, otherwise the CPU.

## The Persian clean-up

`volis\persian.py` runs between recognition and translation when the source language is
Persian (`[text] persian_cleanup`). Its letter table, spacing patterns and verb list are
ported from [hazm](https://github.com/roshan-research/hazm)'s normalizer (MIT), not imported:
hazm would add three packages and load a 3.4 MB word list at start. The module's docstring
lists exactly what was ported and what was left out. `scripts\p16_check.py` measures its
effect on the Persian test clips, clean-up off and on; `HANDOFF.md` has the figures.

## volis-rust

Volis began as a port of volis-rust, the original Rust implementation, and stays compatible
with it in three ways, each a rule in `CLAUDE.md`:

- **`volis.toml`** is the same file in both, same keys and meanings. volis-rust refuses
  settings it doesn't know, which is why the settings only Volis has are in
  `volis-python.toml`.
- **Paired mode** speaks the same protocol, so either app can be at either end.
- **`models\`** has the same layout. volis-rust uses the one `.gguf` at the top of
  `models\mt\` and refuses to start with two, so every other translator goes in a folder of
  its own. Its recognizers are the `-onnx-int8` folders.

To compare the two on the same audio, copy `machine.example.yaml` to `machine.yaml`, point it
at `volis-rust.exe`, and run:

```powershell
.\.venv\Scripts\python.exe parity\report.py
```

`[translate] prompt = "rust"` sends exactly the prompt volis-rust sends, and
`[context] mode = "off"` translates each sentence alone, as it does.
