"""End-to-end: real hotkeys + paste into another app; the mic audio is swapped for a WAV clip."""
import ctypes, ctypes.wintypes, os, subprocess, sys, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
from try_file import read_wav
from kalam import app as kapp
from kalam.audio import SR

wav, out = sys.argv[1], os.path.join(os.environ['TEMP'], 'kalam_target.txt')
clips = [read_wav(wav)[0:6 * SR], read_wav(wav)[57 * SR:64 * SR]]
u = ctypes.windll.user32
def key(vk, up=False, ext=False):
    u.keybd_event(vk, 0, (2 if up else 0) | (1 if ext else 0), 0)
def log(*a):
    print(*a, flush=True)

def drive(a):
    real_stop = a.recorder.stop
    a.recorder.stop = lambda: (real_stop(), log('stop called'), clips.pop(0))[2]
    while a.state != 'ready':
        time.sleep(0.2)
    log('state ready on', a.engine.device)
    external = os.environ.get('KALAM_E2E_EXTERNAL')  # focus your own app (Notepad, Word…) instead of the test box
    if external:
        go = Path(external); Path(str(go) + '.ready').write_text('1')
        log('ready: focus the target app, then create', go)
        while not go.exists():
            time.sleep(0.2)
        time.sleep(0.5); tgt = None; hwnd = u.GetForegroundWindow()
    else:
        tgt = subprocess.Popen(['powershell', '-NoProfile', '-Command', (ROOT / 'tools' / 'target.ps1').read_text()],
                               env={**os.environ, 'KALAM_TARGET_OUT': out})
        time.sleep(3.5)
        hwnd = u.FindWindowW(None, 'Kalam test target')
        r = ctypes.wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r)); u.SetCursorPos((r.left + r.right) // 2, (r.top + r.bottom) // 2 + 20)
        u.mouse_event(2, 0, 0, 0, 0); u.mouse_event(4, 0, 0, 0, 0); time.sleep(0.5)
    log('target focused:', u.GetForegroundWindow() == hwnd)
    # 1) hold Right Ctrl
    key(0xA3, ext=True); time.sleep(1.0); log('while holding, state =', a.state); key(0xA3, True, ext=True)
    time.sleep(6); log('after hold   :', '' if external else open(out, encoding='utf-8-sig').read())
    log('target still focused:', u.GetForegroundWindow() == hwnd)
    # 2) Ctrl+Alt+Space toggle
    for _ in range(2):
        key(0x11); key(0x12); key(0x20); time.sleep(0.05); key(0x20, True); key(0x12, True); key(0x11, True)
        time.sleep(1.0)
    time.sleep(6); log('after toggle :', '' if external else open(out, encoding='utf-8-sig').read())
    if tgt: tgt.kill()
    a.ui.put(a.quit)

import logging; logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
a = kapp.App()
threading.Thread(target=drive, args=(a,), daemon=True).start()
a.run()
log('quit ok')
