"""Put text where the cursor is, in whatever app has focus."""
import time

import keyboard
import pyperclip

MODIFIERS = ['ctrl', 'alt', 'shift', 'windows']


def _wait_modifiers_released(timeout=2.0):
    # Ctrl+V sent while the user still holds Alt would become Ctrl+Alt+V
    end = time.time() + timeout
    while time.time() < end and any(keyboard.is_pressed(m) for m in MODIFIERS):
        time.sleep(0.02)


def insert(text, method='paste'):
    if not text:
        return
    _wait_modifiers_released()
    if method == 'type':
        keyboard.write(text, delay=0.002)
        return
    try:
        old = pyperclip.paste()
    except pyperclip.PyperclipException:
        old = None
    pyperclip.copy(text)
    time.sleep(0.03)
    keyboard.send('ctrl+v')
    time.sleep(0.35)  # let the app read the clipboard before restoring it
    if old:
        try:
            pyperclip.copy(old)
        except pyperclip.PyperclipException:
            pass
