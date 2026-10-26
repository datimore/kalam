"""Microphone capture -> float32 mono 16 kHz."""
import collections
import threading

import numpy as np
import sounddevice as sd

SR = 16000
PREROLL = 0.4  # seconds kept before the key press when the mic stays open


def list_mics():
    """Full device names (WASAPI when present, else the default host API)."""
    apis = sd.query_hostapis()
    wasapi = next((i for i, a in enumerate(apis) if 'WASAPI' in a['name']), None)
    api = wasapi if wasapi is not None else sd.default.hostapi
    return [d['name'] for d in sd.query_devices() if d['max_input_channels'] > 0 and d['hostapi'] == api]


def _find_device(name):
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d['max_input_channels'] > 0 and d['name'] == name:
            return i
    return None  # unplugged -> Windows default


def _to_16k(x, rate):
    if rate == SR or not len(x):
        return x
    # low-pass below the new Nyquist, then resample
    cutoff = 0.95 * (SR / 2) / rate
    n = np.arange(-32, 33)
    taps = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(len(n))
    x = np.convolve(x, taps / taps.sum(), mode='same')
    t_new = np.arange(0, len(x) / rate, 1 / SR)
    return np.interp(t_new, np.arange(len(x)) / rate, x).astype(np.float32)


class Recorder:
    def __init__(self, cfg):
        self.cfg = cfg
        self.stream = None
        self.rate = SR
        self.lock = threading.Lock()
        self.recording = False
        self.chunks = []
        self.preroll = collections.deque()
        self.level = 0.0  # for the on-screen meter

    def _callback(self, data, frames, time_info, status):
        x = data[:, 0].copy()
        self.level = float(np.sqrt(np.mean(x ** 2)))
        with self.lock:
            if self.recording:
                self.chunks.append(x)
            elif self.cfg['keep_mic_open']:
                self.preroll.append(x)
                while sum(len(c) for c in self.preroll) > PREROLL * self.rate:
                    self.preroll.popleft()

    def _open(self):
        if self.stream is not None:
            return
        dev = _find_device(self.cfg['mic_device'])
        self.rate = int(sd.query_devices(dev if dev is not None else sd.default.device[0])['default_samplerate'])
        self.stream = sd.InputStream(device=dev, channels=1, samplerate=self.rate, dtype='float32',
                                     blocksize=int(self.rate * 0.05), callback=self._callback)
        self.stream.start()

    def _close(self):
        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

    def apply_settings(self):
        """Reopen with the current mic / keep-open setting."""
        self._close()
        self.preroll.clear()
        if self.cfg['keep_mic_open']:
            self._open()

    def start(self):
        with self.lock:
            self.chunks = list(self.preroll)
            self.preroll.clear()
            self.recording = True
        self._open()

    def stop(self):
        with self.lock:
            self.recording = False
            chunks, self.chunks = self.chunks, []
        if not self.cfg['keep_mic_open']:
            self._close()
        self.level = 0.0
        x = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
        return _to_16k(x, self.rate)
