"""End-to-end for the floating mic: real mouse clicks on the bubble must not steal focus from the target app."""
import ctypes, ctypes.wintypes, json, os, subprocess, sys, tempfile, threading, time
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
home = Path(tempfile.mkdtemp(prefix='kalam-bubble-')); os.environ['KALAM_HOME'] = str(home)
(home / 'settings.json').write_text(json.dumps({'bubble_x': 900, 'bubble_y': 260, 'bubble_dock': ''}))
from try_file import read_wav
from kalam import app as kapp
from kalam.audio import SR
from PySide6.QtWidgets import QApplication

wav, out = sys.argv[1], os.path.join(os.environ['TEMP'], 'kalam_target.txt')
clip = read_wav(wav)[57 * SR:64 * SR]
u = ctypes.windll.user32
def log(*a): print(*a, flush=True)
def click(x, y):
    u.SetCursorPos(x, y); time.sleep(0.15); u.mouse_event(2, 0, 0, 0, 0); time.sleep(0.05); u.mouse_event(4, 0, 0, 0, 0)

def drive(a):
    real_stop = a.recorder.stop
    a.recorder.stop = lambda: (real_stop(), clip)[1]
    while a.state != 'ready':
        time.sleep(0.2)
    log('cfg bubble', a.cfg['bubble_x'], a.cfg['bubble_y'], repr(a.cfg['bubble_dock']), 'pos', a.bubble.pos(), 'data', os.environ['KALAM_HOME'])
    tgt = subprocess.Popen(['powershell', '-NoProfile', '-Command', (ROOT / 'tools' / 'target.ps1').read_text()],
                           env={**os.environ, 'KALAM_TARGET_OUT': out})
    time.sleep(3.5)
    hwnd = u.FindWindowW(None, 'Kalam test target')
    r = ctypes.wintypes.RECT(); u.GetWindowRect(hwnd, ctypes.byref(r))
    click((r.left + r.right) // 2, (r.top + r.bottom) // 2 + 20); time.sleep(0.5)
    log('target focused before:', u.GetForegroundWindow() == hwnd)
    g = a.bubble.geometry(); bx, by = g.center().x(), g.center().y()
    log('bubble at', bx, by, 'visible', a.bubble.isVisible())
    def fg():
        h = u.GetForegroundWindow(); b = ctypes.create_unicode_buffer(200); u.GetWindowTextW(h, b, 200)
        pid = ctypes.c_ulong(); u.GetWindowThreadProcessId(h, ctypes.byref(pid)); return f'{b.value!r} pid={pid.value} (kalam pid {os.getpid()})'
    pt = ctypes.wintypes.POINT(bx, by); log('window under bubble point:', u.WindowFromPoint(pt), 'bubble hwnd', int(a.bubble.winId()))
    for ev in ('mousePressEvent', 'mouseReleaseEvent', 'enterEvent'):
        orig = getattr(a.bubble, ev)
        setattr(a.bubble, ev, (lambda o, n: (lambda e: (log('bubble got', n), o(e))))(orig, ev))
    click(bx, by); time.sleep(1.2)
    log('foreground now:', fg())
    log('after 1st bubble click: state =', a.state, '| target still focused:', u.GetForegroundWindow() == hwnd)
    click(bx, by); time.sleep(6)
    log('after 2nd bubble click: target text =', open(out, encoding='utf-8-sig').read())
    tgt.kill(); a.ui.put(a.quit)

qapp = QApplication(sys.argv); qapp.setQuitOnLastWindowClosed(False)
a = kapp.App(qapp, start_hidden=True)
threading.Thread(target=drive, args=(a,), daemon=True).start()
a.run()
log('quit ok')
