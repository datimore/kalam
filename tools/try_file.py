"""Run the dictation engine on clips of a WAV file:  python tools/try_file.py file.wav [start:dur ...]"""
import sys, time, wave
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kalam import config
from kalam.engine import Engine, SR

def read_wav(path):
    with wave.open(str(path)) as wf:
        assert wf.getframerate() == SR and wf.getsampwidth() == 2, 'need 16 kHz 16-bit WAV'
        a = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768
        return a.reshape(-1, wf.getnchannels()).mean(1)

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    cfg = config.load()
    eng = Engine(cfg)
    t = time.time(); print('device', eng.load(), 'load', round(time.time() - t, 1), 's')
    audio = read_wav(sys.argv[1])
    clips = sys.argv[2:] or [f'0:{len(audio) / SR}']
    for c in clips:
        s, d = map(float, c.split(':'))
        text, info = eng.transcribe(audio[int(s * SR):int((s + d) * SR)])
        print(f'[{s:6.1f} +{d:4.1f}] {info}\n   {text}')
