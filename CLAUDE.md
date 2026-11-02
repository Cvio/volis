# CLAUDE.md - volis

`model-converter` is for reading only: never change anything in it unless the user explicitly
approves a specific change.

Which document holds what:

| Document | What it holds |
|---|---|
| `README.md` | For a new user: what Volis is, setup, first run, what to do when something goes wrong. No builder's detail. |
| `OVERVIEW.md` | For someone deciding whether to use it. |
| `MODELS.md` | Which models to start with, choosing your own, test scores. |
| `SETTINGS.md` | Every setting and command-line option. |
| `DEVELOPMENT.md` | Building, checking and finding your way round the code. |
| `HANDOFF.md` | What is open, and why the code is the way it is. |
| `volis-next-features.md` | The plan for the features not built yet (P18 to P20). Read it before building one. |

## Hard constraints

1. **Never requires, attempts or depends on internet access at runtime.** No downloads, no update
   checks, no telemetry, no model hub lookups. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are
   set **before** any Hugging Face library is imported, in the entry point, and a test proves no
   library opens a connection to anywhere but the local network. Local network sockets for
   two-computer conversations are allowed, under this test: *would it still work with the WAN
   cable unplugged and no DNS server anywhere on the segment?*
   The one exception: the developer Models page may start `scripts\fetch_model.py` as a separate
   program, only from source. Volis itself stays offline, and the no-connections test still applies
   to it. The goal is that translation always works fully offline, not to stop a developer fetching
   a model.
2. **No separate services.** Every model runs in-process. No Ollama, no local servers, no helper
   processes that serve models. (A Python thread is fine. A child process running inference is
   not.)
3. **No JavaScript toolchain.**
4. **No OS-managed folders.** Never read or write `%APPDATA%`, `%LOCALAPPDATA%`, `~/.cache`,
   Hugging Face's cache, or PyTorch's cache. Every path comes from one `app_root()` function. Set
   `HF_HOME`, `TORCH_HOME` and similar variables to folders **inside** the app, so a library that
   tries to cache something stays inside the app.
5. **Model files keep their published names,** in folders named after the model. A folder made
   by `hf download` is exactly what the user sees in Explorer.
6. **Copy-to-run:** zip the finished folder, unzip on a fresh Windows machine with no internet and
   no Python, double-click, and it works. It is heavy because of PyTorch, and that's accepted. It
   still has to work.

Every error about a file names the absolute path tried. Add no setting that no feature needs.

## Working rules

- Build one stage at a time. **Stop after each, show its check passing, and wait for the user to
  say go on.** Don't work ahead.
- **Verify before you rely.** Where a plan says "verify" (library classes, chat templates,
  packaging), check the installed version's behaviour and report it before building on it. If
  something doesn't exist, stop and say so. Don't invent an API.
- Window logic stays out of Qt: new state and rules go in Qt-free modules with tests.
- New settings go in `volis-python.toml` and `SETTINGS.md`, never in `volis.toml`.
- `models\mt\`: at most one `.gguf` at the top level, the default translator. Every other
  translator goes in a folder of its own inside it.
- Open, start, stop and close every audio stream through `audio.on_audio_thread`, and get
  sounddevice through `audio._sd()`: PortAudio only works from the thread that initialised it.
- `paths.app_root()` is the only path-derivation function. `volis/__main__.py` sets the
  offline environment before importing anything else; keep it that way.
- Commit after each stage. Tests pass at every commit (`.venv\Scripts\python.exe -m pytest`).
- When the user **asks a question, answer it and wait.** Don't run commands or change their
  `volis.toml` unasked.
