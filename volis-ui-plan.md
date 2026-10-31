# Volis: the new window (U1 to U7)

For Claude Code, in the volis repo. Agreed with the user on 2026-10-31. It comes before P18 to
P20 in `volis-next-features.md`. `CLAUDE.md`'s rules all still apply.

**Who it is for:** two people who want to talk, and a linguist reading the conversation
afterwards. Nobody using it should need to know what a model is. Each customer gets a version
tailored to them, so they see only the languages and ways of talking they have.

## How to work on this

- Build in the order below. **Stop after each stage, show its check passing, and wait for the
  user to say go on.** Commit after each stage; tests pass at every commit.
- The old window (`gui/window.py`) stays the one that opens by default until U6, so there is a
  working app throughout. Until then the new one opens with `--new-window`.
- Window logic stays out of Qt: new state and rules go in Qt-free modules with tests.
- Qt widgets and style sheets only. Nothing new to install.
- New settings go in `volis-python.toml` and `SETTINGS.md`.

## The design

### Overall

- **Look:** dark. Graphite by default; Midnight and Warm charcoal in Settings.
- **Layout:** a slim icon rail on the left (Talk, Saved, Settings); the conversation fills the
  rest. Top bar: languages, sound, microphone level (red when silent), text size, "...".
- **Screen language:** English for now, with the wording kept in one place so it can be
  translated later. Speak buttons use each person's own script.

### Starting a conversation

Choose the languages and how you'll talk, then press Start. Volis remembers the last choices.
Only the ways of talking in the customer's setup appear; with only one, that row disappears.

| How people talk | Controls |
|---|---|
| Two people, one computer | Two big buttons, or the arrow keys |
| Two computers | One Talk button; pick the other computer from a nearby list (or type its address), and it must accept |
| Hands-free | One way, with an adjustable pause. Two-way is tested on the Test bench later |

### During a conversation

- **Speaking:** press once to start, again to finish. The buttons grey out and say why, and
  everyone waits while Volis speaks.
- **Moments:** Ready ("Press to speak"), Listening ("Press when finished"), Translating ("Please
  wait"), Speaking ("Volis is speaking", with the bubble outlined).
- **Bubbles:** each person has a side. On one computer each language keeps its side; on two
  computers your own words are on the right. Farsi and Arabic read right to left inside the
  bubble. The translation is larger, with the original smaller and dimmer above it, in Talk and
  in Saved.
- **Speakers:** shown by language unless someone types a name, before or after the conversation.
- **Listening back:** clicking a bubble plays its translation through one shared bar (play,
  pause, bar, timer), then stops. On a second computer only the translation can be heard live.
- **Typing:** "Type a sentence instead" stays available.
- **Loading:** a simple progress screen.
- **Problems:** plain words and one button to fix it; the technical text sits behind **Details**.

### Saving

- **When it ends:** Volis asks for a name, whether to keep the audio, and Save or Delete. Settings
  offers Always ask (default), Always save or Never save.
- **Crashes:** a temporary copy protects the conversation, unless Never save is on.
- **Storage:** an ordinary `conversations` folder inside Volis, one folder per conversation, with
  text (speaker, original, translation) and audio. No password in the first version.
- **Two computers:** when the conversation ends they swap audio over the local network, so both
  have everything. If the connection dropped, either can open the other's file later to combine
  them. Deleting on one computer leaves the other's copy; customers should be told.

### Saved

- Read, listen, search, rename, name speakers, delete.
- The bar gets a "Translation | Original" switch and **Play all**.
- **Open** handles recordings and Volis conversation files, and replaces today's File mode.
- **Share:** a Volis conversation file (one file, opens in another Volis, with audio), text
  (speaker, original, translation), or audio (the whole conversation in the order heard, each
  original followed by its translation).

### Settings

Sound (microphone, speakers, Test, "Using a headset"), Saving, Appearance (theme, text size) and
the hands-free pause. Voice and Faster | More accurate appear only if the setup includes those
choices.

Streaming text, earlier-sentence context, revision, wait before speaking, join fragments, vowel
marks and the glossary box are fixed by the setup, and visible only in developer mode.

### Developer mode

A separate "Volis (developer)" shortcut opens the same window with Models, Test bench, Performance
and a Developer settings page holding every existing option. Customer versions ship without the
shortcut.

### Left for later

Corrections and notes, two-way hands-free, Word and PDF export, password protection, a Farsi or
Arabic interface.

## The stages

### U1: Theme and the new window, with the conversation bubbles

The three themes; the rail, top bar and pages; bubbles drawn from `Session`; Settings' Appearance
section working and remembered. Everything not yet working is greyed out and says so. The Talk page
shows a sample conversation until U2.

**Check:** `python -m volis --new-window` opens in Graphite with the sample conversation; each
theme and text size can be chosen and is remembered; Farsi reads right to left.

### U2: Starting a conversation and the talking controls

The start screen; the real pipeline; the moments above; the three ways of talking; microphone
level and sound; typing; loading and problem screens. Check for a customer's setup deciding what
appears. The two-computers way uses today's typed address until U7.

**Check:** a real conversation in each of the three ways, through bubbles.

### U3: Keeping the audio, and the shared bar

Keep every sentence's original and spoken translation (new: only the file mode keeps audio today).
Audio through `audio.on_audio_thread` as everywhere. Click a bubble to play; the shared bar.

**Check:** click any bubble of a live conversation and hear its translation, with the bar moving.

### U4: Saving and the Saved page

The end-of-conversation prompt and the Settings choice; the temporary copy; the `conversations`
folder; Saved's list, search, rename, speakers and delete; a saved conversation reopens looking the
same, with the Original switch and Play all. `session.MAX_LINES` (200) must stop cutting off long
conversations.

**Check:** kill the app mid-conversation and recover it; save one, close, reopen it in Saved.

### U5: Open and Share

One **Open** for recordings and Volis conversation files, replacing File mode; the three kinds of
Share.

**Check:** open a recording; share a conversation and open that file in a second copy of Volis.

### U6: Developer mode, then removing the old window

The developer shortcut; Models, Test bench, Performance and Developer settings as pages. Every
option in the old window has a home. Then the old window goes, the new one opens by default, and
`README.md` and its pictures are rewritten for it.

**Check:** every old setting can be found; the customer version has no route to developer pages.

### U7: The nearby list and swapping audio

Pick the other computer from a list, with an accept step; typing an address stays. (`Session` already
has `discovered`; check what exists before building.) The computers swap audio when the conversation
ends; if that fails, open the other's file to combine them.

**Check:** two computers on a local network with no internet: find, accept, talk, end, and both
have the whole conversation. Then the same on a network that blocks discovery, by typed address.

## Risks

- **Saving audio is new work,** and it uses more disk space.
- **The nearby list can be blocked** by office and guest networks, so typing an address stays.
- **Copies you can't delete:** after two computers swap audio, deleting on one leaves the other's.
