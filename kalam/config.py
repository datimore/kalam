"""Settings and the user's editable text files (prompt, hint words, fixes)."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, 'frozen', False)  # running from the installed Kalam.exe
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent
DEFAULTS_DIR = ROOT / 'defaults'
ASSETS_DIR = ROOT / 'assets'
# installed: %APPDATA%\Kalam (Program files are read-only); from source: next to the code
_default_home = Path(os.environ.get('APPDATA', Path.home())) / 'Kalam' if FROZEN else ROOT / 'my-settings'
DATA_DIR = Path(os.environ.get('KALAM_HOME', _default_home))

MODELS = ['large-v3', 'large-v3-turbo', 'large-v2', 'medium', 'small', 'base', 'tiny']

DEFAULTS = {
    'model': 'large-v3',
    'device': 'auto',            # auto | cuda | cpu
    'compute_type': 'auto',      # auto | int8_float16 | float16 | int8 | float32
    'language': 'smart',         # smart (Egyptian Arabic + English, pure English detected) | ar | en
    'hold_key': 'right ctrl',    # hold to talk, release to insert
    'toggle_key': 'ctrl+alt+space',  # press to start, press again to insert
    'insert_method': 'paste',    # paste (clipboard + Ctrl+V, clipboard restored) | type
    'trailing_space': True,
    'remove_fillers': False,
    'keep_mic_open': False,      # True keeps a 0.4 s pre-roll so the first word is never cut
    'mic_device': '',            # '' = Windows default
    'use_hint_words': False,     # words.txt as Whisper hotwords (off: made it skip speech and echo the prompt)
    'use_context': False,        # feed the last sentence back (off: one wrong sentence made the next ones drift)
    'beam_size': 5,
    'max_seconds': 300,
    'live_mode': True,           # write each sentence as soon as you pause (toggle / floating mic)
    'live_pause': 1.0,           # seconds of silence that end a sentence
    'show_caption': False,       # live caption of what Kalam hears (the text itself goes into your app)
    'show_status': False,        # status strip (Listening / Writing…); the floating mic's ring already shows it
    'bubble_skin': 'mic',        # mic | emoji:🤖 | image:skins/file.png
    'bubble_size': 56,
    'show_bubble': True,         # floating mic on top of every window
    'meeting_key': 'ctrl+alt+m', # start / stop meeting mode
    'meeting_speakers': True,    # tell the other people in a meeting apart by voice
    'your_name': '',             # your name in meeting transcripts ('' = your Windows name)
    'keep_meeting_audio': False, # keep the two recordings next to the transcript
    'bubble_x': None,
    'bubble_y': None,
    'bubble_dock': '',           # '' | left | right (tucked into that screen edge)
}

FILES = ['prompt_ar.txt', 'prompt_en.txt', 'words.txt', 'fixes.txt']
SETTINGS_VERSION = 4
# the long prompt shipped before 1.2.0: Whisper reused its words («الـ data», «طبعاً») and skipped speech
OLD_DEFAULT_PROMPTS = {'05b84ee60a0e77f915c78ce6298cd50f143f02180ebde030e2b3af3dee211d4f'}


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dst = DATA_DIR / name
        if not dst.exists():
            shutil.copy(DEFAULTS_DIR / name, dst)
    # upgrade the prompt only if the user never edited it
    prompt = DATA_DIR / 'prompt_ar.txt'
    digest = hashlib.sha256(prompt.read_text(encoding='utf-8-sig').strip().encode()).hexdigest()
    if digest in OLD_DEFAULT_PROMPTS:
        shutil.copy(DEFAULTS_DIR / 'prompt_ar.txt', prompt)


def load():
    ensure_data_dir()
    path = DATA_DIR / 'settings.json'
    cfg = dict(DEFAULTS)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            pass
        if cfg.get('settings_version', 1) < 2:
            cfg['use_context'] = False  # the old default caused drift; users can turn it back on
    if cfg.get('settings_version', 1) < 4:
        cfg['show_caption'] = False  # 1.4.0: nothing on screen but the floating mic, unless you turn it on
    # 1.3.0's shortcut boxes could save an empty value or "press the keys…": put the defaults back
    for key in ('hold_key', 'toggle_key', 'meeting_key'):
        if key in DEFAULTS and (not str(cfg.get(key, '')).strip() or 'press' in str(cfg[key])):
            cfg[key] = DEFAULTS[key]
    cfg['settings_version'] = SETTINGS_VERSION
    return cfg


def save(cfg):
    ensure_data_dir()
    (DATA_DIR / 'settings.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')


def read_lines(name):
    """Non-empty, non-comment lines of a user text file."""
    path = DATA_DIR / name
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            out.append(line)
    return out


def read_text(name):
    return ' '.join(read_lines(name))
