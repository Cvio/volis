# Volis

Volis is a live interpreter that runs entirely on your own computer. One person speaks; Volis
writes down what they said, translates it, shows both, and says the translation aloud in the
other language. Two people who don't share a language can hold a conversation through it.

**It never uses the internet.** You need a connection once, to install it and download the
speech and translation models. After that it works with the network cable unplugged, and
nothing you say leaves the machine.

## What you need

- **Windows 10 or 11**, 64-bit.
- **An NVIDIA graphics card with 8 GB of memory or more**, with a current driver.
- **About 15 GB of free disk space** for the program and a basic set of models. More models
  need more space.
- **A microphone and speakers.** A headset is best: with speakers, Volis mutes the microphone
  while it talks so it doesn't hear itself.
- **An internet connection for the setup below only.**
- **[Git](https://git-scm.com/)**, to get the code.
- **[uv](https://docs.astral.sh/uv/)**, which installs everything else:
  `winget install astral-sh.uv` (then open a new PowerShell window).

Every command on this page is for **PowerShell**.

If someone gave you a ready-made Volis folder, skip to
[If you were given a ready-made folder](#if-you-were-given-a-ready-made-folder).

## Set it up

1. **Get Volis** and go into its folder:

   ```powershell
   git clone https://github.com/Cvio/volis.git
   cd volis
   ```

2. **Install it:**

   ```powershell
   .\setup.ps1
   ```

   This downloads Python and everything Volis needs into this folder (several GB, so it
   takes a while the first time) and then checks the result. Nothing is installed anywhere
   else on your computer.

   ✅ It should end with `All checks passed.`

3. **Get the models.** Volis uses three kinds: one that turns speech into text (a
   *recognizer*), one that translates the text (a *translator*), and one that speaks the
   result (a *voice*). This gets a set that works for English and Spanish on an 8 GB card,
   about 4.5 GB in all:

   ```powershell
   .\fetch-models.ps1 -Only silero_vad,lessac,es_MX-claude
   .\fetch-model.ps1 openai/whisper-large-v3-turbo -Role asr
   .\fetch-model.ps1 unsloth/gemma-3-4b-it-GGUF -Role mt -Include "*Q4_K_M.gguf"
   ```

   For other languages, a larger graphics card, or to choose your own models, see
   **[MODELS.md](MODELS.md)**. It says what to pick for 8 GB and 16 GB cards and how to
   find and try models yourself.

4. **Check that Volis sees them:**

   ```powershell
   .\.venv\Scripts\python.exe -m volis --report
   ```

   ✅ Every model listed should say `ok`.

5. **Optional, but worth it: translate on the graphics card.** As installed, the translator
   runs on the processor, which works but takes a second or more per sentence. Running it on
   the graphics card is several times faster. That needs a one-time build on your machine;
   [DEVELOPMENT.md](DEVELOPMENT.md#the-translator-on-the-graphics-card) has the steps.

## Start it

```powershell
.\.venv\Scripts\python.exe -m volis
```

A window opens, with a console window behind it that shows what Volis is doing.

1. Under **Spoken**, choose the language you will speak. Under **Translate into**, choose
   the other one.
2. Choose a **Recognizer** and a **Translator** from the lists. Volis remembers your choices.
3. Choose your **Microphone** and **Speakers**.
4. Press **Start**. The first time, loading the models takes a few seconds.
5. Speak. Each sentence appears with its translation, and the translation is spoken.

## Ways to use it

Choose one under **Mode**. You can switch while it is running.

| Mode | How it works |
|---|---|
| **Take turns** | The microphone stays closed until you press Space. Press it, speak, press it again: everything you said is translated and spoken. The easiest mode to start with. |
| **Listen continuously** | Hands-free. Every pause ends a sentence. |
| **Shared machine** | Two people, one computer, a key each (the left and right arrow keys). Each side has its own language, and what one says is spoken in the other's. Escape cancels a turn. |
| **Pair with another PC** | Two computers, one conversation. Each translates what its own person says and sends the text to the other, which shows and speaks it. Tick the box on both, press Start on both, then type the address the other one shows and press Connect. They must be on the same local network. |

### Translate a recording

Choose **File** at the top, open a recording (or drop it on the window), and press Start.
Each sentence becomes a row; click a row to hear that part of the recording. **Export** saves
the transcript, the translation and subtitles.

From the command line:

```powershell
.\.venv\Scripts\python.exe -m volis --file talk.m4a --from es --to en --fast
```

WAV, MP3, M4A, FLAC, OGG and Opus all work.

### The options in the window

| Option | What it does |
|---|---|
| **Speak translations** | Says each translation aloud. Turn it off for captions only. |
| **Half-duplex** | Mutes the microphone while Volis is speaking. Leave it on unless you wear a headset. |
| **Show text while speaking** | Shows words as you say them, before the sentence is finished. Costs more work. |
| **Translate with the earlier sentences as context** | Each sentence is translated knowing the few before it, so "it", "her" and the like come out right. |
| **Revise earlier translations** | Looks again at a short sentence once the next one is heard, and corrects it on screen if its meaning changed. |
| **Add vowel marks to Arabic before it is spoken** | Helps the Arabic voices pronounce words correctly. Needs one more small model: `.\fetch-models.ps1 -Only tashkeel`. |
| **Glossary** | Names and terms to keep exactly as written, separated by commas. |

[SETTINGS.md](SETTINGS.md) lists every setting and every command-line option.

### See what it costs your computer

**View > Performance** (Ctrl+Shift+P) opens a panel showing how much of the graphics card,
memory and processor Volis is using, and how long each sentence takes. Its **What if** tab
tells you whether a different choice of models would fit before you load them.

## If something goes wrong

| What you see | What to do |
|---|---|
| `setup.ps1` stops, or says files are missing | Security software sometimes removes program files. Ask for an exclusion for the Volis folder, then run `.\setup.ps1 -Reinstall`. |
| `--report` shows a model as `DISABLED` or `broken` | The line under it says which file is missing or what is wrong. Fetch the model again. |
| A model you downloaded isn't in the lists | Run `--report`: every folder Volis found is listed, with the reason if it can't be used. |
| Nothing happens when you speak | Check the level meter at the top right moves when you talk. If it doesn't, pick another **Microphone**, and check the microphone isn't muted in Windows. |
| Volis translates its own voice | Tick **Half-duplex**, or use a headset. |
| Everything is very slow | The models probably don't fit on your graphics card together. Open **View > Performance**; the **What if** tab says whether they fit. Choose a smaller translator. |
| Translation takes a second or more per sentence | The translator is running on the processor. See step 5 of the setup. |
| It starts, then says a model "is not in" the models folder | The model named in your settings isn't installed. Pick one from the list in the window. |
| Pairing won't connect | Both computers must be on the same network, and Windows Firewall must allow Volis. The message in the window says which of the two it is. |

To check the installation at any time:

```powershell
.\doctor.ps1
```

## If you were given a ready-made folder

Someone can build Volis into a folder that needs no setup. If you have one:

1. Copy the whole folder anywhere on your computer. You need an NVIDIA graphics card and its
   driver; nothing else has to be installed, and no internet is needed.
2. Double-click `volis.exe`. Everything under [Start it](#start-it) applies from there.

If it doesn't start, open a terminal in the folder and run `volis.exe --doctor`. It checks that
every file the program needs is present and names any that isn't. Security software removing
files is the usual cause.

## More

- **[MODELS.md](MODELS.md):** which models to use, how to find and try your own, and how
  every model we tested scored.
- **[SETTINGS.md](SETTINGS.md):** every setting and command-line option.
- **[DEVELOPMENT.md](DEVELOPMENT.md):** for people changing Volis: the translator build, making
  the ready-made folder, the tests.
