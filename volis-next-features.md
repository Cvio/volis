# The plan: features not built yet (P18 to P20)

Each one is for **non-technical users who want to talk to a friend or colleague and have no
interpreter.** They shouldn't need to know what a recognizer or a GGUF is. `CLAUDE.md`'s rules all
apply. Written before the current window: where it says Advanced, read the Developer settings page,
and where it says a cell, read a bubble.

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
  `scripts/app_shots.py`) puts the window in each state offscreen, takes the screenshots
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

## Notes for P19d, on hold

**Automatic phrasebook use:** the 90% rule above is wrong in both directions. "Could I see the menu,
please?" scores 88% against "Can I see the menu, please?" and misses, while "Can **we** see the
menu, please?" scores 94% and passes. Proposed: use a stored translation automatically only on an
exact match, ignoring punctuation and capitals; let one entry list several wordings; show a near
match as a suggestion beside the model's translation.

**Kinds of glossary entry:** a word with two meanings can't be a fixed entry. Persian منو is "menu"
and, far more often, the everyday "me". Proposed: add a *hint* ("X can also mean Y here"; chat
translators only) and a *watch word* (show both readings and let a person choose). Whether a hint
works is untested.

**Not yet answered by the user:** the setting this is for, whether the speakers are from Iran or
Afghanistan, who can check terms, and one row per term or a list per language pair.
