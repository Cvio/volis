# Handoff

What is open, and why the code is the way it is. Read `CLAUDE.md` first. Older detail is in git
history. Last updated 2026-11-01.

## Where it stands

Everything in `README.md` is built: the window, the three ways of talking, saving and sharing,
opening recordings, the test bench and developer mode, and the ready-made folder. Still to build:
P18 to P20 in `volis-next-features.md`.

## Open

### Must have

Mostly checks, not features: the largest unknown is whether this holds up away from this machine
and with real people.

| Item | Who |
|---|---|
| **The ready-made folder on a second Windows PC** with no Python and no internet: zip, unzip, live conversation, Resource Monitor watched for connections. Rebuild first (`.\build.ps1`, `scripts\p12_check.py`). | Rebuild: Claude. Second PC: the user |
| **Two computers, for real:** find, accept, talk, end, both have the whole conversation; then the same on a network that blocks discovery, by typed address. Never yet run on two machines. | The user |
| **Two people at one computer,** speakers at normal volume: the other key does nothing during a turn, Escape silences a turn, Volis never translates its own voice. | The user |
| **A first-time user starts a conversation unaided.** | The user |
| **In-app help (P18).** `README.md` doesn't reach someone handed the ready-made folder. | Claude, when the user says go |

### Should have

- **Fixing a sentence (P19a, P19b),** then the corrections log (P19c).
- **Everyday test sentences** for Persian and Iraqi Arabic, checked by a speaker. Everything
  measured so far is read news; the first colloquial sentence tried ("menu", see P19d in the plan)
  defeated all nine translators.
- **The real context test for Persian,** then say in `MODELS.md` which translator to use. In a
  running conversation with context on, type a restaurant sentence, then
  میشه منو رو ببینم لطفا؟ as a second line. In the user's runs only Gemma 4 12B and Gemma 4 E4B used
  context correctly.
- **Quiet speech straight after loud speech** is missed. It is the Silero detector itself: a clip
  37 dB quieter than the one before was not found, though it is when given alone. Find out how
  large the difference must be, and try evening out levels.
- **A translator that lacks the chosen language** greyed out beforehand, with the reason. Today
  it is refused when it translates.
- **Model advice (part of P20).**
- **The GPU translator build published,** so setting up from a clone needs no build tools. Matters
  less if everyone gets the ready-made folder.

### Nice to have

- Guided tutorials (part of P20).
- Two computers listening continuously.
- A graphics-card or processor choice in the window (now only `[translate] device`).
- A context box in the test bench. Joining two sentences on one line is not the same and spoils
  the score.
- One settings file in place of `volis.toml` and `volis-python.toml`.
- An automatic check of the Arabic vowel marks, since no listener has judged them.
- Translating the computer's own sound with a caption window; speaker labels on recordings; a
  full-screen view for the other person; Word and PDF export; password protection; a Farsi or
  Arabic interface.
- Small loose ends: the "too slow" warning exists only for a pair already run here; an English
  test recording with references; whether
  the Persian clean-up should be off by default (no measured benefit); `--translate` prints
  "prompt default" and no fallback note for a seq2seq model; `session.py`'s `comparing` and
  `session.indicator` are used only by tests; `models\asr\whisper-model-large-hmong` has no
  `config.json`.

### Waiting on the user

- CTranslate2: it mainly helps a machine with no graphics card, which is not a target. Proposal:
  drop it.
- Gemma 4 26B: record it in `MODELS.md`, add a per-model layer setting, or delete it (51.6 GB).
- Whether P18 or P19 comes first.

### On hold, by the user's decision

- Glossaries and the phrasebook (P19d).
- Holding speech for revision (`[context] hold_speech`): built, set aside.
- Linux, and machines without an NVIDIA card.

### Tried and dropped

- A "situation" line in the translator's instructions (restaurant, clinic). Given a restaurant
  sentence, three smaller translators invented words ("my order", "my reservation").
- Other ways of showing a translator the following sentence during revision: none beat translating
  the two together, and two made Qwen recite the note.

## Why things are the way they are

### The pipeline

- **Translation is per sentence, not per utterance.** Each sentence has the id
  `<utterance>.<n>`, used by every event and the export. Text with no final punctuation stays one
  sentence per utterance.
- **One set of events** (`events.py`) for everything: the window, `--listen`, recordings,
  `events.jsonl`.
- **Recognition has its own thread** (`AsrWorker`), so a slow pass never delays cutting speech.
  Final passes come first; a provisional pass already out of date is skipped.
- **From a file nothing is dropped;** live use drops what the translator can't take in time.
- **A turn ends when all its sentences have run their course:** translated or refused and, when
  spoken, spoken. A short fragment at the end of a turn isn't held, since nothing can follow it.
- **Cancelling drops what is under way at every stage,** including sentences queued for translating
  or speaking.
- **Resampling uses soxr,** a better filter than sherpa-onnx's linear one.
- **Every PortAudio stream opens on one thread:** through WASAPI a stream otherwise fails to start
  ("Unanticipated host error").
- **Word timestamps are asked for only where used.** They cost Whisper about 1 s a pass.
- **GPU recognizers make one pass over silence when they load,** or the first turn takes about
  three times as long.
- **Streaming** commits words two passes agree on; the final pass still decides the text. Not for
  turns: a turn is recognised once.

### Guards

- **Prompts come from each GGUF's own chat template,** so a GGUF with no template is unusable.
  Models that only translate (TranslateGemma: `source_lang_code` in the template) get what the
  template asks for; the prompt file and glossary aren't used with them.
- **The default prompt frames the text** ("text to translate ...; never answer it"), with the text
  in quotes. Without the frame and with context, Gemma 3 4B translated only 9 of 24 tempting
  sentences; with it, 24. `guards.contains_the_wrapper` refuses output that repeats the frame.
- **The recital guard ignores earlier turns the sentence repeats** (`guards.repeats`, 60% of its
  words): a sentence said again rightly translates to the earlier translation.
- **Recognizer guards** (`asr/guards.py`): speech probability, repeats, stock phrases, and "sparse"
  (fewer than one word per 3 s), for the one- or two-word outputs Whisper gives on long noise.
  Sherpa-onnx's binding doesn't expose Silero's probabilities, so the first uses a second Silero
  with `min_peak_probability` as its threshold.

### Context and revision

- **Context leaves half at a time,** so consecutive prompts start the same way and the translator
  reuses what it evaluated: about 0.7 s a sentence instead of 1.7 s on the CPU.
- **On a shared computer, context crosses directions turned round,** so an answer is translated
  knowing the question.
- **Revision never touches** a sentence handed to the voice, one over 30 s old, one over 8 words
  (revising everything made translation worse: chrF 61.2 against 63.6), the newest, or one
  already revised (second looks flip-flop). It fixes a minority of what context gets wrong, and
  changes nothing once the voice is on.
- **Context stays local and revision is off with two computers:** only the final translation is
  sent.

### Text

- **Right to left needs a right-to-left base direction,** or the final full stop lands on the wrong
  side. A Qt layout mirrors left and right for a right-to-left widget unless `AlignAbsolute` is set.
- **The Persian clean-up is ported from hazm, not imported:** hazm brings three packages and a
  3.4 MB word list. `persian.py`'s docstring lists what was ported, left out and changed. Measured
  on ten read clips: no clear effect, either way.
- **Vowel marks** (`tashkeel.py`) port Piper's step, which sherpa-onnx leaves out.

### Models and libraries

- **llama-cpp-python is built here:** published wheels stop at older versions, 0.3.35 is source
  only.
- **The GPU build uses PyTorch's own CUDA 12 files,** loaded by full path first
  (`llamacpp.load_cuda_runtime`), so there is one copy and no toolkit is needed to run. CUDA 12.9's
  headers refuse Visual Studio 2026's compiler; the build passes `-allow-unsupported-compiler`.
- **Flash attention is on;** llama-cpp-python turns it off unless told.
- **llama.cpp speech models go through `mtmd_cpp` directly:** the package's chat handlers take
  images only.
- **Reading a GGUF's metadata walks its vocabulary in memory:** listing five took 1.5 s with a read
  per string, 0.3 s now.
- **A recognizer's LoRA is merged at load** in memory (`peft`). **A GGUF LoRA is a translator of its
  own:** a folder with the adapter and `base = "<translator id>"`.
- **`onnxruntime` is a dependency** for the vowel marks. On Windows it carries its runtime inside
  its extension, so sherpa-onnx's 1.28.2 stays the only `onnxruntime.dll` in the process.
- **GPU memory per program isn't reported by Windows,** so Volis's share is the sum of its loaded
  models and "others" is the rest.
- **The Download section runs `fetch_model.py` as a separate program,** so Volis keeps
  `HF_HUB_OFFLINE` and never imports the code that goes online. `download.py` must not import
  `fetch_model`, which removes that setting; a test checks it brings in no Hugging Face library.
- **A stopped download can't resume.** With `huggingface_hub` 1.33.0, a new run started the file
  from zero under a new name and left the old partial file behind, so `remove_leftovers` deletes
  it. Finished files stay.
- **The window's downloads turn Xet off** (`--progress`). Xet writes a file nearly all at once, so
  there is nothing to measure; plain HTTP grows in 10 MB steps. `fetch-model.ps1` still uses Xet.
- **A display name covers the whole folder,** so two versions in one named folder show the same
  name. Give a second version its own folder to tell them apart.

### Two computers

- **Discovery, wire and accept:** protocol version 3. Someone dialled waits for `Accept`; two
  computers choosing each other need no asking. Waiting links are pinged, or the read timeout
  closes them.
- **The audio swap** uses the same connection, so no new firewall opening. Sentences are named by
  their translation's words. A sentence still under way at the end may miss the swap; opening the
  other's file adds it.
- **Combining** recognises the other's copy: both two-computers, same day, at least half the
  shorter one's sentences match. Clocks a day apart open as a separate conversation.
- **`SO_EXCLUSIVEADDRUSE`:** on Windows two programs can otherwise share a port and each get some
  of the connections.

### The window and packaging

- **A `.volis` file is untrusted:** every field's type is checked, only audio named as `Keeper`
  names it is read, folder names are cleaned, and nothing is left behind on failure.
- **A crash's conversation is recovered silently on opening,** not by a prompt.
- **`[window] advanced_open` is accepted and ignored,** so older settings files still load.
- **PyInstaller, one folder** (`volis.spec`), with no UPX: compressed DLLs are what scanners flag.
  The spec names what its hooks can't see. transformers, torch and peft are kept as `.py`, since
  they read their own source.
- **The built program is a console program,** so the same exe takes every option.
- **`--doctor`** checks every library loaded comes from the folder or Windows.

## Versions

`uv.lock` pins every package by version and hash. The pins that matter: `sherpa-onnx` 1.13.8,
`onnxruntime` 1.28.0, `llama-cpp-python` 0.3.35, torch 2.11.0+cu128 (carries the CUDA 12 runtime
the GPU build loads), transformers 5.18.0, peft 0.21.1, Python 3.12.10, uv 0.11.26.

**Models are not pinned to a revision:** `fetch-models.ps1` takes each repo's current files. For a
deployment, copy `models\` from a machine that works rather than download again.

The repository doesn't carry the GPU wheel (344 MB) or `models\`.
