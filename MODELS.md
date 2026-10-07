# Models

Volis does its work with four kinds of model:

- a **speech detector** notices when someone starts and stops talking, so the rest get whole
  sentences. There is one (Silero VAD, 2 MB), it is required, and you never choose it;
- a **recognizer** turns speech into text;
- a **translator** turns that text into the other language;
- a **voice** says the translation aloud.

The last three are yours to choose.

Models are files in the `models` folder. Whatever is there is what Volis offers in its lists;
there is nothing to register. This page says which to start with, how to choose your own, and
how every model we tried scored.

- [A basic set that works](#a-basic-set-that-works)
- [Choosing your own](#choosing-your-own)
- [Getting models](#getting-models)
- [What we tested, and how it scored](#what-we-tested-and-how-it-scored)

## A basic set that works

A starting point for ordinary translation, by the memory on your graphics card. These are
general models: none is tuned for a region or dialect.

| | 8 GB card | 16 GB card |
|---|---|---|
| **Recognizer** | `whisper-large-v3-turbo` | `whisper-large-v3-turbo` |
| **Translator** | Gemma 3 4B | Gemma 4 12B |
| **Voice** | one Piper voice for each language you translate into | the same |
| **Speech detector** | Silero VAD (required with any set) | the same |
| **Graphics memory used** | about 4.5 GB | about 9.8 GB |
| **Left for other programs** | about 3.5 GB | about 6 GB |

```powershell
.\fetch-models.ps1 -Only silero_vad,lessac,es_MX-claude          # the speech detector, an English and a Spanish voice
.\fetch-model.ps1 openai/whisper-large-v3-turbo -Role asr
.\fetch-model.ps1 unsloth/gemma-3-4b-it-GGUF -Role mt -Include "*Q4_K_M.gguf"                    # 8 GB
.\fetch-model.ps1 unsloth/gemma-4-12b-it-GGUF -Role mt -Include "gemma-4-12b-it-Q4_K_M.gguf"     # 16 GB
```

For Arabic, add a voice: `.\fetch-models.ps1 -Only kareem`.

Why these:

- **`whisper-large-v3-turbo`** covers nearly every language. On our test recordings it made
  0.5% character errors in Spanish and 3.3% in Arabic.
- **Gemma 3 4B** scored 64.8 on our translation tests against 60.2 for the smallest translator
  we tried, never answered a question instead of translating it, and took under half a second
  a sentence.
- **Gemma 4 12B** had the best score of everything we tested (66.1), and the best Arabic.

Two things to know before relying on this table:

- **The 16 GB column is partly untested.** We measured Gemma 4 12B's translations, but only on
  an 8 GB card it doesn't fit, where it ran several times slower. Its speed on a card that
  holds it has not been measured. The Benchmarks button in the performance panel will tell you.
- **The tests are small.** They are enough to say one model is clearly better than another,
  not to separate models a point apart.

**If Arabic matters most on an 8 GB card:** Gemma 4 E4B translates Arabic clearly better than
Gemma 3 4B (71.3 against 67.7). With the same recognizer it uses about 7.3 of the 8 GB, which
leaves almost nothing for other programs.

All of this assumes the translator runs on the graphics card
([DEVELOPMENT.md](DEVELOPMENT.md#the-translator-on-the-graphics-card)). On the processor every
translator still works, several times slower.

## Choosing your own

The set above is a starting point. A model made for your language will usually do better than
a general one, and new models appear all the time. Most are published on
[Hugging Face](https://huggingface.co/models).

### A recognizer

Search Hugging Face for speech recognition in your language (the filter is *Automatic Speech
Recognition*). Volis can load:

| Kind | How to recognise it | Examples |
|---|---|---|
| Whisper and its fine-tunes | The files include `model.safetensors` and `config.json`, and the page says Whisper | `openai/whisper-large-v3-turbo`; search "whisper" with your language's name |
| Other speech models the `transformers` library supports | The same files; the page names wav2vec2, MMS, Cohere Transcribe or similar | `facebook/mms-1b-all` |
| Speech models in GGUF form | A `.gguf` file **and** an `mmproj-*.gguf` file beside it (the part that hears) | `ggml-org/Qwen3-ASR-0.6B-GGUF` |

What to look for on a model's page:

- **Your language is listed.** A fine-tune for one language usually beats the general model on
  that language, and is useless for any other.
- **What it was trained on.** A model trained on read speech hears a conversation less well
  than its scores suggest, and one trained on a different region's speech may mishear yours.
- **Its size.** On the graphics card a Whisper "large" takes about 1.6 GB; smaller ones are
  faster and less accurate.
- **Whether it writes punctuation.** Volis cuts speech into sentences at full stops. A model
  that writes none (MMS, for one) still works, with sentences cut at pauses instead.

### A translator

Any chat model in **GGUF** form works: Volis asks it to translate using the model's own chat
format, which is stored in the file. Search Hugging Face for the model's name with "GGUF".

- **Size.** A translator takes about its file size plus 15% of graphics memory. It has to fit
  beside your recognizer: on 8 GB that means a file of about 5 GB at most; on 16 GB, about 12 GB.
- **Which file.** A GGUF repository usually offers the same model at several levels of
  compression. `Q4_K_M` is the usual choice: about a third of the full size, with little loss.
  Every translator we tested is `Q4_K_M`.
- **Which model.** In our tests models of about 4 billion parameters were clearly better than
  smaller ones, and 12 billion were only a little better again except on Arabic. Models made
  only to translate (TranslateGemma) work too.
- **Languages.** A general chat model translates the languages it knows well. For a less
  common language, try a sentence before you trust it.

**Models made only to translate** (MADLAD-400, NLLB-200, OPUS-MT) work too, as they are
published: a folder with `config.json`, not a GGUF. They are not chat models: you give them
text and a language, and they give back the translation.

- They know which languages they have. Volis reads the list from the model and refuses a
  language it lacks, by name. Where a model has no entry for a regional variety (Iraqi Arabic,
  say), it translates as the plain language and says so beside the sentence.
- They translate each sentence on its own: they can't use earlier sentences, a glossary, or a
  dialect instruction.
- OPUS-MT models translate one pair each, one way. Keep the folder's published name
  (`opus-mt-fa-en`): that is how Volis knows the pair.
- **NLLB-200's licence (CC-BY-NC 4.0) allows non-commercial use only.** MADLAD-400 is Apache 2.0.

### A voice

Volis speaks with [Piper](https://github.com/rhasspy/piper) voices. Each speaks one language,
and some a particular accent.

- Ready to use: the `vits-piper-*` voices in the
  [sherpa-onnx releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models) and the
  `csukuangfj/vits-piper-*` repositories on Hugging Face.
- A voice published as Piper's own two files (`name.onnx` and `name.onnx.json`) works too:
  `fetch-model.ps1` converts it as it downloads.

### Will it fit?

Once a model is in the `models` folder, open **View > Performance** in the window and choose
the **What if** tab. Pick the recognizer, translator and voice you have in mind: it shows the
memory they need and whether they fit on your card as it is now, without loading anything.

Two models that don't fit together still run, but spill into ordinary memory and become
several times slower. That is the usual reason for Volis suddenly being slow.

### Is it any good?

Published scores don't tell you how a model hears *your* voice in *your* room. To find out:

1. **Listen.** In the window, tick **Compare recognizers** and speak: every recognizer you have
   transcribes the same sentence, side by side, with its timing.
2. **Measure.** Record yourself reading a page (two minutes is enough). Save what you read
   beside the recording, as described in [SETTINGS.md](SETTINGS.md#--file). Run the recording
   through file mode once with each model: each run ends with an error rate for the recognizer
   and a score for the translator, on your own voice.
3. **Time it.** The **Benchmarks** tab of the performance panel runs a recording through any
   combination and records how fast it was. Those results feed the What if tab from then on.

## Getting models

**One model** from Hugging Face, into the right folder:

```powershell
.\fetch-model.ps1 <owner>/<model> -Role asr                              # a recognizer
.\fetch-model.ps1 <owner>/<model> -Role mt -Include "*Q4_K_M.gguf"       # a translator: say which file
.\fetch-model.ps1 <owner>/<model> -Role asr -Include "*Q8_0.gguf"        # a GGUF speech model: the model and its mmproj file
.\fetch-model.ps1 <owner>/<model> -Role tts                              # a voice
```

Some models are *gated*: their page asks you to accept terms first. Do that in your browser,
then run `.\fetch-model.ps1 -Login` once.

**Every model on this page,** in one go:

```powershell
.\fetch-models.ps1 -List              # what is in place, what would be downloaded, how big
.\fetch-models.ps1                    # everything worth having: about 50 GB
.\fetch-models.ps1 -Group use         # only what suits an 8 GB card
.\fetch-models.ps1 -Only Qwen3-ASR    # only entries whose name contains this
```

It asks once before downloading, skips what you already have, and never overwrites a settings
file. One model on the list (Cohere Transcribe) is gated; without the login above, the rest
still download and the script says which one didn't.

**A model you got some other way:** put its folder in `models\asr\`, `models\mt\` or
`models\tts\`, keeping the files' names. Each translator goes in a folder of its own.

**Afterwards, always:**

```powershell
.\.venv\Scripts\python.exe -m volis --report
```

It lists every folder Volis found, and for any it can't use, the reason. If a model's language
or name is detected wrongly, a small settings file in its folder corrects it:
[SETTINGS.md](SETTINGS.md#settings-for-one-model).

## What we tested, and how it scored

Every model Volis has been run with, including the ones that weren't worth keeping.

The **Group** column is how the download script sorts them:

| Group | Meaning | Downloaded by default |
|---|---|---|
| `use` | tested on an 8 GB card and worth having | yes |
| `bigger` | tested, but too large for 8 GB; to be measured on a larger card | yes |
| `tested` | tested and not kept: a worse score, or only there to prove something works | no |

### How the numbers were measured

All on one laptop (RTX 4070, 8 GB), with the translator on the graphics card. They are small tests: read
them as "clearly better", "about the same" or "clearly worse", not to the decimal.

- **CER / WER** (recognizers): character and word error rate against the reference
  transcript, lower is better. "Clips" = 10 FLEURS clips a language (`scripts/transcribe.py`).
  "File" = one two-minute recording of FLEURS sentences through the whole pipeline
  (`scripts/p7_check.py`, `scripts/p11_check.py`). All of it is read speech in a quiet room:
  none of it says how a model hears *you*, or a dialect.
- **RTF**: time to transcribe divided by the length of the audio. 0.1 = ten times faster
  than speech.
- **chrF** (translators): overlap with the FLORES+ reference translation, higher is better.
  Ten sentences a language (`scripts/mt_bench.py`), so one or two points is noise.
- **obey**: of 24 sentences that tempt a chat model to answer instead of translate ("how do
  you say ...", "what is the capital of France"), how many were translated, alone / after two
  earlier sentences (`scripts/obey_check.py`).

### Recognizers

Folders ending in `-onnx-int8` are compressed to 8-bit and run on the processor, leaving the
graphics card free; the same model without that ending is the original, on the graphics card.

| Model | Group | Runs on | Disk | Spanish CER / WER | Arabic CER / WER | RTF | Notes |
|---|---|---|---|---|---|---|---|
| Gemma 4 E4B (Q4_K_M + audio encoder) | use | llama.cpp audio, GPU | 1.0 GB + the translator's file | 1.1% / 3.4% (file) | **1.5% / 6.5%** (file) | 0.08 | The best Arabic measured. The same file is the Gemma 4 translator; loaded as both it is in memory twice. No word timings. |
| Cohere Transcribe Arabic 07-2026 | use | transformers, GPU, 4.1 GB | 4.1 GB | not tested | 1.9% / 7.4% (file), 2.1% (clips) | 0.19 | Arabic and English only. Gated. The best dedicated Arabic recognizer measured. |
| Qwen3-ASR 0.6B (Q8) | use | llama.cpp audio, GPU | 1.0 GB | 1.6% / 6.0% (file) | 4.1% / 16.2% (file) | **0.02** | The fastest recognizer installed. No word timings. |
| whisper-large-v3-turbo-es (adriszmar) | use | transformers, GPU, 1.6 GB | 3.2 GB | **0.9% / 3.0%** (file) | Spanish only | 0.34 | The Spanish recognizer every check uses. |
| whisper-large-v3-turbo-arabic-dialectal (oddadmix), safetensors | use | transformers, GPU, 1.6 GB | 3.2 GB | Arabic only | 3.7% (clips) | not recorded | Tuned on dialects; the clips are Standard Arabic, so this test undersells it. Not yet tested on dialect speech. |
| MMS 1B (adapters: ar, en, fa, es) | use | transformers, GPU, 1.9 GB | 3.9 GB | 1.3% / 6.0% (file) | 5.8% (clips) | 0.04 | Never writes punctuation or capitals, so sentences are cut by pauses alone. The only one here with a Persian adapter besides Whisper. |
| `parakeet-tdt-0.6b-v3-onnx-int8` | use | sherpa-onnx, CPU | 0.7 GB | 0.5 to 1.9% (clips) | no Arabic | not recorded | Runs on the processor. Detects the language itself; spells numbers out. |
| `whisper-large-v3-turbo-onnx-int8` | use | sherpa-onnx, CPU | 1.0 GB | 0.6% / 2.1% (file) | 5.2% / 13.4% (file); no punctuation on any Arabic output | 0.41 (es), 0.52 (ar) | The general Whisper compressed to 8-bit, on the processor. |
| `whisper-large-v3-turbo` (OpenAI, as published) | use | transformers, GPU, about 1.6 GB | 1.6 GB | **0.5% / 2.1%** (file) | 3.3% / 12.0% (file) | 0.33 (es), 0.22 (ar) | The same model as the line above, uncompressed, on the GPU: the general recognizer to use, and the one for English. English not yet scored. |
| Qwen3-ASR 1.7B (Q8) | tested | llama.cpp audio | 2.5 GB | | | | Tried on another machine: not good so far. No figures recorded. Kept on the list for more testing. |
| Voxtral Mini 3B (Q4_K_M) | removed | llama.cpp audio | 3.2 GB | | | | The same: tried, not good, no figures. Not on the download list; `.\fetch-model.ps1 ggml-org/Voxtral-Mini-3B-2507-GGUF -Role asr -Include "*Q4_K_M.gguf","mmproj-*.gguf"` fetches it. |
| whisper-small | tested | transformers, GPU | 1.0 GB | not tested | 7.4% / 22.7% (file) | 0.13 | Clearly worse than everything above. Kept on the list only as the base of the adapter below. |
| whisper-algerian-darja-small (LoRA on whisper-small) | tested | transformers + peft | 0.1 GB | | 12.6% / 43.1% (file) | 0.13 | Proves that a LoRA adapter loads and is applied. Worse than its base on this recording, as expected: the recording is Egyptian read speech, the adapter is for Algerian. |

No word timings means the text can't be shown word by word while you speak; everything else
works.

### Persian

Ten Persian test clips (read news sentences), each sentence on its own. Recognition is the
character error rate; translation is chrF into English from the clips' correct text.

| Recognizer | Persian CER |
|---|---|
| MMS 1B | 4.2% |
| Gemma 4 E4B (audio) | 4.5% |
| Whisper large-v3-turbo | 6.6% |
| Qwen3-ASR 0.6B | 20.5% |

| Translator | Persian > English chrF |
|---|---|
| NLLB-200 1.3B | **70.2** |
| Gemma 4 12B | 67.5 |
| Gemma 3 12B | 66.8 |
| Gemma 4 E4B | 65.3 |
| TranslateGemma 12B | 64.6 |
| Gemma 3 4B | 64.3 |
| Aya Expanse 8B | 61.9 |
| TranslateGemma 4B | 61.5 |

Qwen3-ASR 0.6B is not usable for Persian. The Persian clean-up step (README, "Persian") made
no measurable difference to any of these on this test.

### Translators

Text only, against reference translations, with earlier sentences as context. All are `Q4_K_M`
GGUF files on the graphics card.

| Model | Group | Disk | es>en | ar>en | fa>en | en>es | mean chrF | obey | ms / sentence | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3 1.7B | use | 1.1 GB | 59.2 | 64.3 | 58.8 | 58.3 | 60.2 | 24 / 24 | **261** | The smallest and fastest, 3 to 6 chrF below the rest. The script puts it at the top of `models\mt\`, where it is the default. |
| Gemma 3 4B | use | 2.5 GB | **65.9** | 67.7 | 65.5 | 60.0 | 64.8 | 24 / 24 | 444 | The best all-rounder that fits 8 GB with a recognizer loaded. |
| Gemma 4 E4B | use | 5.0 GB | 64.3 | 71.3 | 63.8 | 60.9 | 65.1 | 24 / 23 | 586 | Clearly better Arabic than the other small ones. Also a recognizer (above). |
| TranslateGemma 4B | use | 2.5 GB | 64.2 | 66.9 | 65.9 | 60.0 | 64.3 | 23 / 24 | 511 | Trained only to translate. Its own prompt format: the prompt file and the glossary are not used. The one revision mode helps most. |
| Gemma 4 12B | bigger | 7.1 GB | 62.2 | **73.1** | 66.6 | **62.7** | **66.1** | 24 / 24 | 5909 * | The best Arabic and the best mean measured. |
| Gemma 3 12B | bigger | 7.3 GB | 63.1 | 70.3 | **66.9** | 60.5 | 65.2 | 24 / 24 | 9313 * | |
| TranslateGemma 12B | bigger | 7.3 GB | 62.3 | 68.4 | 64.9 | 61.2 | 64.2 | 24 / 24 | 8040 * | |
| Qwen3 8B | tested | 5.0 GB | 64.3 | 67.3 | 62.3 | 59.9 | 63.4 | 24 / 23 | 867 | No better than the 4B models and slower. |
| NLLB-200 1.3B | tested | 5.5 GB | 61.6 | 68.6 | **70.2** | 61.6 | 65.5 | 23 / n/a | 687 | Made only to translate, not a chat model: no earlier sentences, no glossary, no dialect wording. The best Persian measured, and it fits 8 GB. **Non-commercial licence.** |
| Qwen3 0.6B (safetensors) | tested | 1.5 GB | 58.8 on the Spanish file | | | | | | 1974 | Through transformers, not llama.cpp: proves that backend. Five times slower a sentence than a GGUF of a larger model. |

\* didn't fit the laptop's 8 GB card and spilled into ordinary memory. These times say nothing
about a larger GPU, which is why the three are in the `bigger` group: their quality is
measured, their speed is not.

What holds across the table: every model from 4B up is 3 to 6 chrF above Qwen3 1.7B, and the
12B models are not clearly better than the 4B ones except on Arabic.

### Voices

Voices have no score. Each was listened to, and each speaks through Volis.

| Voice | Group | Language | Disk | Notes |
|---|---|---|---|---|
| vits-piper-en_US-lessac-medium | use | English (US) | 64 MB | |
| vits-piper-es_MX-claude-high | use | Spanish (Mexico) | 67 MB | Chosen first for Spanish (Mexico). |
| vits-piper-es_ES-carlfm-x_low | use | Spanish (Spain) | 25 MB | |
| vits-piper-ar_JO-kareem-medium | use | Arabic, male | 64 MB | Mispronounces some words written without vowel marks, as every Arabic Piper voice here does. |
| arabic-emirati-female-model | use | Arabic (Emirati), female | 127 MB | Published as a raw Piper model, which sherpa-onnx can't load. The script converts it (below). MIT licence. |
| vits-piper-ar_JO-SA_dii-high | tested | Arabic, male | 64 MB | Works. **Its licence is non-commercial**; read its README before using it, which is why it isn't downloaded by default. |

The Arabic voices mispronounce some words, because Arabic is written without its short vowels.
The option **Add vowel marks to Arabic before it is spoken** runs a small model that restores
them first (`.\fetch-models.ps1 -Only tashkeel`, 10 MB). Its marks are good, not perfect.

### Where each comes from

| Model | Source |
|---|---|
| silero_vad.onnx, Parakeet, Whisper int8 | [sherpa-onnx ASR releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models) |
| English and Spanish voices | [sherpa-onnx TTS releases](https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models) |
| Qwen3 1.7B | [unsloth/Qwen3-1.7B-GGUF](https://huggingface.co/unsloth/Qwen3-1.7B-GGUF), saved as `qwen3-1.7b-q4_k_m.gguf` |
| whisper-large-v3-turbo-es | [adriszmar/whisper-large-v3-turbo-es](https://huggingface.co/adriszmar/whisper-large-v3-turbo-es) |
| whisper-large-v3-turbo-arabic-dialectal-hf | [oddadmix/whisper-large-v3-turbo-arabic-dialectal](https://huggingface.co/oddadmix/whisper-large-v3-turbo-arabic-dialectal) |
| cohere-transcribe-arabic-07-2026 | [CohereLabs/cohere-transcribe-arabic-07-2026](https://huggingface.co/CohereLabs/cohere-transcribe-arabic-07-2026) (gated) |
| mms-1b-all | [facebook/mms-1b-all](https://huggingface.co/facebook/mms-1b-all) |
| Qwen3-ASR 0.6B, 1.7B | [ggml-org/Qwen3-ASR-0.6B-GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-0.6B-GGUF), [ggml-org/Qwen3-ASR-1.7B-GGUF](https://huggingface.co/ggml-org/Qwen3-ASR-1.7B-GGUF) |
| Voxtral Mini 3B | [ggml-org/Voxtral-Mini-3B-2507-GGUF](https://huggingface.co/ggml-org/Voxtral-Mini-3B-2507-GGUF) |
| Gemma 4 E4B (translator and audio encoder), Gemma 4 12B | [unsloth/gemma-4-E4B-it-GGUF](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF), [unsloth/gemma-4-12b-it-GGUF](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF) |
| Gemma 3 4B, 12B | [unsloth/gemma-3-4b-it-GGUF](https://huggingface.co/unsloth/gemma-3-4b-it-GGUF), [unsloth/gemma-3-12b-it-GGUF](https://huggingface.co/unsloth/gemma-3-12b-it-GGUF) |
| TranslateGemma 4B, 12B | [mradermacher/translategemma-4b-it-GGUF](https://huggingface.co/mradermacher/translategemma-4b-it-GGUF), [mradermacher/translategemma-12b-it-GGUF](https://huggingface.co/mradermacher/translategemma-12b-it-GGUF) |
| Qwen3 8B, Qwen3 0.6B | [Qwen/Qwen3-8B-GGUF](https://huggingface.co/Qwen/Qwen3-8B-GGUF), [Qwen/Qwen3-0.6B](https://huggingface.co/Qwen/Qwen3-0.6B) |
| whisper-small, the Darja adapter | [openai/whisper-small](https://huggingface.co/openai/whisper-small), [touati-kamel/whisper-algerian-darja-small](https://huggingface.co/touati-kamel/whisper-algerian-darja-small) |
| Arabic voices | [csukuangfj/vits-piper-ar_JO-kareem-medium](https://huggingface.co/csukuangfj/vits-piper-ar_JO-kareem-medium), [vadimbelsky/arabic-emirati-female-piper](https://huggingface.co/vadimbelsky/arabic-emirati-female-piper), [csukuangfj/vits-piper-ar_JO-SA_dii-high](https://huggingface.co/csukuangfj/vits-piper-ar_JO-SA_dii-high) |

Each model has its own licence. Check it before you pass a copy on.

### Not measured yet

- Any recognizer on dialect speech with a reference to score against, on a noisy room, or on
  a real conversation. (One informal trial: Standard Arabic and Iraqi dialect speech gave the
  same translations.)
- The 12B translators' speed on a GPU they fit.
- Streaming and shared machine mode with a GGUF speech model, with figures. (Both were tried with Gemma 4 E4B and
  Qwen3-ASR on another machine: they work.)
- A trained (not synthetic) LoRA adapter on a translator.
