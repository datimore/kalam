"""Windows integration: start with Windows (HKCU Run key)."""
import os
import sys
import winreg

from . import config

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


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
