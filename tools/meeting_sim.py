"""Meeting mode end to end without a real call: two tracks (you / the computer's sound) are streamed in real time.
Usage: python tools/meeting_sim.py <folder with d1 z1 d2 z2 .wav> <your voice wav> [online|room] [speakers on|off]"""
import json, os, sys, tempfile, threading, time
from pathlib import Path
import numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
home = Path(tempfile.mkdtemp(prefix='kalam-meet-')); os.environ['KALAM_HOME'] = str(home)
mode = sys.argv[3] if len(sys.argv) > 3 else 'online'
spk = (sys.argv[4] if len(sys.argv) > 4 else 'on') == 'on'
(home / 'settings.json').write_text(json.dumps({'show_bubble': False, 'meeting_speakers': spk, 'your_name': 'Mohamed'}))
from try_file import read_wav
from kalam import app as kapp, meeting
from PySide6.QtWidgets import QApplication
sys.stdout.reconfigure(encoding='utf-8')
SR = 16000
folder, mine = Path(sys.argv[1]), read_wav(sys.argv[2])
others = {k: read_wav(folder / f'{k}.wav') for k in ('d1', 'z1', 'd2', 'z2')}
me_clips = [mine[int(0.0 * SR):int(5.9 * SR)], mine[int(57.6 * SR):int(63.4 * SR)], mine[int(78 * SR):int(84.6 * SR)]]
# script: who talks when
script = [('others', others['d1']), ('me', me_clips[0]), ('others', others['z1']), ('others', others['d2']),
          ('me', me_clips[1]), ('others', others['z2']), ('me', me_clips[2])]
tracks = {'me': [], 'others': []}
t = 1.0
for who, clip in script:
    tracks[who].append((t, clip)); t += len(clip) / SR + 1.2
total = int((t + 1) * SR)
audio = {k: np.zeros(total, np.float32) for k in tracks}
for who, items in tracks.items():
    for start, clip in items:
        audio[who][int(start * SR):int(start * SR) + len(clip)] += clip
if mode == 'online':
    audio['me'] += 0.12 * audio['others']                  # no headphones: the mic hears the others quietly
else:                                                    # one room, one mic: everyone is on the mic
    audio['me'] = audio['me'] + audio['others'] * 0.8; audio['others'][:] = 0
print(f'meeting: {total / SR:.0f} s, mode={mode}, speakers={"on" if spk else "off"}')
if os.environ.get('KALAM_ENROLL'):  # 'Record my voice' with a different recording of the same person
    from kalam import speakers
    speakers.save_my_voice(read_wav(os.environ['KALAM_ENROLL'])[20 * SR:40 * SR])
    print('your voice recorded from', os.environ['KALAM_ENROLL'])

def fake_capture(track, which, mic_name, stop, errors):
    src, i = audio[which], 0
    while not stop.is_set() and i < len(src):
        time.sleep(0.1); track.add(src[i:i + SR // 10]); i += SR // 10
    while not stop.is_set():
        time.sleep(0.1)
meeting._capture = fake_capture

def drive(a):
    while a.state != 'ready':
        time.sleep(0.2)
    a.ui.put(a.start_meeting)
    time.sleep(total / SR + 0.5)
    t0 = time.time(); a.ui.put(a.stop_meeting)
    while not a.last_meeting:
        time.sleep(0.3)
    print(f'saved {time.time() - t0:.1f} s after stopping -> {a.last_meeting}\n')
    print(Path(a.last_meeting).read_text(encoding='utf-8'))
    os.remove(a.last_meeting)
    a.ui.put(a.quit)

qapp = QApplication(sys.argv); qapp.setQuitOnLastWindowClosed(False)
a = kapp.App(qapp, start_hidden=True)
threading.Thread(target=drive, args=(a,), daemon=True).start()
a.run()
