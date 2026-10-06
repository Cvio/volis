# Instructions: volis, the next features (P13 to P20)

For Claude Code, in the volis repo (`D:\AI_Data\projects\volis`). P0 to P12 are done. This file
adds eight milestones. Each one makes the app better for the people it's meant for:
**non-technical users who want to talk to a friend or colleague and have no interpreter.**

Read this whole file before writing any code. Then read `CLAUDE.md`, `HANDOFF.md`,
`SETTINGS.md` and `MODELS.md`, and the modules each milestone names.

---

## How to work on this

- `CLAUDE.md`'s rules all still apply: offline at runtime, no separate services, one path
  function, everything inside the app folder, new settings in `volis-python.toml` (never
  `volis.toml`), tests passing at every commit.
- **Build in the milestone order below. Stop after each milestone,** show its check passing, and
  wait for the user to say go on.
- **Before P13, summarise back** what you understood of all eight milestones, and list anything
  in this file that conflicts with the code as it is. This file was written from reading the
  code, not from running every path in it.
- **Verify before you rely.** Where this file says "verify" (beam search alternatives, seq2seq
  model classes, language codes), check the installed library's behaviour and report it before
  building on it.
- **The window's logic stays out of Qt,** as now: new state goes in `gui/session.py` or a new
  Qt-free module, with tests. Qt only draws it.
- Record every new setting in `SETTINGS.md`, every user-facing change in `README.md` (plain
  words), and every milestone in `HANDOFF.md`.

## Who this is for

Every decision in the window below follows from this. A typical user opens volis, picks two
languages, presses Start and talks. They don't know what a recognizer or a GGUF is, and they
shouldn't need to. Everything technical stays **available**, but out of the way.

---

## P13 — Rescan models and devices without restarting

**Why:** adding or fixing a model (say, re-downloading a broken folder) currently means closing
and reopening the app. volis-rust has a rescan. volis never got one.

- A **Rescan** button, plus `F5` and a menu entry under *View*.
- It re-runs model discovery for recognizers, translators and voices, and re-lists microphones and
  speakers. Every dropdown updates. New entries appear, removed ones disappear, and broken ones
  show their reason, as `--report` does.
- **While stopped:** if the currently selected model or device is gone, select the best
  remaining match (the same ranking as now), and show one plain line saying what changed and why.
- **While running:** Rescan is allowed for devices and lists, but never unloads a model in use.
  Changes to the selection apply at the next Start.
- Models already loaded stay loaded.

**Check:** with the app open and stopped, add a model folder and press Rescan. It appears. Rename
it and press Rescan. It disappears, and if it was selected, the line says so. Plug in a headset
and press Rescan. It appears in both device lists.

---

## P14 — The window, for non-technical users

Eight changes to `gui/window.py`. Make a screenshot before and after (`scripts/window_check.py`
already renders the window offscreen) and put both in `HANDOFF.md`.

1. **Basic and Advanced.** The visible settings are only:
   - the two languages, with a **swap button** between them (item 3);
   - the recognizer and the translator;
   - the microphone and the speakers, each with a **Test** button (item 6);
   - "Speak translations" on or off;
   - the mode: take turns, continuous, or shared machine.

   Everything else goes in an **Advanced** section that starts closed and remembers whether the
   user opened it: half-duplex, vowel marks, comparing recognizers, streaming, context, revision,
   hold-speech, fragment joining, glossary, pairing.
2. **A conversation view while running.** Nothing can be changed while a conversation runs, so
   once Start is pressed, the settings fold away into a slim bar showing the two languages and
   the two models. The transcript takes the space, with larger text. A text-size control
   (A− / A+) is kept in that bar and remembered.
3. **Swap languages:** a ⇄ button between "Spoken" and "Translate into" swaps them in one click.
   It isn't needed in shared mode, where each side has its own language.
4. **Plain model names.** Dropdowns show a short, readable name ("Whisper turbo — many
   languages", "Gemma 4 E4B — good for Arabic"), and the technical details (folder, file,
   quantization, backend, size) go in a tooltip that appears on hover. The name comes, in order,
   from:
   - the model folder's `volis-python.toml` `name`;
   - the recommendations file (P20), if it exists by then;
   - a cleaned-up folder name: strip `-GGUF`, quantization tags and file extensions, and replace
     dashes with spaces.

   `fetch_models.py` writes a plain `name` for every model it downloads.
5. **Start and Stop is the big control.** A large button whose label and colour show the state
   (*Start* / *Listening… press to stop* / *Paused*), with the shortcut key written under it.
   This replaces the small Start button next to the large "STOPPED" banner.
6. **Test buttons.**
   - **Test speakers** says a short sentence in the target language through the chosen speakers
     and voice.
   - **Test microphone** records 3 seconds, shows the level while recording, then plays it back
     and shows what the recognizer heard.

   They're disabled while running.
7. **Say why something is greyed out.** Every disabled control has a one-line reason, as a tooltip
   and as small text beside it. For example: "Needs 'Revise earlier translations'".
8. **A warning before it won't fit.** Using the estimates the performance panel already has, show
   a warning next to the recognizer and translator when the chosen combination likely won't fit
   in memory, or will be too slow for conversation, **before** Start is pressed. One plain
   sentence, with the numbers in the tooltip.

**Check:** the before and after screenshots. A first-time user, the user's own test, can choose
languages and start a conversation without opening Advanced. Every disabled control explains
itself. The tests for `gui/session.py` cover the new states.

---

## P15 — Type or paste text to translate

**Why:** for noisy rooms, names, addresses and numbers; and to test a translator directly, for
example against Google Translate, without speaking.

- A **text box** below the transcript: type or paste, press Enter or **Translate**. It uses the
  current languages and translator, and the result is added to the transcript as a row marked as
  typed. "Speak translations" applies.
- **Several lines** at once: each line becomes its own row.
- **Compare mode** (a checkbox by the box): the text goes through 2 or 3 chosen translators, side
  by side, with the time each took and its device (GPU or CPU). Translators load on demand, one
  at a time if they don't fit together, as `--compare` does for recognizers.
- **Reference:** an optional second box for a reference translation (Google's, or a person's).
  Each translator's output is scored against it with chrF, the same scoring as file mode
  (`scoring.py`). The page says plainly that the score shows closeness to that reference, not
  correctness.
- Typed rows are exported and logged like spoken ones.
- Command line, already there: `--translate`. Add `--compare-mt <id,id,...>` for the same compare
  mode from a terminal.

**Check:** a Persian, an Arabic and a Spanish sentence, each through two translators with a
reference, show both outputs, the scores and the timings.

---

## P16 — The Persian clean-up step

**Why:** Persian recognition is often good while the translation comes out odd. Three things in
the recognizer's text can mislead a translator. A clean-up step between recognition and
translation fixes the first two. The third is a model question (P17).

1. **Arabic look-alike letters.** Arabic ي and ك become Persian ی and ک. Also Arabic ة and ۀ
   forms where the Persian standard differs. Use a published normalisation table, and name the
   source in the code.
2. **The half-space (zero-width non-joiner, U+200C).** Persian joins word parts with it:
   می‌خواهم ("I want") is one word. Recognizers often write a normal space (می خواهم) or nothing at
   all (میخواهم). Repair the standard cases:
   - the prefixes می / نمی before a verb;
   - the plural ها / های;
   - the comparatives تر / ترین;
   - the possessive and pronoun endings after a word that ends in ه.

   Use a published rule set, for example the one in the `hazm` library's normalizer. Either use
   `hazm`'s normalizer directly, if it installs cleanly in this environment with no network at
   runtime and no large dependencies, or port its rules, with the source named. Report which
   before building on it.
3. **Digits and punctuation:** Arabic-Indic and Persian digits stay as they are in what's shown,
   but are handled consistently. Keep the original text, so nothing the user sees is silently
   altered.

**Where it runs:** on recognized and typed Persian text, after the hallucination guards and before
translation, when the source language is `fa`. The transcript shows the cleaned text, with the
original in a tooltip. Setting: `[text] persian_cleanup = true` in `volis-python.toml`, on by default.

**Measure it.** The Persian FLEURS fixtures already have aligned English references. Run each
installed recognizer and translator on them with the clean-up off and on, and report chrF both
ways in `HANDOFF.md`. If it makes things worse anywhere, say so and keep it switchable.

**Check:** unit tests for each rule, with real examples. The measurement above.

---

## P17 — Seq2seq translators: MADLAD, NLLB and similar

**Why:** dedicated translation models often translate languages like Persian better than small
chat models, because translation is all they were trained for. volis lists them as unusable
today, because every translator backend expects a chat model.

**What they are:** models that take text in one language and produce its translation, with no
chat format and no instructions. The language is chosen by a code:
- **MADLAD-400** (T5): a prefix token on the input, like `<2fa>` for "into Persian";
- **NLLB-200** (M2M100): a source-language setting, and the target language forced as the first
  output token, with codes like `pes_Arab`, `arb_Arab` and `acm_Arab` (Mesopotamian, that is,
  Iraqi, Arabic);
- **Marian / OPUS-MT:** one model per language pair.

**Build:**

- **Discovery:** a folder in `models\mt\` with a `config.json` whose `model_type` is a text
  seq2seq family (`t5`, `mt5`, `m2m_100`, `marian` and the like). **Check the class:** a
  *text*-to-text model, never a *speech* seq2seq model, which belongs to recognizers. List it in
  `--report` with its family and the languages it supports.
- **A new backend, `seq2seq`,** in `translate/seq2seq.py`, through `transformers`
  (`AutoModelForSeq2SeqLM`). It implements the existing `Translator` interface, and outputs go
  through the same cleaning and the guards that apply: empty, echo and too-long. The "recited the
  prompt" guard doesn't apply, since there's no prompt.
- **Language codes:** a table per family, mapping volis's tags and varieties to the model's
  codes. For example, NLLB `ar-IQ` → `acm_Arab`, `ar` → `arb_Arab`, `fa` → `pes_Arab`. **Verify
  every code** against the model's own tokenizer or config, and refuse, with a clear message, a
  language the model doesn't have. A variety the model lacks falls back to its base language,
  with a note in the transcript row ("translated as Arabic: this model has no Iraqi").
- **What it can't do,** said plainly in the window and `SETTINGS.md`: no context from earlier
  sentences, no glossary in the prompt, no dialect instruction. Each sentence is translated on
  its own. The glossary still works as an **after-check** (P19), flagging a translation that
  didn't use a glossary term.
- **Memory:** check it fits before loading, as other backends do. MADLAD 10B won't fit on 8 GB.
  MADLAD 3B and NLLB 1.3B should. GPU in float16, otherwise CPU.
- **Faster versions, verify first:** CTranslate2 conversions (int8) of NLLB and MADLAD exist and
  run much faster on the CPU. If the `ctranslate2` package installs cleanly and runs in-process,
  add it as a second path for the same models (folders containing `model.bin` and a CTranslate2
  config). Otherwise, report that and skip it.
- `fetch_models.py` learns to fetch `google/madlad400-3b-mt` and
  `facebook/nllb-200-distilled-1.3B` into `models\mt\`, with a `volis-python.toml` giving a plain
  name. Note in `MODELS.md` that NLLB's license is non-commercial.

**Check:** both models translate the Persian and Arabic fixtures, from text (P15's compare mode)
and from a file. Add their chrF to `MODELS.md` next to the Gemma models, with the Persian
clean-up on.

---

## P18 — Help, in plain words

- A **Help** button and menu. Pages open inside the app (`QTextBrowser`), work offline, and
  live in `help\` as plain files that are easy to edit.
- **Writing rules:** very simple words, short sentences, one idea per line, one picture per step.
  Written for someone who has never used a translation app. No model names except where the
  user chooses a model, and no technical terms without a plain explanation.
- **Pages:**
  - What volis does, in four pictures;
  - Your first conversation;
  - Taking turns, Continuous and Shared machine: what each is for, and when to use it;
  - Pairing two computers;
  - Translating a recording;
  - Headsets or speakers;
  - Typing a sentence;
  - What every option in Advanced does;
  - When something goes wrong.
- **A small ? beside each option** opens its explanation.
- **Pictures are made automatically** from the real window: a script (extend
  `scripts/window_check.py`) puts the window in each state offscreen, takes the screenshots
  into `help\images\`, and `build.ps1` runs it. Hand-made screenshots go out of date after the
  next change. These can't.
- Arabic and Persian examples in the pictures display right to left.

**Check:** every page opens offline, every picture is current, and a ? opens the right page. The
user reads the first-conversation page and can follow it without help.

---

## P19 — Alternatives, corrections, glossaries and the phrasebook

The biggest milestone. Split it into P19a to P19d and stop after each.

### P19a — Alternatives for a transcript

Click a transcript cell (what was heard) to open a panel that shows:

- **The audio** of that sentence, with a Play button.
- **Other readings:**
  - **Whisper-type recognizers** through `transformers`: the next-best readings, from beam search
    with several returned sequences (**verify** with the installed `transformers`: `num_beams`
    and `num_return_sequences` on generation).
  - **llama.cpp audio models:** two or three readings by sampling.
  - **sherpa-onnx models (greedy only):** none, so say so.
- **A second opinion:** the same audio heard by the **checker recognizer**, chosen in Advanced per
  language. For example, Cohere Transcribe checks Arabic. Loaded on demand, with a "Checking…"
  status, unloaded afterwards if memory is short.
- **An edit box** to type the correction.

Choosing any of them replaces the transcript, translates it again (with the same context), and
speaks it again if voice is on.

### P19b — Alternatives for a translation

Click a translation cell to open a panel that shows:

- **2 or 3 alternatives** from the current translator, by sampling with different settings.
  Seq2seq models produce them with beam search.
- **A second opinion** from the **checker translator** (Advanced, per language pair), loaded on
  demand.
- **Under each alternative, its back-translation**: the alternative translated back into the
  speaker's language by the current translator, so someone who can't read the target language can
  judge the meaning. Shown in smaller grey text.
- Which model produced each one.

Choosing one replaces the translation, and speaks it again if voice is on.

**Memory:** the checker models are bigger than the everyday ones. Loading on demand, with a
visible status, is acceptable here. This is for fixing, not for every sentence. Refuse plainly if
it can't fit at all.

### P19c — The corrections log

Every choice made in P19a and P19b is saved, in `userdata\corrections.jsonl`, one line each:
- the date, the language pair, the mode, and the models used;
- the original transcript, the alternatives offered, and the one chosen or typed;
- the original translation, the alternatives offered, and the one chosen;
- a copy of the sentence's audio, in `userdata\clips\<id>.wav`.

**This is training data.** Corrected audio and transcript pairs are what the Whisper LoRA
pipeline needs, and corrected translations are what the translator LoRA needs. Add an export:
**File → Export corrections…** writes them as:
- a Parquet file with `audio`, `text` and `language` for recognizer training;
- a JSONL file of `source`, `target`, `source_lang` and `target_lang` for translator training.

These are the formats `model-converter`'s train-and-convert app takes.

**Privacy, stated in the window and `README.md`:** saved clips are recordings of people. A setting,
`[corrections] save_audio`, on by default, turns audio saving off. The log never leaves the
computer.

### P19d — Glossaries and the phrasebook

**Glossaries:** files in `userdata\glossaries\`, one per topic (`medical.toml`, `names.toml`), each
listing **terms with their fixed translations** per language pair:

```toml
[[term]]
source = "presión arterial"
source_lang = "es"
targets = { en = "blood pressure" }
```

- The window's Advanced section has a list of glossary files with tick boxes. The ticked ones are
  active for the session, and the choice is remembered.
- **For chat translators:** when an active term appears in the source text, the prompt is told
  "translate *X* as *Y*". This extends the existing glossary line in `translate/context.py`. Plain
  names with no translation keep today's meaning: keep exactly.
- **After every translation, by any backend:** if a term appeared in the source and its fixed
  translation isn't in the output (after the language's text cleaning), the row is **flagged**,
  with the term in its tooltip.
- **From the panels:** select words in a source and its translation → **Add to glossary** → choose
  the file.

**The phrasebook:** files in `userdata\phrasebook\`, one per language pair. Each entry is a
sentence with its checked translation:

```toml
[[phrase]]
source = "Where does it hurt?"
source_lang = "en"
targets = { "ar-IQ" = "وين يوجعك؟" }
checked_by = "native"     # "native" or "me"
note = ""
audio = ""                # optional: a recording by a native speaker, in phrasebook\audio\
```

- **A Phrasebook panel:** searchable, grouped by topic. Tap an entry to show and **speak** its
  checked translation, through the recording if there is one, otherwise the voice. It never goes
  through a translator.
- **Automatic use:** when a recognized sentence closely matches a phrasebook entry (similarity
  after text cleaning at least `[phrasebook] match = 0.9`), the checked translation is used in
  place of the model's, and the row shows ✓. **Only `checked_by = "native"` entries are used
  automatically.** `"me"` entries are offered as a suggestion beside the model's translation.
- **From the panels:** **Add to phrasebook** saves the chosen sentence and translation as
  `checked_by = "me"`. A native speaker can later mark it `"native"`, in a review list in the
  Phrasebook panel.
- The files are plain text, made to be copied between team members.

**Check for P19:** a sentence misheard on purpose, fixed through each panel, ends up corrected in
the transcript, re-spoken, and logged. The corrections export produces both files, and the
training app's data loader opens them. A glossary term that a translator ignores gets flagged. A
native-checked phrase spoken into the microphone is replaced by its checked translation, with ✓.

---

## P20 — Tutorials and model advice

### Tutorials

A guided walk-through per mode: first run, taking turns, shared machine, pairing, translating a
file. Each step highlights the real control and waits for the user to do it ("Step 2 of 5:
choose the language your friend speaks"), with **Skip** and **Back**. The same plain-words rules as
the help pages. Offered once at first start, then always available from Help.

### Model advice, for what's installed

- **`config\recommendations.toml`**, maintained by hand from `MODELS.md`'s test results: per model
  (folder name and Hugging Face id), per language and role, its score, a plain-words reason, and
  the plain name P14 uses.
- **An advisor** (a Qt-free module, with tests) looks only at the models actually installed and
  recommends, per language: the recognizer, the translator and the voice. In shared mode, per
  side. Its reasons, in order of trust:
  1. tested: "best on Arabic speech in our tests";
  2. what the model says about itself: "tuned for Mexican Spanish", using the variety ranking
     volis already has;
  3. "not tested, may work".
- **Where it shows:**
  - a **Recommended** marker in each dropdown;
  - a **Use recommended** button that sets everything in one click;
  - a warning when a choice is clearly wrong, such as an English-only recognizer for the Arabic
    side.
- **The help and tutorials use it,** so a page can say "for your Arabic speaker, choose *Whisper
  turbo Arabic*", naming only models that are installed.

**Check:** with two Whisper models installed, one general and one Arabic-tuned, the advisor
recommends the Arabic one for the Arabic side and the general one for English, and says why.
**Use recommended** sets both. The shared-machine tutorial runs from start to finish.

---

## Not in this file, but noted for later

These came up, and were deliberately left out of this round. Record them in `HANDOFF.md` under
"Later":
- translating the computer's own sound (loopback capture), with an always-on-top caption window;
- a replay button per row;
- speaker labels in file mode (sherpa-onnx speaker diarization);
- a full-screen "show the other person" view;
- automatically saving every live session as a transcript, if export doesn't already cover live
  sessions. **Check and record which.**
