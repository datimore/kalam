"""Kalam: hold a key, speak Egyptian Arabic + English, the text lands where the cursor is."""
import ctypes
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

import keyboard
import pystray
from PIL import Image, ImageDraw

from . import config, inserter
from .audio import Recorder
from .engine import Engine
from .overlay import Overlay
from .settings_window import SettingsWindow, open_file

MODIFIER_FAMILIES = ('ctrl', 'alt', 'shift', 'windows')
STARTUP = Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs/Startup/Kalam.vbs'
RELOAD_KEYS = ('model', 'device', 'compute_type')


def _key_matches(spec, name):
    # «ctrl» in a shortcut means either Ctrl; «right ctrl» means only the right one
    name = (name or '').lower()
    return name == spec or (spec in MODIFIER_FAMILIES and name in (f'left {spec}', f'right {spec}'))


def _icon(color):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=color)
    d.rounded_rectangle((24, 12, 40, 38), radius=8, fill='white')     # mic head
    d.arc((17, 22, 47, 46), 0, 180, fill='white', width=4)            # holder
    d.line((32, 46, 32, 53), fill='white', width=4)
    d.line((24, 53, 40, 53), fill='white', width=4)
    return img


ICONS = {s: _icon(c) for s, c in {'loading': '#8B8D98', 'ready': '#30A46C', 'listen': '#E5484D',
                                  'work': '#F5A524', 'paused': '#8B8D98', 'error': '#E5484D'}.items()}


class App:
    def __init__(self):
        config.ensure_data_dir()
        self.cfg = config.load()
        self.engine = Engine(self.cfg)
        self.recorder = Recorder(self.cfg)
        self.ui = queue.Queue()     # work for the Tk thread
        self.jobs = queue.Queue()   # audio / reload requests for the worker
        self.state = 'loading'
        self.mode = None            # 'hold' | 'toggle' while recording
        self.paused = False
        self.pressed = set()
        self.toggle_latched = False
        self.rec_started = 0.0
        self.hotkey_handles = []

        self.root = tk.Tk()
        self.root.withdraw()
        self.overlay = Overlay(self.root)
        self.tray = pystray.Icon('kalam', ICONS['loading'], 'Kalam: loading…', self._menu())

    # ── tray ─────────────────────────────────────────────────────────────────
    def _menu(self):
        item = pystray.MenuItem
        return pystray.Menu(
            item(lambda _: self._status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            item('Settings…', lambda: self.ui.put(self.open_settings), default=True),
            item('Edit my Egyptian style prompt', lambda: open_file('prompt_ar.txt')),
            item('Edit hint words', lambda: open_file('words.txt')),
            item('Edit fixes', lambda: open_file('fixes.txt')),
            item('Open history', lambda: open_file('history.txt')),
            pystray.Menu.SEPARATOR,
            item('Pause', self.toggle_pause, checked=lambda _: self.paused),
            item('Start with Windows', self.toggle_startup, checked=lambda _: STARTUP.exists()),
            item('Quit', lambda: self.ui.put(self.quit)),
        )

    def _status_text(self):
        hold, tog = self.cfg['hold_key'], self.cfg['toggle_key']
        if self.state == 'loading':
            return f'Loading {self.cfg["model"]}…'
        if self.state == 'error':
            return 'Error, see kalam.log'
        return f'{self.cfg["model"]} on {self.engine.device} · hold {hold} · or {tog}'

    def set_state(self, state):
        self.state = state
        self.tray.icon = ICONS['paused' if self.paused and state == 'ready' else state]
        self.tray.title = f'Kalam: {self._status_text()}'

    def toggle_pause(self):
        self.paused = not self.paused
        self.set_state(self.state)

    def toggle_startup(self):
        if STARTUP.exists():
            STARTUP.unlink()
            return
        pyw = Path(sys.executable).with_name('pythonw.exe')
        entry = config.ROOT / 'kalam.pyw'
        STARTUP.write_text(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{entry}""", 0\n', encoding='utf-16')

    # ── hotkeys (keyboard thread) ────────────────────────────────────────────
    def register_hotkeys(self):
        keyboard.unhook_all()
        self.pressed.clear()
        keyboard.hook(self._on_key)
        tog = self.cfg['toggle_key'].strip()
        if tog:
            # swallow the toggle combo so it does nothing in the focused app
            self.hotkey_handles = [keyboard.add_hotkey(tog, lambda: None, suppress=True, trigger_on_release=False)]

    def _on_key(self, e):
        name = (e.name or '').lower()
        hold = [k.strip() for k in self.cfg['hold_key'].lower().split('+') if k.strip()]
        tog = [k.strip() for k in self.cfg['toggle_key'].lower().split('+') if k.strip()]
        if e.event_type == 'down':
            self.pressed.add(name)
            if name == 'esc' and self.mode:
                self.ui.put(self.cancel)
                return
            all_down = lambda keys: keys and all(any(_key_matches(k, p) for p in self.pressed) for k in keys)
            if tog and all_down(tog) and any(_key_matches(k, name) for k in tog):
                if not self.toggle_latched:  # ignore key auto-repeat
                    self.toggle_latched = True
                    self.ui.put(self.on_toggle)
            elif hold and all_down(hold) and self.mode is None and not (tog and all_down(tog)):
                self.ui.put(lambda: self.start('hold'))
        else:
            self.pressed.discard(name)
            if any(_key_matches(k, name) for k in tog):
                self.toggle_latched = False
            if self.mode == 'hold' and any(_key_matches(k, name) for k in hold):
                self.ui.put(self.finish)

    # ── recording (Tk thread) ────────────────────────────────────────────────
    def start(self, mode):
        if self.mode or self.paused:
            return
        if self.state not in ('ready', 'work'):  # recording while the last clip is still being written is fine
            self.overlay.show('Still loading the model…' if self.state == 'loading' else 'Model not loaded', 'info', 1.5)
            return
        try:
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            logging.exception('mic')
            self.overlay.show('Microphone error', 'error', 3)
            return
        self.mode, self.rec_started = mode, time.time()
        self.set_state('listen')
        self._tick()

    def _tick(self):
        if not self.mode:
            return
        secs = time.time() - self.rec_started
        hint = '  (Esc cancels)' if self.mode == 'toggle' else ''
        self.overlay.show(f'Listening {int(secs) // 60}:{int(secs) % 60:02d}{hint}', 'listen', level=self.recorder.level)
        if secs > self.cfg['max_seconds']:
            self.finish()
            return
        self.root.after(80, self._tick)

    def on_toggle(self):
        if self.mode == 'toggle':
            self.finish()
        elif self.mode is None:
            self.start('toggle')

    def finish(self):
        if not self.mode:
            return
        self.mode = None
        audio = self.recorder.stop()
        self.set_state('work')
        self.overlay.show('Writing…', 'work')
        self.jobs.put(('audio', audio))

    def cancel(self):
        if not self.mode:
            return
        self.mode = None
        self.recorder.stop()
        self.set_state('ready')
        self.overlay.show('Cancelled', 'info', 1.0)

    # ── worker thread: model + transcription ─────────────────────────────────
    def worker(self):
        while True:
            kind, payload = self.jobs.get()
            if kind == 'quit':
                return
            if kind == 'load':
                self.ui.put(lambda: (self.set_state('loading'), self.overlay.show(f'Loading {self.cfg["model"]}…', 'info')))
                try:
                    dev = self.engine.load()
                    logging.info('loaded %s on %s', self.cfg['model'], dev)
                    self.ui.put(lambda: (self.set_state('ready'), self.overlay.show(f'Ready · hold {self.cfg["hold_key"]}', 'ok', 2.5)))
                except Exception:  # noqa: BLE001
                    logging.exception('load')
                    self.ui.put(lambda: (self.set_state('error'), self.overlay.show('Model failed to load, see kalam.log', 'error', 6)))
                continue
            try:
                text, info = self.engine.transcribe(payload)
                logging.info('%s %s', info, text)
                if text:
                    self._history(text, info)
                    inserter.insert(text + (' ' if self.cfg['trailing_space'] else ''), self.cfg['insert_method'])
                    self.ui.put(lambda: self._done())
                else:
                    self.ui.put(lambda: self._done('Didn’t catch anything', 'info', 1.2))
            except Exception:  # noqa: BLE001
                logging.exception('transcribe')
                self.ui.put(lambda: self._done('Error, see kalam.log', 'error', 3))

    def _done(self, msg=None, kind='info', secs=None):
        if self.mode:  # already recording the next one
            return
        self.set_state('ready' if self.jobs.empty() else 'work')
        if msg:
            self.overlay.show(msg, kind, secs)
        elif self.jobs.empty():
            self.overlay.hide()

    def _history(self, text, info):
        line = f'{datetime.now():%Y-%m-%d %H:%M} | {info.get("lang")} | {info.get("secs")}s -> {info.get("took")}s | {text}\n'
        with open(config.DATA_DIR / 'history.txt', 'a', encoding='utf-8') as f:
            f.write(line)

    # ── settings ─────────────────────────────────────────────────────────────
    def open_settings(self):
        SettingsWindow(self.root, self.cfg, self.apply_settings)

    def apply_settings(self, new):
        reload = any(new[k] != self.cfg[k] for k in RELOAD_KEYS)
        self.cfg.update(new)  # engine and recorder share this dict
        config.save(self.cfg)
        self.register_hotkeys()
        try:
            self.recorder.apply_settings()
        except Exception:  # noqa: BLE001
            logging.exception('mic')
            self.overlay.show('Microphone error', 'error', 3)
        if reload:
            self.jobs.put(('load', None))
        else:
            self.set_state(self.state)

    # ── main loop ────────────────────────────────────────────────────────────
    def _pump(self):
        while True:
            try:
                fn = self.ui.get_nowait()
            except queue.Empty:
                break
            fn()
        self.root.after(30, self._pump)

    def quit(self):
        self.jobs.put(('quit', None))
        keyboard.unhook_all()
        self.tray.stop()
        self.root.destroy()

    def run(self):
        threading.Thread(target=self.worker, daemon=True).start()
        self.jobs.put(('load', None))
        self.register_hotkeys()
        try:
            self.recorder.apply_settings()
        except Exception:  # noqa: BLE001
            logging.exception('mic')
        self.tray.run_detached()
        self._pump()
        self.root.mainloop()


def main():
    config.ensure_data_dir()
    logging.basicConfig(filename=config.DATA_DIR / 'kalam.log', level=logging.INFO, encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(message)s')
    # one instance only: two copies would both paste every dictation
    ctypes.windll.kernel32.CreateMutexW(None, False, 'Kalam-dictation-single-instance')
    if ctypes.windll.kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, 'Kalam is already running (look for the mic icon in the tray).', 'Kalam', 0x40)
        return
    try:
        App().run()
    except Exception:  # noqa: BLE001
        logging.exception('fatal')
        raise
