"""Settings and the user's editable text files (prompt, hint words, fixes)."""
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
    'use_context': True,         # feed the last sentence back so the style carries over
    'beam_size': 5,
    'max_seconds': 300,
    'show_bubble': True,         # floating mic on top of every window
    'bubble_x': None,
    'bubble_y': None,
    'bubble_dock': '',           # '' | left | right (tucked into that screen edge)
}

FILES = ['prompt_ar.txt', 'prompt_en.txt', 'words.txt', 'fixes.txt']


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dst = DATA_DIR / name
        if not dst.exists():
            shutil.copy(DEFAULTS_DIR / name, dst)


def load():
    ensure_data_dir()
    path = DATA_DIR / 'settings.json'
    cfg = dict(DEFAULTS)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text(encoding='utf-8')))
        except (ValueError, OSError):
            pass
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
