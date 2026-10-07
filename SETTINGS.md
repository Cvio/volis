# Settings and command-line options

Everything Volis can be told, in one place. Most people never need this page: the window
saves what you choose there. [README.md](README.md) covers everyday use.

## Where settings are kept

Two files in the Volis folder. Both are plain text, both are optional, and both are updated
when you change something in the window.

| File | What it holds |
|---|---|
| `volis.toml` | The basics: languages, recognizer, microphone and speakers, voice on or off, mode, pairing, shared machine mode. |
| `volis-python.toml` | Everything else: translator, context, streaming, the checks on recognized text. |

A setting you leave out keeps its default. A setting Volis doesn't know is an error that names
it, so a typing mistake is never silently ignored.

## `volis.toml`

An example. Where a value differs from the default, the window set it.

```toml
[asr]
engine = "whisper-large-v3-turbo"   # a folder in models\asr\

[languages]
source = "en"                        # what is spoken
target = "es-MX"                     # what to translate into; a region is optional

[audio]
input_device = ""                    # "" = Windows' default; names from --devices
output_device = ""

[tts]
enabled = true                       # speak the translations
half_duplex = true                   # mute the microphone while speaking

[mode]
kind = "turn"                        # "turn" | "continuous" | "shared"
turn_key = "Space"
turn_style = "toggle"                # "toggle" = press to start, again to stop; "hold" = hold while speaking

[vad]                                # how speech is cut into sentences
threshold = 0.5                      # how sure it must be that someone is speaking
min_silence_ms = 500                 # a pause this long ends a sentence
min_speech_ms = 250                  # anything shorter is not speech

[peer]                               # pairing with another PC
enabled = false
listen_addr = "0.0.0.0:47800"        # two copies on one PC need different ports
peer_addr = ""                       # the last address typed
display_name = ""                    # "" = the computer's name
discovery = true                     # announce this PC on the local network

[shared]                             # shared machine mode: two people, a key each
left_language = "en"
right_language = "es-MX"
left_key = "ArrowLeft"
right_key = "ArrowRight"
left_asr = ""                        # the recognizer for each side; "" = best match
right_asr = ""
left_voice = ""                      # the voice that speaks each side's words; "" = best match
right_voice = ""
```

## `volis-python.toml`

```toml
[translate]
model = ""          # as --report lists it, e.g. "gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf";
                    # "" = the .gguf at the top of models\mt\, or else the first one found
prompt = "default"  # a file in prompts\
device = "auto"     # "auto" = the graphics card when the translator can use it, "cpu", or "cuda"

[asr]
streaming = false   # show text while speaking (continuous and file mode)
interval_s = 1.0    # how often the growing sentence is transcribed

[context]
mode = "carry"      # "off" = each sentence alone; "carry" = with the earlier ones as context;
                    # "revision" = carry, and earlier translations are corrected when later
                    # sentences change their meaning
sentences = 4       # how many earlier sentences, at most
token_budget = 400  # and never more than this many tokens of them
revise_sentences = 3     # revision: how many are translated again together
revise_max_age_s = 30.0  # revision: never a sentence that ended longer ago than this
revise_max_words = 8     # revision: nor one longer than this
hold_speech = false      # revision with the voice on: a short sentence waits for the next
                         # one before it is spoken, so it is spoken as corrected
hold_speech_s = 2.0      # ...this long at most

[tts]
diacritize = false  # Arabic: predict the vowel marks before the voice pronounces the text

[text]
persian_cleanup = true  # Persian: before translating, replace Arabic look-alike letters and
                        # repair the half-space (می خواهم -> می‌خواهم). The window shows the
                        # cleaned text; the tooltip shows what was heard. false = translate
                        # exactly what the recognizer wrote

[window]             # what the window remembers about itself
advanced_open = false   # whether the Advanced section is open
text_size = 12          # the conversation's text size, in points (the A- and A+ buttons)

[fragments]
hold = true         # join a few words with no full stop to what follows
min_words = 4       # shorter than this is a fragment
hold_ms = 1500      # how long it waits for the rest

[vad]
pre_roll_ms = 600   # audio kept from just before each sentence, so its first sound isn't cut

[guards]            # drop text a recognizer invents on silence or noise
vad_probability = true
min_peak_probability = 0.8
repeats = true
stock_phrases = true   # the phrases are in config\hallucinations.toml
sparse = true          # a word or two for several seconds of "speech"
min_words_per_second = 0.33
sparse_min_seconds = 3.0
```

## Lists you can edit

Two plain-text files in `config\`:

| File | What it is |
|---|---|
| `hallucinations.toml` | Phrases recognizers invent on silence ("Thanks for watching"), which Volis drops. |
| `persian_verbs.txt` | Persian verb stems, one verb a line as `past#present`. The Persian clean-up uses it to tell a verb written with its prefix joined on (میخواهم) from a word that only starts with the same letters (میز, a table). Add a verb if Volis fails to separate it. |

## Settings for one model

A model's folder may hold its own `volis-python.toml`, to correct or add to what Volis worked
out from the model's files. All optional:

```toml
name = "Whisper turbo — Spanish"          # the plain name the window's lists show
languages = ["es"]
varieties = ["es-MX"]      # the region it is tuned for, if any
device = "cuda"            # "cuda" or "cpu"
dtype = "float16"          # Hugging Face models only
trust_remote_code = false  # a model that brings its own code must be trusted explicitly
base = "whisper-small"     # a LoRA adapter: the folder (or translator id) it is applied to
scale = 1.0                # a translator's LoRA adapter: how strongly
prompt = "..."             # a GGUF speech model: how it is asked to transcribe
```

Voices and the `-onnx-int8` recognizers describe themselves in an `engine.toml` instead, which
the download script writes.

**The name in the lists.** The window shows `name` when a settings file gives one. Otherwise
it shows the folder's name tidied up (`gemma-3-4b-it-GGUF` becomes "Gemma 3 4b it"). The
download script writes a plain name for each model it fetches. To give the models you already
have their plain names, without downloading anything:

```powershell
.\fetch-models.ps1 -Names -Group all
```

A settings file that already exists is never changed.

## Command line

Everything the window does can be run from a terminal. From the repository:
`.\.venv\Scripts\python.exe -m volis <option>`. From a ready-made folder: `volis.exe <option>`.

| Option | What it does |
|---|---|
| (none) | Opens the window. |
| `--report` | Lists every model found, and why any can't be used. |
| `--report --load` | Also loads each model in turn and prints where it runs and the memory it takes. |
| `--doctor` | Checks the installation: every library present, the right version, the graphics card visible. |
| `--devices` | Lists microphones and speakers, with the names `[audio]` takes. |
| `--listen` | Listens on the microphone and prints what it hears. `--seconds N` stops after N seconds, `--wav` saves each sentence, `--compare` runs every recognizer on each one. |
| `--translate "text" --from es --to en` | Translates one sentence. `--mt <id>` and `--prompt <name>` choose the translator and the prompt. |
| `--translate "text" --compare-mt <id>,<id>` | The same text through two or three translators, one loaded at a time, each with its time. Add `--reference "a translation you trust"` to score each against it (chrF, 0 to 100: closeness to that reference, not correctness). |
| `--print-prompt "text" --from es --to en` | Prints exactly what the translator would be sent. |
| `--file <path>` | Translates a recording. See below. |

### `--file`

```powershell
.\.venv\Scripts\python.exe -m volis --file talk.m4a --from es-MX --to en --fast
```

| Option | What it does |
|---|---|
| `--from`, `--to` | The languages. Default: the ones in `volis.toml`. |
| `--asr <folder>`, `--mt <id>`, `--prompt <name>` | The recognizer, translator and prompt, as `--report` lists them. |
| `--fast` | As fast as the models allow. Without it, the recording runs at playing speed. |
| `--export <folder>` | Where to write. Default: `exports\<file>-<date>\`. |
| `--no-translate` | Transcribe only. |
| `--streaming`, `--no-streaming` | Recognize while the speech goes on, or don't, for this run. |
| `--context off\|carry\|revision` | The context mode for this run. |
| `--no-hold` | Don't join short fragments to what follows. |
| `--glossary "Name, Term"` | Names and terms to keep exactly. |

What it writes:

| File | What it holds |
|---|---|
| `transcript.txt`, `translation.txt` | One sentence per line, side by side. |
| `source.srt`, `translation.srt` | Subtitles with timings. |
| `events.jsonl` | Everything that happened, in order. The first line records the models and settings used; the last is the summary. |

**Scoring a run.** Put a reference beside the recording, named after it:
`talk.m4a.ref.json` containing `{"transcript": "...", "translation": "..."}` (either may be left
out). The run then ends with the recognizer's error rate and the translator's score against
your text. This is how to compare two models on your own voice: see
[MODELS.md](MODELS.md#is-it-any-good).
