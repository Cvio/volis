# CLAUDE.md - volis

`volis-build.md` is the original build specification (P0 to P12, done) and
`volis-next-features.md` the current one (P13 to P20). Read the current one before changing
anything. Volis began as a port of a Rust app, volis-rust, which is no longer on this machine
and no longer a reference: where these files or the code say "as Rust does", the Python code
is now the specification. `model-converter` is for reading only: never change anything in it
unless the user explicitly approves a specific change.

Which document holds what: `README.md` (for a new user: what Volis is, setup, first run, the
modes, what to do when something goes wrong; **no milestones, no volis-rust, no builder's
detail**), `MODELS.md` (which models to start with, choosing your own, then every model tested
and its scores), `SETTINGS.md` (every setting and command-line option), `DEVELOPMENT.md` (the
translator build, the ready-made folder, the checks, volis-rust compatibility), `HANDOFF.md`
(status, history, and every difference from volis-rust with its reason), this file
(constraints and working rules). Rust's documents cover the wire protocol, varieties and
dialects; link to them, don't copy them.

## Hard constraints

These come from the Rust `CLAUDE.md` and SPEC §2, adapted only where they name Rust tools.

1. **Never requires, attempts or depends on internet access at runtime.** No downloads, no update
   checks, no telemetry, no model hub lookups. `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` are
   set **before** any Hugging Face library is imported, in the entry point, and a test proves no
   library opens a connection to anywhere but the local network (see "Offline enforcement").
   Local network sockets for paired mode are allowed, under the same test as Rust: *would it still
   work with the WAN cable unplugged and no DNS server anywhere on the segment?*
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
   no Python, double-click, and it works. This is heavier than the Rust version because of
   PyTorch, and that's accepted. It still has to work.

Plus the Rust working rules: every error about a file names the absolute path tried; one path
function; no settings no milestone needs.

## Working rules

- Build in the milestone order of `volis-build.md` (P0 to P12). Each milestone ends with a
  check. **Stop after each milestone, show its check passing, and wait for the user to say go
  on.** Don't work ahead.
- **Verify before you rely.** Where the spec says "verify" (llama.cpp audio, `transformers`
  classes, chat templates, packaging), check the installed version's behaviour and report it
  before building on it. If something doesn't exist, stop and say so. Don't invent an API.
- If a Rust behaviour seems wrong, port it as it is and note it in `HANDOFF.md`. Changing it is
  the user's call, for both apps.
- One Python module per Rust module, with the same name. Port the Rust tests to pytest.
- `volis.toml` is shared with volis-rust and must stay loadable by it: Rust rejects unknown
  sections (`deny_unknown_fields`), so volis-only settings go in `volis-python.toml`, never in
  `volis.toml`.
- `models\mt\`: Rust uses exactly one `.gguf` at the top level and refuses to start with two.
  Extra translators go one folder per model inside it, which Rust never looks at.
- Open, start, stop and close every audio stream through `audio.on_audio_thread`, and get
  sounddevice through `audio._sd()`: PortAudio only works from the thread that initialised it.
- `paths.app_root()` is the only path-derivation function. `volis/__main__.py` sets the
  offline environment before importing anything else; keep it that way.
- Commit after each milestone. Tests pass at every commit (`.venv\Scripts\python.exe -m pytest`).
- When the user **asks a question, answer it and wait.** Don't run commands or change their
  `volis.toml` unasked.

## Status

P0 to P12 done (through the window, voice output, file mode, continuous and turn-based modes,
streaming recognition, carry-forward context, revision mode, paired mode, the shared machine,
the llama.cpp speech, LoRA and transformers-translator backends, and the copy-to-run folder
built by `build.ps1`). See `HANDOFF.md`.
