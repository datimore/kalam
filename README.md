# Kalam · كلام

**Hold a key, talk the way you talk, and the text appears where your cursor is.**
Built for Egyptian Arabic mixed with English, written the way you say it: no formal Arabic, no translation.

> «محتاج أعمل update للـ dashboard قبل الـ meeting بكره»
> stays exactly like that, not «أحتاج إلى تحديث لوحة المعلومات قبل الاجتماع غداً».

Works in Word, Notion, the browser, Outlook, WhatsApp desktop: any app with a text cursor.
Everything runs on your own computer. Nothing is uploaded.

## How to use

| Do this | What happens |
|---|---|
| **Hold Right Ctrl**, speak, release | Text is inserted at the cursor ~1–2 s later |
| **Ctrl+Alt+Space**, speak, **Ctrl+Alt+Space** again | Same, for longer dictation (no key to hold) |
| **Esc** while it's listening | Cancel, nothing is inserted |

A small pill at the bottom of the screen shows *Listening* (red) and *Writing…* (amber).
It never takes the cursor away from your document.
The mic icon in the system tray has the menu: settings, pause, start with Windows, quit.

## Install (Windows)

1. Install [Python 3.11+](https://www.python.org/downloads/) (tick *Add to PATH*).
2. Double-click **`install.bat`**. It installs GPU support automatically when it finds an NVIDIA card.
3. Double-click **`Start Kalam.bat`**. The first start downloads the model (large-v3, ~3 GB).
4. Optional: tray icon → **Start with Windows**.

## Why it keeps your Egyptian Arabic

Generic dictation tools turn Egyptian Arabic into formal Arabic, or write English words in Arabic letters
(«داشبورد»). Kalam uses the recipe that worked for my video captions:

1. **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** running OpenAI's Whisper **large-v3** locally (GPU if you have one).
2. **Language forced to Arabic**, so a sentence full of English words isn't switched to English.
3. **A prompt written in Egyptian dialect, with English words in English letters.** Whisper copies the style
   of its prompt. This is the biggest single difference.
4. **Your hint words** (Power BI, Notion, client names…) so they're spelled right.
5. **Your last sentence** fed back in, so the style stays consistent between presses.
6. **A fix list** applied after every dictation (يكذب → يكدب, الثالثة → التالتة…).
7. **Smart language**: if you dictate a sentence fully in English, it's detected and written in English.

Safety nets for Whisper's known quirks: silence and very short presses are ignored, YouTube-style phrases
it invents on silence ("اشتركوا في القناة") are dropped, and repetition loops are cut.

## Make it understand you better

Tray icon → the files below (also in the `my-settings` folder). Changes apply on the next dictation; no restart.

| File | What to put there |
|---|---|
| `prompt_ar.txt` | 3–4 sentences that sound like **you**: your dialect, your English terms. |
| `words.txt` | English terms and names you say often, one per line. |
| `fixes.txt` | `wrong = right`, one per line, for words it keeps getting wrong. |
| `history.txt` | Everything you dictated, the easiest place to spot new fixes. |

## Models

Settings → *Whisper model*. Default **large-v3**.

| Model | Egyptian quality | Speed | Notes |
|---|---|---|---|
| **large-v3** | Best | ~1.5–2.5 s per sentence on an RTX 4060 | Default |
| large-v3-turbo | Good | Much faster | Good on slower laptops |
| large-v2 / medium | OK | Faster | |
| small / base / tiny | Weak for dialect | Fastest | Not recommended |

You can also paste any faster-whisper (CTranslate2) model id from Hugging Face, e.g. an Egyptian fine-tune.
Models download the first time you pick them.

## Settings

- **Run on**: auto / cuda (NVIDIA GPU) / cpu. Auto falls back to CPU if the GPU fails.
- **Hold to talk / Press to start-stop**: click *Set…* and press the keys. Avoid Alt+Shift (Windows language switch).
- **Microphone**: pick a specific mic, or leave Windows default.
- **Insert text by**: *paste* (fast; your clipboard text is restored afterwards) or *type* (for apps that block paste).
- **Keep mic open**: keeps 0.4 s of audio from before you press, so the first word is never cut. The Windows mic indicator stays on.
- **Remove fillers**: drops «إممم», «ااا», "umm".

## Troubleshooting

- **Nothing appears in one specific app**: if that app runs *as administrator*, Windows blocks other apps from
  typing into it. Run Kalam as administrator too, or switch *Insert text by* to *type*.
- **First word missing**: start speaking a beat after pressing, or turn on *Keep mic open*.
- **Slow**: check the tray tooltip says `cuda`. If it says `cpu`, re-run `install.bat`, or pick large-v3-turbo.
- **Copied an image right before dictating**: paste mode can only restore copied *text*.
- Logs: `my-settings/kalam.log`.

## For developers

```
kalam/engine.py     faster-whisper + prompt + hotwords + fixes + hallucination filters
kalam/audio.py      mic capture, resampling to 16 kHz, optional pre-roll
kalam/inserter.py   paste / type at the cursor
kalam/app.py        hotkeys, tray icon, worker thread
kalam/overlay.py    the non-focus-stealing pill
tools/try_file.py   run the engine on clips of a WAV:  python tools/try_file.py voice.wav 0:6 12:8
tools/e2e.py        end-to-end: real hotkeys + paste, with a WAV in place of the mic
```

## License

MIT. Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) and
[OpenAI Whisper](https://github.com/openai/whisper) (MIT).
