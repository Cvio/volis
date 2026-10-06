# Volis

Volis is a live interpreter that runs entirely on your own computer. One person speaks; Volis
writes down what they said, translates it, shows both, and says the translation aloud in the
other language. Two people who don't share a language can hold a conversation through it.

**After initial install, no internet is needed.** You need a connection once, to install it and download the
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
- **About an hour for the setup**, most of it waiting for downloads. One step (step 3) installs
  two free tools from Microsoft and NVIDIA so that translation runs on the graphics card.
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

   ✅ It should end with `All checks passed.` It will also say, in yellow, that the translator
   will run on the processor. That's expected at this point: the next step fixes it.

3. **Put the translator on the graphics card.** Don't skip this. Without it Volis still
   works, but the translator runs on the processor and every sentence takes several seconds
   instead of about half a second. It is done once per computer and takes 30 to 45 minutes,
   most of it waiting.

   It needs two free tools installed first. Do the four parts in order.

   **Part A: install Microsoft's build tools** (about 10 minutes, about 7 GB of disk)

   1. Paste this line into PowerShell and press Enter:

      ```powershell
      winget install Microsoft.VisualStudio.2022.BuildTools --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
      ```

   2. If Windows asks "Do you want to allow this app to make changes to your device?",
      choose **Yes**.
   3. A window titled *Visual Studio Installer* opens and shows a progress bar. **Wait.** You
      don't need to click anything in it. It closes by itself.

   ✅ PowerShell prints `Successfully installed`.

   **Part B: install NVIDIA's CUDA Toolkit, version 12.9** (about 15 minutes, about 3 GB to
   download)

   Use version **12.9**. Newer versions (13 and up) don't work with Volis.

   1. Open this page in your browser: <https://developer.nvidia.com/cuda-toolkit-archive>
   2. In the list, click the highest entry that starts with **CUDA Toolkit 12.9**.
   3. On the next page, click these buttons, in order: **Windows**, **x86_64**, **11** (choose
      11 on Windows 10 too), **exe (local)**. A **Download** button appears. Click it and wait
      for the download to finish.
   4. Open the downloaded file (its name starts with `cuda_12.9`). If Windows asks to allow
      changes, choose **Yes**. Click **OK** to accept the folder it suggests, and wait while it
      unpacks.
   5. Click **Agree and continue**.
   6. Choose **Custom (Advanced)**, then **Next**.
   7. You see a list with tick boxes. **Untick everything except the one named `CUDA`.** This
      matters: the other boxes would replace your graphics driver with an older one.
   8. Click **Next**, then **Next** again, and wait for it to finish. Then **Close**.

   ✅ This folder now exists: `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9`

   **Part C: build the translator's engine** (10 to 20 minutes)

   1. In PowerShell, in the Volis folder, run:

      ```powershell
      .\build-llama.ps1 -Cuda
      ```

   2. **Wait.** Lines of text scroll past for a long time, and sometimes it looks stuck for a
      minute or two. That's normal. Don't close the window.

   ✅ The last line begins `Successfully built` and ends in `.whl`.

   If it stops with `STOP: Visual Studio Build Tools (C++) are not installed`, do Part A
   again. If it stops with `STOP: no CUDA Toolkit 12.x`, do Part B again.

   **Part D: install what you built**

   1. Run the setup again:

      ```powershell
      .\setup.ps1
      ```

   ✅ Near the end you should see both of these lines:

   ```
   ok    llama_cpp 0.3.35, GPU offload: yes
   The translator will run on the graphics card.
   ```

   If it says `GPU offload: no`, or `The translator will run on the PROCESSOR`, Part C didn't
   finish. Run Part C again and read its last lines.

4. **Get the models.** Volis uses four kinds:

   | Model | What it does | Do you choose it? |
   |---|---|---|
   | **Speech detector** | Notices when someone starts and stops talking | No: there is one, and it is required |
   | **Recognizer** | Turns the speech into text | Yes |
   | **Translator** | Translates the text | Yes |
   | **Voice** | Says the translation aloud | One for each language you translate into |

   This gets a set that works for English and Spanish on an 8 GB card, about 4.5 GB in all:

   ```powershell
   .\fetch-models.ps1 -Only silero_vad,lessac,es_MX-claude                          # the speech detector, an English voice, a Spanish voice
   .\fetch-model.ps1 openai/whisper-large-v3-turbo -Role asr                        # the recognizer
   .\fetch-model.ps1 unsloth/gemma-3-4b-it-GGUF -Role mt -Include "*Q4_K_M.gguf"    # the translator
   ```

   For other languages, a larger graphics card, or to choose your own models, see
   **[MODELS.md](MODELS.md)**. It says what to pick for 8 GB and 16 GB cards and how to
   find and try models yourself.

5. **Check that Volis sees them:**

   ```powershell
   .\.venv\Scripts\python.exe -m volis --report
   ```

   ✅ Every model listed should say `ok`.

## Start it

```powershell
.\.venv\Scripts\python.exe -m volis
```

A window opens, with a console window behind it that shows what Volis is doing.

1. Under **Spoken**, choose the language you will speak. Under **Translate into**, choose
   the other one. **Swap** between them exchanges the two.
2. Choose a **Recognizer** and a **Translator** from the lists. Volis remembers your choices.
   Hold the mouse over a name to see the details of that model. If an orange line appears
   under them, the two won't fit in your computer's memory together: choose a smaller
   translator.
3. Choose your **Microphone** and **Speakers**, and press **Test** beside each:
   - **Test** beside Speakers says a short sentence. If you don't hear it, choose other speakers.
   - **Test** beside Microphone records you for 3 seconds, plays it back, and shows what
     Volis heard.
4. Press the big green **START** button (or Ctrl+Enter). The first time, loading the models
   takes a few seconds. The button always shows what Volis is doing; press it again to stop.
5. Speak. Each sentence appears with its translation, and the translation is spoken.

While a conversation runs, the settings fold away so the text has the whole window. **A−** and
**A+** above the text make it smaller or larger. **Settings** brings the settings back.

A setting that is greyed out says why in small grey text beside it, and when you hold the mouse
over it.

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

**Speak translations** is with the main settings: it says each translation aloud. Turn it off
for captions only.

The rest are under **Advanced**, which stays closed until you open it:

| Option | What it does |
|---|---|
| **Half-duplex** | Mutes the microphone while Volis is speaking. Leave it on unless you wear a headset. |
| **Add vowel marks to Arabic before it is spoken** | Helps the Arabic voices pronounce words correctly. Needs one more small model: `.\fetch-models.ps1 -Only tashkeel`. |
| **Compare recognizers** | Every recognizer you have writes down the same sentence, side by side. Nothing is translated. |
| **Show text while speaking** | Shows words as you say them, before the sentence is finished. Costs more work. |
| **Translate with the earlier sentences as context** | Each sentence is translated knowing the few before it, so "it", "her" and the like come out right. |
| **Revise earlier translations** | Looks again at a short sentence once the next one is heard, and corrects it on screen if its meaning changed. |
| **Wait for the next sentence before speaking a short one** | With the option above: a short sentence is spoken only after the next is heard, so it is spoken corrected. |
| **Join short fragments to what follows** | A few words with no full stop wait a moment for the rest of the sentence. |
| **Glossary** | Names and terms to keep exactly as written, separated by commas. |
| **Pair with another PC** | Two computers, one conversation (see above). |

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
| You added a model, or plugged in a headset, while Volis was open | Press **Rescan models and devices** (or F5). The lists update without restarting, and a line under the button says what changed. |
| A model you downloaded isn't in the lists | Run `--report`: every folder Volis found is listed, with the reason if it can't be used. |
| Nothing happens when you speak | Check the level meter at the top right moves when you talk. If it doesn't, pick another **Microphone**, and check the microphone isn't muted in Windows. |
| Volis translates its own voice | Tick **Half-duplex**, or use a headset. |
| Everything is very slow | The models probably don't fit on your graphics card together. Open **View > Performance**; the **What if** tab says whether they fit. Choose a smaller translator. |
| Translation takes several seconds per sentence | The translator is running on the processor, not the graphics card. Run `.\doctor.ps1`: if it says `GPU offload: no`, do step 3 of the setup. |
| Setup finished, but `.\doctor.ps1` says `GPU offload: no` | Step 3 of the setup was skipped or didn't finish. Do it (or do it again); its Part C must end with `Successfully built`. |
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
