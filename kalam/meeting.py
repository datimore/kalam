"""Meeting mode: records your mic and the computer's sound (the other people in Zoom / Teams / Meet) as two
tracks, transcribes them in the background while the meeting runs, and writes a Markdown transcript at the end.

Who said what:
- Online meeting: your mic is you; the computer's sound is everyone else, told apart by voice (optional).
- In-room meeting (nothing comes out of the computer): one mic hears everyone; speakers are told apart by
  voice and you are found by your recorded voice.
"""
import ctypes
import difflib
import logging
import os
import re
import shutil
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from . import config, speakers

SR = 16000
BLOCK = SR // 10          # 0.1 s
PAUSE = 0.8               # silence that ends a piece
MAX_PIECE = 25.0          # Whisper works on 30 s windows
MERGE_GAP = 2.5           # same speaker again within this many seconds: same paragraph
OTHERS = 'Others'


def meetings_dir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL: Documents (follows OneDrive)
    d = Path(buf.value or Path.home() / 'Documents') / 'Kalam Meetings'
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_name():
    name = os.environ.get('USERNAME', '') or 'Me'
    return name.split()[0] if name.split() else 'Me'


class Track:
    """One audio source at 16 kHz, kept in memory (int16) and on disk; padded with silence to stay on the clock."""

    def __init__(self, name, path, t0):
        self.name, self.t0 = name, t0
        self.lock = threading.Lock()
        self.chunks, self.total, self.level = [], 0, 0.0
        self.wav = wave.open(str(path), 'wb')
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(SR)

    def _append(self, x16):
        with self.lock:
            self.chunks.append(x16)
            self.total += len(x16)
        self.wav.writeframes(x16.tobytes())

    def add(self, x):
        # Windows sends nothing from the speakers while nothing plays: fill the gap so both tracks share one clock
        behind = int((time.time() - self.t0) * SR) - len(x) - self.total
        if behind > SR // 3:
            self._append(np.zeros(behind, np.int16))
        self.level = float(np.sqrt(np.mean(x ** 2))) if len(x) else 0.0
        self._append((np.clip(x, -1, 1) * 32767).astype(np.int16))

    def pad_to(self, t):
        behind = int((t - self.t0) * SR) - self.total
        if behind > 0:
            self._append(np.zeros(behind, np.int16))

    def since(self, start):
        with self.lock:
            chunks, total = list(self.chunks), self.total
        need = total - start
        if need <= 0:
            return np.zeros(0, np.float32), total
        parts, got = [], 0
        for c in reversed(chunks):
            parts.append(c)
            got += len(c)
            if got >= need:
                break
        return np.concatenate(parts[::-1])[-need:].astype(np.float32) / 32768, total

    def all(self):
        with self.lock:
            return (np.concatenate(self.chunks).astype(np.float32) / 32768) if self.chunks else np.zeros(0, np.float32)

    def close(self):
        self.wav.close()


def _find_mic(sc, name):
    if name:
        for m in sc.all_microphones():
            if name.lower() in m.name.lower() or m.name.lower() in name.lower():
                return m
    return sc.default_microphone()


def _capture(track, which, mic_name, stop, errors):
    try:
        # soundcard sets up COM itself on import and fails if this thread already did, so import first
        # (always on a fresh capture thread, never Qt's), then make sure this thread joined COM too
        import soundcard as sc
        ctypes.windll.ole32.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED; harmless if already done
        if which == 'me':
            dev = _find_mic(sc, mic_name)
        else:
            dev = sc.get_microphone(id=str(sc.default_speaker().name), include_loopback=True)
        with dev.recorder(samplerate=SR, channels=1, blocksize=BLOCK) as rec:
            while not stop.is_set():
                data = rec.record(numframes=BLOCK)
                track.add(data[:, 0] if data.ndim > 1 else data)
    except Exception as e:  # noqa: BLE001
        logging.exception('meeting capture (%s)', which)
        errors.append(f'{which}: {e}')


class Meeting:
    def __init__(self, cfg, on_piece):
        self.cfg, self.on_piece = cfg, on_piece
        self.started = datetime.now()
        self.tmp = config.DATA_DIR / 'meetings_tmp' / self.started.strftime('%Y%m%d-%H%M%S')
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.t0 = time.time()
        self.tracks = {n: Track(n, self.tmp / f'{n}.wav', self.t0) for n in ('me', 'others')}
        self.segments = []          # {'track', 'start', 'end', 'text'}
        self.stop_event = threading.Event()
        self.errors = []
        self.threads = []
        self.ended = None
        self.commit = {'me': 0, 'others': 0}
        self.lock = threading.RLock()  # on_piece may call add() while a watcher holds it

    def start(self):
        for name in self.tracks:
            self.threads.append(threading.Thread(
                target=_capture, args=(self.tracks[name], name, self.cfg['mic_device'], self.stop_event, self.errors),
                daemon=True))
        for name in self.tracks:
            self.threads.append(threading.Thread(target=self._watch, args=(name,), daemon=True))
        for t in self.threads:
            t.start()

    def elapsed(self):
        return (self.ended or time.time()) - self.t0

    @property
    def level(self):
        return self.tracks['me'].level

    # cut each track at pauses and hand pieces to the transcriber while the meeting runs
    def _watch(self, name):
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        vad = VadOptions(min_silence_duration_ms=250, speech_pad_ms=150)
        track = self.tracks[name]
        while not self.stop_event.is_set():
            time.sleep(0.3)
            with self.lock:
                start = self.commit[name]
                seg, total = track.since(start)
                secs = len(seg) / SR
                if secs < 1.0:
                    continue
                ts = get_speech_timestamps(seg, vad)
                if not ts:
                    if secs > 5:  # silence: move on so the piece doesn't grow
                        self.commit[name] = total - SR // 2
                    continue
                silence = (len(seg) - ts[-1]['end']) / SR
                cut = None
                if silence >= PAUSE:
                    cut = min(len(seg), ts[-1]['end'] + SR // 4)
                elif secs > MAX_PIECE:
                    gaps = [(ts[i + 1]['start'] - ts[i]['end'], ts[i]['end']) for i in range(len(ts) - 1)]
                    cut = max(gaps)[1] + SR // 10 if gaps else len(seg)
                if cut:
                    self.commit[name] = start + cut
                    self.on_piece(self, name, start / SR, seg[:cut])

    def stop(self):
        """Stop recording; the unfinished end of each track goes to the transcriber."""
        self.ended = time.time()
        self.stop_event.set()
        for t in self.threads:
            t.join(timeout=2)
        with self.lock:
            for name, track in self.tracks.items():
                track.pad_to(self.ended)
                track.close()
                rest, _ = track.since(self.commit[name])
                if len(rest) > SR // 2:
                    self.on_piece(self, name, self.commit[name] / SR, rest)
                self.commit[name] = track.total

    def add(self, track, offset, segments):
        with self.lock:
            for s, e, text in segments:
                self.segments.append({'track': track, 'start': offset + s, 'end': offset + e, 'text': text})

    # ── after the meeting ────────────────────────────────────────────────────
    def build(self):
        """Work out who said what and write the transcript. Returns (path, people)."""
        me_name = (self.cfg.get('your_name') or default_name()).strip()
        mine = sorted((s for s in self.segments if s['track'] == 'me'), key=lambda s: s['start'])
        theirs = sorted((s for s in self.segments if s['track'] == 'others'), key=lambda s: s['start'])
        mine = [s for s in mine if not _is_echo(s, theirs)]
        diarize = self.cfg.get('meeting_speakers', True) and speakers.available()

        if theirs:  # online meeting
            for s in mine:
                s['who'] = me_name
            if diarize:
                audio = self.tracks['others'].all()
                _label(theirs, speakers.diarize(audio), None, me_name)
            else:
                for s in theirs:
                    s['who'] = OTHERS
        else:       # everyone in one room, one mic
            if diarize and mine:
                audio = self.tracks['me'].all()
                turns = speakers.diarize(audio)
                _label(mine, turns, speakers.find_me(audio, turns), me_name)
            else:
                for s in mine:
                    s['who'] = me_name
        rows = _merge(sorted(mine + theirs, key=lambda s: s['start']))
        path = write_markdown(self.started, self.elapsed(), rows, me_name)
        self._tidy(path)
        return path, _people(rows)

    def _tidy(self, md_path):
        if self.cfg.get('keep_meeting_audio'):
            dst = md_path.with_name(md_path.stem + ' audio')
            dst.mkdir(exist_ok=True)
            for f in self.tmp.glob('*.wav'):
                shutil.move(str(f), dst / ('you.wav' if f.stem == 'me' else 'others.wav'))
        shutil.rmtree(self.tmp, ignore_errors=True)


def _is_echo(seg, theirs):
    """Without headphones your mic also hears the others: drop what matches the computer's sound at that time."""
    for o in theirs:
        if o['end'] < seg['start'] - 1 or o['start'] > seg['end'] + 1:
            continue
        if difflib.SequenceMatcher(None, seg['text'], o['text']).ratio() > 0.45:
            return True
    return False


def _label(segs, turns, me_idx, me_name):
    """Give each segment the speaker who talks most during it; number the others in order of appearance."""
    numbers = {}
    for s in segs:
        overlap = {}
        for start, end, spk in turns:
            o = min(end, s['end']) - max(start, s['start'])
            if o > 0:
                overlap[spk] = overlap.get(spk, 0) + o
        if not overlap:  # no turn covers it: nearest one
            near = min(turns, key=lambda t: abs((t[0] + t[1]) / 2 - (s['start'] + s['end']) / 2), default=None)
            overlap = {near[2]: 1} if near else {}
        spk = max(overlap, key=overlap.get) if overlap else -1
        if spk == me_idx:
            s['who'] = me_name
        else:
            numbers.setdefault(spk, len(numbers) + 1)
            s['who'] = f'Speaker {numbers[spk]}'


def _merge(segs):
    rows = []
    for s in segs:
        if rows and rows[-1]['who'] == s['who'] and s['start'] - rows[-1]['end'] < MERGE_GAP:
            rows[-1]['text'] += ' ' + s['text']
            rows[-1]['end'] = s['end']
        else:
            rows.append(dict(s))
    return rows


def _people(rows):
    seen = []
    for r in rows:
        if r['who'] not in seen:
            seen.append(r['who'])
    return seen


def _clock(secs):
    secs = int(secs)
    return f'{secs // 3600:02d}:{secs % 3600 // 60:02d}:{secs % 60:02d}'


def _languages(rows):
    text = ' '.join(r['text'] for r in rows)
    langs = []
    if re.search(r'[\u0600-\u06ff]', text):
        langs.append('Arabic')
    if re.search(r'[A-Za-z]{3,}', text):
        langs.append('English')
    return ', '.join(langs) or '-'


def write_markdown(started, duration, rows, me_name):
    people = _people(rows)
    title = f'Meeting · {started:%d %b %Y, %H:%M}'
    lines = [f'# {title}', '',
             f'- **Date:** {started:%A %d %B %Y, %H:%M}',
             f'- **Length:** {max(1, round(duration / 60))} min',
             f'- **People:** {", ".join(people) if people else "-"}',
             f'- **Languages:** {_languages(rows)}',
             '', '## Transcript', '']
    if not rows:
        lines.append('_Nothing was said, or nothing could be heard._')
    for r in rows:
        lines.append(f'**[{_clock(r["start"])}] {r["who"]}:** {r["text"]}')
        lines.append('')
    path = meetings_dir() / f'{started:%Y-%m-%d %H.%M} Meeting.md'
    path.write_text('\n'.join(lines), encoding='utf-8')
    return path


# ── after the fact: list, rename, hand to an AI ──────────────────────────────
_ROW = re.compile(r'^\*\*\[(\d\d:\d\d:\d\d)\] (.+?):\*\* ', re.M)


def list_meetings():
    """Newest first: [{'path', 'title', 'people', 'length'}]"""
    out = []
    for p in sorted(meetings_dir().glob('*.md'), key=lambda p: p.stat().st_mtime, reverse=True):
        text = p.read_text(encoding='utf-8')
        title = text.splitlines()[0].lstrip('# ').strip() if text else p.stem
        people = re.search(r'\*\*People:\*\* (.*)', text)
        length = re.search(r'\*\*Length:\*\* (.*)', text)
        out.append({'path': p, 'title': title, 'people': people.group(1) if people else '',
                    'length': length.group(1) if length else ''})
    return out


def speakers_in(path):
    return speakers_in_text(Path(path).read_text(encoding='utf-8'))


def rename_speakers(path, names):
    """names: {old: new}. Rewrites the transcript and the People line."""
    path = Path(path)
    text = path.read_text(encoding='utf-8')
    for old, new in names.items():
        new = new.strip()
        if new and new != old:
            text = re.sub(rf'^(\*\*\[\d\d:\d\d:\d\d\] ){re.escape(old)}(:\*\* )', rf'\g<1>{new}\g<2>', text, flags=re.M)
    people = speakers_in_text(text)
    text = re.sub(r'(\*\*People:\*\* ).*', lambda m: m.group(1) + ', '.join(people), text, count=1)
    path.write_text(text, encoding='utf-8')


def speakers_in_text(text):
    return _people([{'who': m.group(2)} for m in _ROW.finditer(text)])


def ai_prompt(path):
    transcript = Path(path).read_text(encoding='utf-8')
    return f"""Below is the transcript of a meeting. It was transcribed automatically from Egyptian Arabic mixed with
English, so a few words may be misheard. "Speaker 1", "Speaker 2"… are people whose names the app didn't know:
if the conversation makes it clear who they are, use their names.

Please write:
1. Summary: 3 to 5 sentences.
2. Key decisions.
3. Action items: who does what, by when (if a date was mentioned).
4. Open questions and follow-ups.

Write it in the same language mix the meeting used. Keep it short and practical.

{transcript}
"""
