# Volis: an overview

What Volis is, what it does well today, what it is still growing into, and what it takes to run
it. Written for people deciding whether and how to use it. To install and use it, see
[README.md](README.md).

## In one paragraph

Volis is a speech translator that runs entirely on one Windows computer. A person speaks; Volis
writes down what they said, translates it, shows both on the screen, and says the translation
aloud in the other language. Once it is installed it needs no internet connection at all, and
nothing said in the room is sent anywhere. It is built first for **Arabic**, both Modern
Standard Arabic and spoken dialects, and for **Farsi (Persian)**, with English and Spanish
alongside. It also translates recordings and typed text, and it includes tools for testing which
translation models work best and for checking what a computer can handle.

![A conversation in progress: Farsi on the left, English on the right](docs/images/overview-conversation.png)

## Why it exists

Many conversations that need a translator can't use the usual tools:

- **The conversation is sensitive.** Online translation apps send the audio to a company's
  servers. For a medical history, a legal matter, a case file or a personnel issue, that may not
  be acceptable. Volis keeps every word on the computer in front of you.
- **There is no reliable internet.** A field site, a basement office, a vehicle, a building with
  poor reception. Volis works the same with the network cable unplugged.
- **An interpreter isn't available for every conversation.** Volis can cover the routine
  exchanges at a front desk or in an intake interview, and it is available at any hour.
- **Cost and control.** There is no per-minute fee and no subscription. The organisation chooses
  which AI models it runs and can test them itself, on its own recordings.

Volis is a help, not a certified interpreter. Machine translation makes mistakes (see
[Limits to know](#limits-to-know)). For consent, diagnosis, legal statements and similar
moments, a qualified interpreter is still the right choice.

## How it works

Every sentence goes through four steps, each done by a separate AI model running on the computer:

| Step | What happens | The model that does it |
|---|---|---|
| 1. Listen | Volis notices when someone starts and stops speaking. | The speech detector |
| 2. Write down | The speech becomes text in the speaker's language. | The **recognizer** |
| 3. Translate | The text is translated into the other language. | The **translator** |
| 4. Speak | The translation is read aloud. | The **voice** |

The models are separate files that can be swapped, much as you would change a printer driver.
New and better models appear every few months; Volis can use them without being rebuilt, and it
includes tools to test them (see [Model benchmarking](#model-benchmarking-the-test-bench)).

**Speed.** With models that fit the computer's graphics card, writing a sentence down takes a
fraction of the time it took to say, and translating it takes about half a second. In our
measured runs the translation began to be spoken within about two seconds of the speaker
finishing.

## Current focus: Arabic and Farsi

| Language | Understands speech | Translates | Speaks aloud | How well tested |
|---|---|---|---|---|
| **Arabic, Modern Standard** | Yes | Yes | Yes | Measured on test recordings; tried in live conversations |
| **Arabic, Iraqi** | Yes | Yes, in Iraqi wording | Yes, with a standard Arabic voice | Tried in live conversations; not measured |
| **Farsi (Iranian Persian)** | Yes | Yes | **Not yet** | Measured on test recordings |
| **English** | Yes | Yes | Yes | In daily use; not measured |
| **Spanish** (Mexico, Spain) | Yes | Yes | Yes | Measured on test recordings |

### Arabic

- **Standard and dialect.** You tell Volis which Arabic is spoken and which is wanted. Iraqi and
  Jordanian Arabic are named choices today; anything else is treated as Arabic in general.
  When the translator is asked for Iraqi Arabic, it is told to write the way Iraqis speak. If a
  translation model has no Iraqi of its own, it writes standard Arabic and says so beside the
  sentence.
- **Recognition.** On our test recordings of people reading standard Arabic, the best
  recognizers got about one or two letters in a hundred wrong. In a trial on another computer,
  the same sentences spoken in standard Arabic and in Iraqi Arabic gave the same English
  translations.
- **Voices.** A male Arabic voice (Jordanian) and a female Emirati voice are available. Arabic is normally written without its short vowels, which makes any voice
  mispronounce some words. An option adds the vowel marks before a sentence is spoken. Its marks
  are good but not perfect, and no Arabic speaker has yet judged whether they make the voices
  clearer.
- **A recognizer tuned on Arabic dialects** is available. It has not yet been tested on dialect
  speech.

### Farsi (Persian)

- **Recognition.** On test recordings of people reading news sentences, the best recognizers got
  about four to five letters in a hundred wrong.
- **Translation.** A translation-only model (NLLB-200) scored best on those news sentences.
  Everyday spoken Farsi has proved harder (see the case below), and testing on it is the next
  step.
- **A clean-up step** tidies Farsi text before it is translated: letters that look the same in
  Arabic and Farsi but are different characters, and the "half-space" that joins the parts of a
  Farsi word.
- **Speaking Farsi aloud is not available yet.** No Farsi voice has been tested. Today, speech in
  Farsi is translated and spoken in English, Arabic or Spanish, and translations *into* Farsi are
  shown on the screen as text.
- **Variety.** The models are trained mostly on Iranian Persian. Afghan Dari has not been tested.

### Other languages

German, French, Italian, Portuguese and Russian are named in Volis, and the recognizers and
translators cover many more. Each language spoken aloud needs a voice for it.

## Ways to use it

![The main window before a conversation starts](docs/images/overview-main-window.png)

### Live conversation

Pick a mode; you can change it while a conversation is running.

| Mode | How it works | Suits | Status |
|---|---|---|---|
| **Take turns** | Press a key, speak, press it again. Only then is the speech translated. | Most meetings: nothing is picked up by accident. | Ready |
| **Listen continuously** | Hands-free. Every pause ends a sentence. | One person speaking at length. | Ready |
| **Shared machine** | Two people at one computer, each with their own key and language. What one says is spoken in the other's language. | Across a desk or a counter. | Built; not yet tried by two people |
| **Pair two computers** | Each person has their own computer. Each translates its own person's speech and sends the text to the other over the local network, never the internet. | Two rooms, or a little distance. | Built; not yet tried on two real computers |

During a conversation the settings fold away and the text fills the window, in a size you can
adjust. Arabic and Farsi are laid out right to left. Microphone and speaker **Test** buttons check
the sound before you start.

### Recordings

Open an audio file (WAV, MP3, M4A, FLAC, OGG or Opus) and Volis transcribes and translates it.
Each sentence becomes a row; click a row to hear that part of the recording. It can run at
normal speed or as fast as the computer allows. **Export** saves the transcript, the translation
and subtitle files. Useful for recorded interviews, voicemail and statements.

### Typed text

A box under the conversation translates typed or pasted text, and speaks it if speech is on. It
helps with names, addresses and numbers, and in a room too noisy for speech. It works during a
conversation as well, and the typed line is translated with the conversation's context.

## Quality and safeguards

- **Errors caught before anyone hears them.** AI recognizers sometimes "hear" stock phrases in
  silence ("Thanks for watching"). Translators sometimes answer a question instead of translating
  it, hand the sentence back unchanged, or ramble. Volis drops those sentences rather than show
  or speak them, and says why.
- **Earlier sentences as context,** so words like "he", "she" and "it" come out right.
- **Revision.** A short sentence whose meaning only becomes clear from the next one is corrected
  on the screen.
- **Names and terms to keep exactly,** entered as a short list for the session.
- **The microphone is muted while Volis speaks,** so it doesn't translate itself. (Not needed with
  a headset.)
- **The Farsi clean-up and the Arabic vowel marks** described above.

## Model benchmarking: the Test bench

AI models improve quickly, and a model that tops a published league table may not suit your
speakers, your vocabulary or your computer. The Test bench (View > Test bench) lets a team member
compare models on their own material, without technical help. It answers three questions:

| Tab | The question | What you give it | What you get |
|---|---|---|---|
| **Recognizers** | Which one hears our speakers best? | A recording made on the spot, or an audio file. Optionally, what was really said. | What each one wrote, how long it took, the memory it needed, and how many letters and words it got wrong. |
| **Translators** | Which one translates our sentences best? | Typed or pasted text, or a recording. Optionally, a translation you trust. | Each translation side by side, its time, and how close it came to the trusted one. |
| **Whole set** | Will this combination run on this computer? | A recognizer, a translator and a voice. | Whether they fit in memory together (worked out without loading anything), and a button that times them on a recording. |

![The Test bench comparing translators](docs/images/overview-testbench-translators.png)

Every comparison is kept and can be copied as a table into a report. Any model in it can be
made the conversation's choice: click its row, then **Use in the conversation**. A record of every model tested so far, with its
scores, is in [MODELS.md](MODELS.md).

**How to read the scores.** For recognizers, fewer wrong letters is better. For translators, the
score (0 to 100) shows how close a translation is to the one you trusted. A high score means
"close to that wording", not "correct": a good translation in different words scores lower. The
scores are a guide for comparing models; reading the translations is still the real test.

### A case from testing: why your own sentences matter

Asked to translate the everyday Farsi for "Can I look at the menu, please?", all nine translators
we tried got it wrong. Most said "Can I see you, please?". The Farsi word for "menu" is spelled
exactly like the everyday word for "me", and every model chose "me". Spelling the sentence more
formally got "menu" from two of the nine. Changing "menu" to "food menu" fixed it for all nine.
Putting a restaurant sentence before it fixed it for two, while three of the smaller models
invented words instead ("my order", "my reservation").

None of this shows up in published scores, which are measured on formal text. A few minutes in
the Test bench with your own phrases does show it.

## Machine performance

Volis runs on the computer's graphics card, and the models must fit in its memory. Three things
help plan for that:

- **A warning before starting.** If the chosen recognizer and translator won't fit together,
  an orange line under them says so, before anything is loaded.
- **The Whole set tab** of the Test bench shows how much memory a combination needs and how
  much is free, keeps every timed run on that computer, and so helps decide what hardware to buy.
  On a laptop with an 8 GB graphics card, the recommended basic set uses about 4.5 GB and leaves
  about 3.5 GB for other programs. A 16 GB card can run larger models, which translate somewhat
  better.
- **The performance panel** (View > Performance) shows, while a conversation runs, how much of
  the graphics card, memory and processor Volis and other programs are using, how long each
  sentence took at each step, and whether Volis is keeping up with the speaker. It turns amber or
  red when memory is nearly full or speech is falling behind. Useful when Volis has to share the
  computer with, say, a video-call program.

![The Whole set tab: whether a combination fits, and every run measured on this computer](docs/images/overview-testbench-whole-set.png)

## Privacy and data

- **No internet after installation.** No cloud service, no account, no usage reporting. Pairing
  two computers uses the local network only.
- **What stays on the computer:** the settings; a log of each session, which includes what was
  said and how it was translated; anything you choose to export; and the Test bench's results.
  Treat the computer as holding sensitive records, and delete the logs as your policy requires.
- **Live conversations are not recorded as audio.** A recording made in the Test bench is held
  in memory only, until Volis is closed.

## What it needs

| | |
|---|---|
| **Computer** | Windows 10 or 11, 64-bit |
| **Graphics card** | NVIDIA, with 8 GB of memory or more (16 GB for the largest models) |
| **Disk** | About 6 GB for the program, plus the models: about 15 GB in all for a basic set |
| **Sound** | A microphone and speakers; a headset works best |
| **Not supported** | Mac, Linux, and computers without an NVIDIA graphics card |

There are two ways to install it:

- **A ready-made folder.** The program and its models are copied onto the computer as one folder.
  Nothing else is installed except the graphics card's driver, and no internet is needed. This
  is the way to give Volis to people who will only use it. (Being verified on a second computer.)
- **Full setup** for whoever maintains Volis: about an hour, with an internet connection, as
  described in [README.md](README.md).

## Model licences

Each model has its own licence, and some of the best ones forbid commercial use. Before using
Volis commercially, have the licences reviewed. Read from the models' own descriptions:

| Licence | Models |
|---|---|
| Free for commercial use (MIT, Apache 2.0) | Whisper (recognizer); Gemma 4 (recognizer and translator); MADLAD-400 (translator); Cohere Transcribe Arabic (recognizer; you must accept its terms to download it); Silero (the speech detector) |
| The maker's own terms (Google's Gemma terms, which allow commercial use under a use policy) | Gemma 3 and TranslateGemma (translators) |
| **Non-commercial use only** (CC BY-NC 4.0) | NLLB-200 (translator, the best on Farsi news so far); MMS (recognizer); Aya Expanse (translator); one of the Arabic voices |

The voices each carry their own licence; [MODELS.md](MODELS.md) lists where every model comes
from.

## Where it stands today

| Ready | Built, awaiting a real-world trial | Planned next |
|---|---|---|
| A conversation on one computer, taking turns or listening continuously | Two people sharing one computer | Help pages inside the program, with a **?** beside each option |
| Translating recordings, with export | Two computers paired | Fixing a sentence: other ways it could have been heard or translated, each translation shown back in the speaker's language so someone who can't read the target language can check it |
| Translating typed text | The ready-made folder on another computer | Saving a live conversation as a document (today only a recording's results can be exported) |
| The Test bench and the performance panel | | Model recommendations: "use recommended" for each language |
| Farsi clean-up; Arabic vowel marks | | Guided tutorials |

**Under consideration:** glossaries of fixed terms and a phrasebook of checked translations for
common sentences. Both are being thought through before they are built (the "menu" case above
shows why a word with two meanings needs care).

## Limits to know

- **Machine translation makes mistakes,** and a fluent-sounding wrong translation is the hardest
  kind to notice. Use Volis for routine exchanges; use a qualified interpreter where an error
  would matter.
- **Most testing so far is on clear, read speech.** Everyday speech, slang, noisy rooms and people
  talking over each other are harder. A very quiet speaker straight after a loud one may be
  missed.
- **Dialects.** Iraqi Arabic is a named choice; other dialects are treated as Arabic in general.
  Afghan Dari has not been tested.
- **Farsi is not yet spoken aloud.**
- **Windows and NVIDIA graphics cards only.**

## Further reading

| Document | For |
|---|---|
| [README.md](README.md) | Installing Volis and using it, step by step |
| [MODELS.md](MODELS.md) | Which models to start with, how to choose your own, and every test result |
| [SETTINGS.md](SETTINGS.md) | Every setting |
| [DEVELOPMENT.md](DEVELOPMENT.md) | For whoever builds and maintains Volis |
| [HANDOFF.md](HANDOFF.md) | Detailed status, history and priorities |
