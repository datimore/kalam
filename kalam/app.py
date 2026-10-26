"""Kalam: hold a key, speak Egyptian Arabic + English, the text lands where the cursor is."""
import ctypes
import logging
import os
import queue
import sys
import threading
import time
import winreg
from datetime import datetime

import keyboard
import pyperclip
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, inserter
from .audio import Recorder
from .engine import Engine, model_cached, model_download_bytes
from .icons import mic_icon
from .main_window import MainWindow
from .overlay import Overlay
from .settings_window import SettingsDialog, open_file

MODIFIER_FAMILIES = ('ctrl', 'alt', 'shift', 'windows')
RELOAD_KEYS = ('model', 'device', 'compute_type')
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
INSTANCE = 'Kalam-dictation-' + os.environ.get('USERNAME', 'user')


def _key_matches(spec, name):
    # «ctrl» in a shortcut means either Ctrl; «right ctrl» means only the right one
    name = (name or '').lower()
    return name == spec or (spec in MODIFIER_FAMILIES and name in (f'left {spec}', f'right {spec}'))


def _own_window_focused():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def _launch_command():
    if config.FROZEN:
        return f'"{sys.executable}" --tray'
    pyw = os.path.join(os.path.dirname(sys.executable), 'pythonw.exe')
    return f'"{pyw}" "{config.ROOT / "kalam.pyw"}" --tray'


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, 'Kalam')
            return True
    except OSError:
        return False


def set_autostart(on):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, 'Kalam', 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, 'Kalam')
            except OSError:
                pass


class App:
    def __init__(self, qapp, start_hidden):
        self.qapp = qapp
        config.ensure_data_dir()
        self.cfg = config.load()
        self.engine = Engine(self.cfg)
        self.recorder = Recorder(self.cfg)
        self.ui = queue.Queue()     # work for the Qt thread
        self.jobs = queue.Queue()   # audio / reload requests for the worker
        self.state = 'loading'
        self.mode = None            # 'hold' | 'toggle' while recording
        self.paused = False
        self.pressed = set()
        self.toggle_latched = False
        self.rec_started = 0.0
        self.downloading = False

        self.overlay = Overlay()
        self.win = MainWindow(self.cfg)
        self.win.mic_clicked.connect(self.on_toggle)
        self.win.model_chosen.connect(self.choose_model)
        self.win.settings_clicked.connect(self.open_settings)
        self.win.history_clicked.connect(lambda: open_file('history.txt'))
        self.win.closed_to_tray.connect(self._closed_to_tray)
        self._tray()
        self.pump = QTimer(timeout=self._pump, interval=30)
        self.ticker = QTimer(timeout=self._tick, interval=80)
        self.dl_timer = QTimer(timeout=self._download_progress, interval=1000)
        if not start_hidden:
            self.win.show_front()

    # ── tray ─────────────────────────────────────────────────────────────────
    def _tray(self):
        self.tray = QSystemTrayIcon(mic_icon('loading'))
        m = QMenu()
        m.addAction('Open Kalam', self.win.show_front)
        m.addAction('Settings…', self.open_settings)
        m.addSeparator()
        m.addAction('Edit my Egyptian style prompt', lambda: open_file('prompt_ar.txt'))
        m.addAction('Edit hint words', lambda: open_file('words.txt'))
        m.addAction('Edit fixes', lambda: open_file('fixes.txt'))
        m.addAction('Open history', lambda: open_file('history.txt'))
        m.addSeparator()
        self.pause_action = QAction('Pause', m, checkable=True, triggered=self.toggle_pause)
        m.addAction(self.pause_action)
        self.autostart_action = QAction('Start with Windows', m, checkable=True, checked=autostart_enabled(),
                                        triggered=set_autostart)
        m.addAction(self.autostart_action)
        m.addSeparator()
        m.addAction('Quit Kalam', self.quit)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.win.show_front() if r in (
            QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def _closed_to_tray(self):
        if not self.cfg.get('tray_tip_shown'):
            self.tray.showMessage('Kalam is still running',
                                  f'Hold {self.cfg["hold_key"].title()} to dictate. Right-click the tray icon to quit.',
                                  mic_icon('ready'), 5000)
            self.cfg['tray_tip_shown'] = True
            config.save(self.cfg)

    def _status_text(self):
        s = self.state
        if s == 'loading':
            return f'Loading {self.cfg["model"]}…'
        if s == 'error':
            return 'Model failed to load'
        if s == 'listen':
            secs = int(time.time() - self.rec_started)
            return f'Listening {secs // 60}:{secs % 60:02d}'
        if s == 'work':
            return 'Writing…'
        return 'Paused' if self.paused else 'Ready'

    def set_state(self, state):
        self.state = state
        icon_state = 'paused' if self.paused and state == 'ready' else state
        self.tray.setIcon(mic_icon(icon_state))
        self.tray.setToolTip(f'Kalam: {self._status_text()}')
        self.win.set_state(icon_state, self._status_text(), self.recorder.level)

    def toggle_pause(self, on):
        self.paused = on
        self.set_state(self.state)

    # ── hotkeys (keyboard thread) ────────────────────────────────────────────
    def register_hotkeys(self):
        keyboard.unhook_all()
        self.pressed.clear()
        keyboard.hook(self._on_key)
        tog = self.cfg['toggle_key'].strip()
        if tog:
            # swallow the toggle combo so it does nothing in the focused app
            keyboard.add_hotkey(tog, lambda: None, suppress=True, trigger_on_release=False)

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

    # ── recording (Qt thread) ────────────────────────────────────────────────
    def start(self, mode):
        if self.mode or self.paused:
            return
        if self.state not in ('ready', 'work'):  # recording while the last clip is still being written is fine
            self.overlay.show_msg('Still loading the model…' if self.state == 'loading' else 'Model not loaded', 'info', 1.5)
            return
        try:
            self.recorder.start()
        except Exception:  # noqa: BLE001
            logging.exception('mic')
            self.overlay.show_msg('Microphone error', 'error', 3)
            return
        self.mode, self.rec_started = mode, time.time()
        self.set_state('listen')
        self.ticker.start()

    def _tick(self):
        if not self.mode:
            self.ticker.stop()
            return
        secs = time.time() - self.rec_started
        hint = '  (Esc cancels)' if self.mode == 'toggle' else ''
        self.overlay.show_msg(f'{self._status_text()}{hint}', 'listen', level=self.recorder.level)
        self.win.set_state('listen', self._status_text(), self.recorder.level)
        if secs > self.cfg['max_seconds']:
            self.finish()

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
        self.overlay.show_msg('Writing…', 'work')
        self.jobs.put(('audio', audio))

    def cancel(self):
        if not self.mode:
            return
        self.mode = None
        self.recorder.stop()
        self.set_state('ready')
        self.overlay.show_msg('Cancelled', 'info', 1.0)

    # ── worker thread: model + transcription ─────────────────────────────────
    def worker(self):
        while True:
            kind, payload = self.jobs.get()
            if kind == 'quit':
                return
            if kind == 'load':
                self._load()
                continue
            try:
                text, info = self.engine.transcribe(payload)
                logging.info('%s %s', info, text)
                if not text:
                    self.ui.put(lambda: self._done('Didn’t catch anything', 'info', 1.2))
                    continue
                self._history(text, info)
                out = text + (' ' if self.cfg['trailing_space'] else '')
                if _own_window_focused():
                    # dictated from Kalam's own window: nowhere to paste, so hand it over via the clipboard
                    pyperclip.copy(text)
                    self.ui.put(lambda t=text: (self.win.set_last(t), self._done('Copied · paste it with Ctrl+V', 'ok', 2.5)))
                else:
                    inserter.insert(out, self.cfg['insert_method'])
                    self.ui.put(lambda t=text: (self.win.set_last(t), self._done()))
            except Exception:  # noqa: BLE001
                logging.exception('transcribe')
                self.ui.put(lambda: self._done('Error, see kalam.log', 'error', 3))

    def _load(self):
        name = self.cfg['model']
        self.downloading = not model_cached(name)
        self.ui.put(lambda: (self.set_state('loading'), self.dl_timer.start() if self.downloading else None,
                             self.win.set_footer(name)))
        try:
            dev = self.engine.load()
            logging.info('loaded %s on %s', name, dev)
            where = 'GPU' if dev.startswith('cuda') else 'CPU'
            self.ui.put(lambda: self._loaded(f'{name} · {where}'))
        except Exception:  # noqa: BLE001
            logging.exception('load')
            self.ui.put(self._load_failed)

    def _loaded(self, footer):
        self.downloading = False
        self.dl_timer.stop()
        self.set_state('ready')
        self.win.set_footer(footer)
        if not self.win.isVisible():
            self.overlay.show_msg(f'Kalam ready · hold {self.cfg["hold_key"].title()}', 'ok', 2.5)

    def _load_failed(self):
        self.downloading = False
        self.dl_timer.stop()
        self.set_state('error')
        self.win.set_footer('see kalam.log (Settings → model / Run on)')
        self.overlay.show_msg('Model failed to load', 'error', 6)

    def _download_progress(self):
        if self.state != 'loading':
            return
        gb = model_download_bytes(self.cfg['model']) / 1e9
        self.win.set_state('loading', f'Downloading {self.cfg["model"]}… {gb:.1f} GB')
        self.tray.setToolTip(f'Kalam: downloading the model (first time only) {gb:.1f} GB')

    def _done(self, msg=None, kind='info', secs=None):
        if self.mode:  # already recording the next one
            return
        self.set_state('ready' if self.jobs.empty() else 'work')
        if msg:
            self.overlay.show_msg(msg, kind, secs)
        elif self.jobs.empty():
            self.overlay.hide()

    def _history(self, text, info):
        line = f'{datetime.now():%Y-%m-%d %H:%M} | {info.get("lang")} | {info.get("secs")}s -> {info.get("took")}s | {text}\n'
        with open(config.DATA_DIR / 'history.txt', 'a', encoding='utf-8') as f:
            f.write(line)

    # ── settings ─────────────────────────────────────────────────────────────
    def open_settings(self):
        self.win.show_front()
        SettingsDialog(self.cfg, self.apply_settings, self.win).exec()

    def choose_model(self, name):
        if name and name != self.cfg['model']:
            self.apply_settings(dict(self.cfg, model=name))

    def apply_settings(self, new):
        reload = any(new[k] != self.cfg[k] for k in RELOAD_KEYS)
        self.cfg.update(new)  # engine and recorder share this dict
        config.save(self.cfg)
        self.register_hotkeys()
        self.win.refresh_hint()
        try:
            self.recorder.apply_settings()
        except Exception:  # noqa: BLE001
            logging.exception('mic')
            self.overlay.show_msg('Microphone error', 'error', 3)
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

    def quit(self):
        self.jobs.put(('quit', None))
        keyboard.unhook_all()
        self.tray.hide()
        self.win.quitting = True
        self.qapp.quit()

    def run(self):
        threading.Thread(target=self.worker, daemon=True).start()
        self.jobs.put(('load', None))
        self.register_hotkeys()
        try:
            self.recorder.apply_settings()
        except Exception:  # noqa: BLE001
            logging.exception('mic')
        self.pump.start()
        return self.qapp.exec()


def transcribe_file(path):
    """Kalam.exe --transcribe voice.wav: checks the whole pipeline without a mic; result goes to kalam.log."""
    import wave

    import numpy as np

    from .audio import _to_16k
    with wave.open(path) as wf:
        rate, ch = wf.getframerate(), wf.getnchannels()
        x = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
    engine = Engine(config.load())
    logging.info('transcribe-file loaded on %s', engine.load())
    text, info = engine.transcribe(_to_16k(x.reshape(-1, ch).mean(1), rate))
    logging.info('transcribe-file %s %s', info, text)
    return 0


def main():
    config.ensure_data_dir()
    logging.basicConfig(filename=config.DATA_DIR / 'kalam.log', level=logging.INFO, encoding='utf-8',
                        format='%(asctime)s %(levelname)s %(message)s')
    if len(sys.argv) > 2 and sys.argv[1] == '--transcribe':
        return transcribe_file(sys.argv[2])
    qapp = QApplication(sys.argv)
    qapp.setApplicationName('Kalam')
    qapp.setQuitOnLastWindowClosed(False)  # closing the window keeps Kalam in the tray
    qapp.setWindowIcon(mic_icon('ready'))

    # one instance only (two copies would both paste every dictation); a second launch opens the window
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE)
    if sock.waitForConnected(300):
        sock.write(b'show')
        sock.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(INSTANCE)
    server = QLocalServer()
    server.listen(INSTANCE)

    try:
        app = App(qapp, start_hidden='--tray' in sys.argv)
        server.newConnection.connect(lambda: (server.nextPendingConnection(), app.win.show_front()))
        return app.run()
    except Exception:  # noqa: BLE001
        logging.exception('fatal')
        raise
