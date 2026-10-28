"""Kalam: speak Egyptian Arabic + English, the text lands where the cursor is.

Live mode: while you talk, a watcher thread cuts the audio at each pause. Every finished sentence is transcribed
on the worker thread and pasted right away (floating mic / start-stop shortcut) or kept until you let go of the
hold key. Between sentences the worker runs a fast rough pass so the caption shows what it hears so far.
"""
import ctypes
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime

import keyboard
import pyperclip
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import config, inserter, learn, system, theme
from .audio import SR, Recorder
from .bubble import Bubble
from .engine import Engine, model_cached, model_download_bytes
from .icons import mic_icon
from .main_window import MainWindow
from .overlay import Overlay
from .settings_window import SettingsDialog, confirm_and_learn, open_file

MODIFIER_FAMILIES = ('ctrl', 'alt', 'shift', 'windows')
RELOAD_KEYS = ('model', 'device', 'compute_type')
INSTANCE = os.environ.get('KALAM_INSTANCE', 'Kalam-dictation-' + os.environ.get('USERNAME', 'user'))
LIVE_TICK = 0.2        # seconds between pause checks
MAX_SENTENCE = 25.0    # never let one piece grow longer than this (Whisper works on 30 s windows)
PREVIEW_EVERY = 0.7    # seconds between caption refreshes


def _key_matches(spec, name):
    # «ctrl» in a shortcut means either Ctrl; «right ctrl» means only the right one
    name = (name or '').lower()
    return name == spec or (spec in MODIFIER_FAMILIES and name in (f'left {spec}', f'right {spec}'))


user32 = ctypes.windll.user32


def _is_own(hwnd):
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value == os.getpid()


def _own_window_focused():
    return _is_own(user32.GetForegroundWindow())


def _title(hwnd):
    buf = ctypes.create_unicode_buffer(120)
    user32.GetWindowTextW(hwnd, buf, 120)
    return buf.value


def _bring_back(hwnd):
    """Give focus back to the app you were typing in (allowed: Kalam's window is the foreground one)."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    end = time.time() + 0.6
    while time.time() < end:
        if user32.GetForegroundWindow() == hwnd:
            time.sleep(0.08)  # let the app put its caret back
            return True
        time.sleep(0.02)
    return False


class Session:
    """One dictation, from start to the last pasted word."""

    def __init__(self, sid, mode, live):
        self.id, self.mode, self.live = sid, mode, live
        self.commit_raw = 0     # raw mic samples already sent off as finished sentences
        self.stopped = False    # no more sentences will be cut
        self.cancelled = False
        self.texts = []         # finished sentences, in order
        self.held = []          # sentences waiting to be pasted (hold key still down / Kalam window focused)
        self.secs = 0.0
        self.preview = ''
        self.last_preview = 0.0
        self.lock = threading.Lock()


class App:
    def __init__(self, qapp, start_hidden):
        self.qapp = qapp
        config.ensure_data_dir()
        self.cfg = config.load()
        self.engine = Engine(self.cfg)
        self.recorder = Recorder(self.cfg)
        self.ui = queue.Queue()     # work for the Qt thread
        self.jobs = queue.Queue()   # finished sentences / one-shot audio / model reloads, in order
        self.preview_req = None     # latest caption request (only the newest one matters)
        self.state = 'loading'
        self.mode = None            # 'hold' | 'toggle' while recording
        self.session = None
        self.sid = 0
        self.paused = False
        self.pressed = set()
        self.toggle_latched = False
        self.rec_started = 0.0
        self.downloading = False
        self.last_target = 0        # the last non-Kalam window that had focus

        self.overlay = Overlay()
        self.bubble = Bubble(self.cfg['bubble_x'], self.cfg['bubble_y'], self.cfg['bubble_dock'],
                             self.cfg['bubble_skin'], self.cfg['bubble_size'])
        self.bubble.clicked.connect(self.on_toggle)
        self.bubble.menu_requested.connect(self._bubble_menu)
        self.bubble.placed.connect(self._bubble_placed)
        self.win = MainWindow(self.cfg)
        self.win.mic_clicked.connect(self.on_toggle)
        self.win.model_chosen.connect(self.choose_model)
        self.win.settings_clicked.connect(lambda: self.open_settings('General'))
        self.win.teach_clicked.connect(lambda: self.open_settings('Teach Kalam'))
        self.win.history_clicked.connect(lambda: self.open_settings('History'))
        self.win.learn_requested.connect(self._learn_from_window)
        self.win.closed_to_tray.connect(self._closed_to_tray)
        self._tray()
        self.pump = QTimer(timeout=self._pump, interval=30)
        self.ticker = QTimer(timeout=self._tick, interval=80)
        self.dl_timer = QTimer(timeout=self._download_progress, interval=1000)
        self.focus_watch = QTimer(timeout=self._track_focus, interval=250)
        QApplication.styleHints().colorSchemeChanged.connect(self._retheme)
        if not start_hidden:
            self.win.show_front()

    # ── tray / menus ─────────────────────────────────────────────────────────
    def _tray(self):
        self.tray = QSystemTrayIcon(mic_icon('loading'))
        m = QMenu()
        m.addAction('Open Kalam', self.win.show_front)
        m.addAction('Settings…', lambda: self.open_settings('General'))
        m.addAction('Teach Kalam…', lambda: self.open_settings('Teach Kalam'))
        m.addAction('History…', lambda: self.open_settings('History'))
        m.addSeparator()
        self.pause_action = QAction('Pause', m, checkable=True, triggered=self.toggle_pause)
        m.addAction(self.pause_action)
        self.bubble_action = QAction('Floating mic', m, checkable=True, checked=self.cfg['show_bubble'],
                                     triggered=lambda on: self.apply_settings(dict(self.cfg, show_bubble=on)))
        m.addAction(self.bubble_action)
        self.live_action = QAction('Live mode', m, checkable=True, checked=self.cfg['live_mode'],
                                   triggered=lambda on: self.apply_settings(dict(self.cfg, live_mode=on)))
        m.addAction(self.live_action)
        m.addSeparator()
        m.addAction('Quit Kalam', self.quit)
        self.tray_menu = m
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.win.show_front() if r in (
            QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick) else None)
        self.tray.show()

    def _bubble_menu(self, at):
        m = QMenu()
        if self.bubble.dock:
            m.addAction('Tucked into the edge (drag it out to free it)').setEnabled(False)
        else:
            m.addAction('Tuck into the edge', self.bubble.tuck)
        m.addAction('Change its look…', lambda: self.open_settings('Floating mic'))
        m.addSeparator()
        m.addAction('Open Kalam', self.win.show_front)
        m.addAction('Settings…', lambda: self.open_settings('General'))
        m.addAction('Hide floating mic', lambda: self.apply_settings(dict(self.cfg, show_bubble=False)))
        m.exec(at)

    def _bubble_placed(self, x, y, dock):
        self.cfg.update(bubble_x=x, bubble_y=y, bubble_dock=dock)
        config.save(self.cfg)

    def _closed_to_tray(self):
        if not self.cfg.get('tray_tip_shown'):
            self.tray.showMessage('Kalam is still running',
                                  'Use the floating mic or hold ' + self.cfg['hold_key'].title()
                                  + ' to dictate. Right-click the tray icon to quit.', mic_icon('ready'), 5000)
            self.cfg['tray_tip_shown'] = True
            config.save(self.cfg)

    def _track_focus(self):
        hwnd = user32.GetForegroundWindow()
        if hwnd and not _is_own(hwnd) and _title(hwnd) not in ('', 'Program Manager'):
            self.last_target = hwnd

    def _paste(self, text):
        """Type `text` where you were working. False if there is nowhere to put it (then it goes to the clipboard)."""
        target = user32.GetForegroundWindow()
        if _is_own(target):
            # Kalam's own window is in front (e.g. you clicked its mic): go back to the app you were in
            target = self.last_target
            if not _bring_back(target):
                logging.info('paste: no app to go back to, using the clipboard')
                return False
        logging.info('paste %d chars into %r', len(text), _title(target))
        inserter.insert(text, self.cfg['insert_method'])
        return True

    def _retheme(self, *_):
        theme.apply(self.qapp)
        theme.style_titlebar(self.win)

    # ── state ────────────────────────────────────────────────────────────────
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
        self.bubble.set_state(icon_state, self.recorder.level)

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
        self.sid += 1
        self.session = Session(self.sid, mode, self.cfg['live_mode'])
        self.mode, self.rec_started = mode, time.time()
        self.overlay.clear_caption()
        self.set_state('listen')
        self.ticker.start()
        if self.session.live:
            threading.Thread(target=self._watch, args=(self.session,), daemon=True).start()

    def _tick(self):
        if not self.mode:
            self.ticker.stop()
            return
        s = self.session
        secs = time.time() - self.rec_started
        if s and s.live:
            hint = '  ·  writes when you pause' if self.mode == 'toggle' else '  ·  writes when you let go'
        else:
            hint = '  ·  Esc cancels' if self.mode == 'toggle' else ''
        show = s and s.live and self.cfg['show_caption']
        caption = ' '.join(s.texts + ([s.preview] if s.preview else [])) if show else None
        self.overlay.show_msg(f'{self._status_text()}{hint}', 'listen', level=self.recorder.level, caption=caption)
        self.win.set_state('listen', self._status_text(), self.recorder.level)
        self.bubble.set_state('listen', self.recorder.level)
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
        s = self.session
        self.mode = None
        audio = self.recorder.stop()
        self.set_state('work')
        if s.live:
            with s.lock:  # the watcher must not cut another sentence from audio we're about to send
                s.stopped = True
                start16 = int(s.commit_raw * SR / self.recorder.rate)
            caption = ' '.join(s.texts + ([s.preview] if s.preview else [])) if self.cfg['show_caption'] else ''
            self.overlay.show_msg('Writing…', 'work', caption=caption or None)
            self.jobs.put(('sentence', (s, audio[start16:], True)))
        else:
            self.overlay.show_msg('Writing…', 'work')
            self.jobs.put(('audio', (s, audio)))

    def cancel(self):
        if not self.mode:
            return
        s = self.session
        self.mode = None
        with s.lock:
            s.stopped = s.cancelled = True
        self.recorder.stop()
        self.set_state('ready')
        self.overlay.clear_caption()
        self.overlay.show_msg('Cancelled', 'info', 1.0)

    # ── live mode: cut sentences at pauses (watcher thread) ──────────────────
    def _watch(self, s):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        vad = VadOptions(min_silence_duration_ms=250, speech_pad_ms=120)
        while not s.stopped:
            time.sleep(LIVE_TICK)
            with s.lock:
                if s.stopped:
                    return
                seg, total = self.recorder.audio_since(s.commit_raw)
                secs = len(seg) / SR
                if secs < 0.5:
                    continue
                ts = get_speech_timestamps(seg, vad)
                if not ts:
                    if secs > 4:  # long silence before speaking: drop it so the piece doesn't grow
                        s.commit_raw = max(s.commit_raw, total - int(0.5 * self.recorder.rate))
                    continue
                end = ts[-1]['end']
                silence = (len(seg) - end) / SR
                cut = None
                if silence >= self.cfg['live_pause']:
                    cut = min(len(seg), end + int(0.25 * SR))
                elif secs > MAX_SENTENCE:
                    # too long without a real pause: cut at the longest gap between speech parts
                    gaps = [(ts[i + 1]['start'] - ts[i]['end'], ts[i]['end']) for i in range(len(ts) - 1)]
                    cut = max(gaps)[1] + int(0.1 * SR) if gaps else len(seg)
                if cut:
                    piece = seg[:cut]
                    s.commit_raw += int(cut * self.recorder.rate / SR)
                    s.preview = ''
                    self.jobs.put(('sentence', (s, piece, False)))
                    continue
            # still talking: ask for a caption refresh (the worker does it when it's free)
            if time.time() - s.last_preview > PREVIEW_EVERY and (len(seg) - end) / SR < 0.6:
                s.last_preview = time.time()
                self.preview_req = (s, seg[:end + int(0.1 * SR)])

    # ── worker thread: model, sentences, captions ────────────────────────────
    def worker(self):
        while True:
            try:
                kind, payload = self.jobs.get(timeout=0.05)
            except queue.Empty:
                req, self.preview_req = self.preview_req, None
                if req and not req[0].stopped and self.engine.model:
                    self._preview(*req)
                continue
            if kind == 'quit':
                return
            if kind == 'load':
                self._load()
                continue
            try:
                if kind == 'sentence':
                    self._sentence(*payload)
                else:
                    self._one_shot(*payload)
            except Exception:  # noqa: BLE001
                logging.exception('transcribe')
                self.ui.put(lambda: self._done('Error, see kalam.log', 'error', 3))

    def _preview(self, s, audio):
        try:
            s.preview = self.engine.preview(audio)
        except Exception:  # noqa: BLE001
            logging.exception('preview')

    def _sentence(self, s, audio, last):
        if s.cancelled:
            return
        text, info = self.engine.transcribe(audio)
        s.secs += info.get('secs', 0)
        logging.info('sentence%s %s %s', ' (last)' if last else '', info, text)
        if text:
            s.texts.append(text)
        if s.cancelled:
            return
        # paste now, unless the hold key is still down
        if text and not last and s.mode == 'toggle' and self._paste(' '.join(s.held + [text]) + ' '):
            s.held = []
        elif text:
            s.held.append(text)
        if last:
            self._finish_session(s, {'secs': round(s.secs, 1), 'lang': info.get('lang', 'ar'), 'took': info.get('took')})

    def _one_shot(self, s, audio):
        text, info = self.engine.transcribe(audio)
        logging.info('%s %s', info, text)
        if text:
            s.texts.append(text)
            s.held.append(text)
        self._finish_session(s, info)

    def _finish_session(self, s, info):
        full = ' '.join(s.texts)
        if not full:
            self.ui.put(lambda: self._done('Didn’t catch anything', 'info', 1.2))
            return
        self._history(full, info)
        rest = ' '.join(s.held)
        if rest and not self._paste(rest + (' ' if self.cfg['trailing_space'] else '')):
            # no app to type into: hand it over via the clipboard
            pyperclip.copy(rest)
            self.ui.put(lambda: (self.win.set_last(full), self._done('Copied · paste it with Ctrl+V', 'ok', 2.5)))
            return
        self.ui.put(lambda: (self.win.set_last(full), self._done()))

    def _load(self):
        name = self.cfg['model']
        self.downloading = not model_cached(name)
        self.ui.put(lambda: (self.set_state('loading'), self.dl_timer.start() if self.downloading else None,
                             self.win.set_footer(name), self.win.set_chip('Loading…')))
        try:
            dev = self.engine.load()
            logging.info('loaded %s on %s', name, dev)
            where = 'GPU' if dev.startswith('cuda') else 'CPU'
            self.ui.put(lambda: self._loaded(name, where))
        except Exception:  # noqa: BLE001
            logging.exception('load')
            self.ui.put(self._load_failed)

    def _loaded(self, name, where):
        self.downloading = False
        self.dl_timer.stop()
        self.set_state('ready')
        self.win.set_footer(f'{name} · {where}')
        self.win.set_chip(f'●  {where}')
        if not self.win.isVisible():
            self.overlay.show_msg('Kalam is ready', 'ok', 2.5)

    def _load_failed(self):
        self.downloading = False
        self.dl_timer.stop()
        self.set_state('error')
        self.win.set_footer('see kalam.log (Settings → Advanced)')
        self.win.set_chip('Error')
        self.overlay.show_msg('Model failed to load', 'error', 6)

    def _download_progress(self):
        if self.state != 'loading':
            return
        gb = model_download_bytes(self.cfg['model']) / 1e9
        self.win.set_state('loading', f'Downloading {self.cfg["model"]}… {gb:.1f} GB')
        self.win.set_chip('First start: downloading')
        self.tray.setToolTip(f'Kalam: downloading the model (first time only) {gb:.1f} GB')

    def _done(self, msg=None, kind='info', secs=None):
        if self.mode:  # already recording the next one
            return
        self.overlay.clear_caption()
        self.set_state('ready' if self.jobs.empty() else 'work')
        if msg:
            self.overlay.show_msg(msg, kind, secs)
        elif self.jobs.empty():
            self.overlay.hide()

    def _history(self, text, info):
        line = f'{datetime.now():%Y-%m-%d %H:%M} | {info.get("lang")} | {info.get("secs")}s -> {info.get("took")}s | {text}\n'
        with open(config.DATA_DIR / 'history.txt', 'a', encoding='utf-8') as f:
            f.write(line)

    # ── teach ────────────────────────────────────────────────────────────────
    def _learn_from_window(self, original, edited):
        pairs = learn.learn_from_edit(original, edited)
        if not pairs:
            self.win.show_tip('Nothing to learn: change a word or two, not the whole sentence.')
            return
        saved = confirm_and_learn(pairs, self.win)
        if saved:
            self.win.set_last(edited)
            self.win.show_tip('Learned:  ' + '   ·   '.join(learn.pair_text(w, r) for w, r in saved))

    # ── settings ─────────────────────────────────────────────────────────────
    def open_settings(self, page='General'):
        self.win.show_front()
        SettingsDialog(self.cfg, self.apply_settings, self.win, page).exec()

    def choose_model(self, name):
        if name and name != self.cfg['model']:
            self.apply_settings(dict(self.cfg, model=name))

    def apply_settings(self, new):
        old = dict(self.cfg)
        reload = any(new[k] != self.cfg[k] for k in RELOAD_KEYS)
        self.cfg.update(new)  # engine and recorder share this dict
        config.save(self.cfg)
        if (new['hold_key'], new['toggle_key']) != (old['hold_key'], old['toggle_key']):
            self.register_hotkeys()
        if new['bubble_skin'] != old['bubble_skin']:
            self.bubble.set_skin(new['bubble_skin'])
        if new['bubble_size'] != old['bubble_size']:
            self.bubble.set_size(new['bubble_size'])
        self.win.refresh_hint()
        self.live_action.setChecked(self.cfg['live_mode'])
        self._show_bubble()
        if (new['mic_device'], new['keep_mic_open']) != (old['mic_device'], old['keep_mic_open']):
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
        self.bubble.hide()
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
        self.focus_watch.start()
        self._show_bubble()
        return self.qapp.exec()

    def _show_bubble(self):
        self.bubble_action.setChecked(self.cfg['show_bubble'])
        if self.cfg['show_bubble'] and not self.bubble.isVisible():
            self.bubble.start()
            self.bubble.set_state(self.state)
        elif not self.cfg['show_bubble']:
            self.bubble.hide()


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
    theme.apply(qapp)

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
