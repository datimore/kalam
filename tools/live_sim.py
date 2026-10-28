"""Live mode end to end, without a mic: real sentences + pauses are streamed into Kalam in real time.
Records when each piece of text would be pasted. Usage: python tools/live_sim.py voice.wav [toggle|hold]"""
import json, os, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
home = Path(tempfile.mkdtemp(prefix='kalam-live-')); os.environ['KALAM_HOME'] = str(home)
(home / 'settings.json').write_text(json.dumps({'show_bubble': False, 'live_mode': True}))
from try_file import read_wav
from kalam import app as kapp
from kalam.audio import SR
from PySide6.QtWidgets import QApplication
sys.stdout.reconfigure(encoding='utf-8')

wav, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else 'toggle')
a16 = read_wav(wav)
silence = lambda s: np.zeros(int(s * SR), np.float32)
# three real sentences from the video, separated by the kind of pause you make when dictating
pieces = [(0.0, 5.9), (57.6, 63.4), (78.0, 84.6)]
stream, ends = [silence(0.4)], []
for s, e in pieces:
    stream.append(a16[int(s * SR):int(e * SR)])
    ends.append(sum(len(x) for x in stream) / SR)
    stream.append(silence(1.6))
stream = np.concatenate(stream)

class FakeMic:
    """Stands in for Recorder: plays `stream` in real time."""
    def __init__(self): self.rate, self.level, self.t0, self.on = SR, 0.0, None, False
    def apply_settings(self): pass
    def start(self): self.t0, self.on = time.time(), True
    def _n(self): return min(len(stream), int((time.time() - self.t0) * SR)) if self.t0 else 0
    def audio_since(self, start):
        n = self._n(); return (stream[start:n].copy() if n > start else np.zeros(0, np.float32)), n
    def stop(self):
        n = self._n(); self.on = False; self.t0 = None; return stream[:n].copy()

pasted, t_start = [], [0.0]
kapp.inserter.insert = lambda text, method='paste': pasted.append((time.time() - t_start[0], text))
kapp._own_window_focused = lambda: False

def drive(a):
    a.recorder = FakeMic()
    while a.state != 'ready':
        time.sleep(0.2)
    print('sentences end in the audio at:', [round(e, 1) for e in ends], 's  | total', round(len(stream) / SR, 1), 's')
    t_start[0] = time.time()
    a.ui.put(lambda: a.start(mode))
    captions = []
    while time.time() - t_start[0] < len(stream) / SR:
        if a.session and a.session.preview and (not captions or captions[-1][1] != a.session.preview):
            captions.append((round(time.time() - t_start[0], 1), a.session.preview))
        time.sleep(0.1)
    a.ui.put(a.finish)
    t_stop = time.time() - t_start[0]
    time.sleep(6)
    print(f'\nlive captions seen ({len(captions)}):')
    for t, c in captions[:12]:
        print(f'  {t:5.1f}s  {c}')
    print(f'\npasted ({mode} mode, stopped at {t_stop:.1f}s):')
    for t, text in pasted:
        print(f'  at {t:5.1f}s  {text}')
    a.ui.put(a.quit)

qapp = QApplication(sys.argv); qapp.setQuitOnLastWindowClosed(False)
a = kapp.App(qapp, start_hidden=True)
threading.Thread(target=drive, args=(a,), daemon=True).start()
a.run()
