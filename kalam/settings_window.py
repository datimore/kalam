"""Settings window: model, language, shortcuts, mic, insert method."""
import os
import threading
import tkinter as tk
from tkinter import ttk

import keyboard

from . import audio, config

LANGS = {
    'smart': 'Egyptian Arabic + English (detects pure English)',
    'ar': 'Always Egyptian Arabic (with English words)',
    'en': 'Always English',
}
DEFAULT_MIC = '(Windows default)'


def open_file(name):
    config.ensure_data_dir()
    os.startfile(config.DATA_DIR / name)


class SettingsWindow:
    def __init__(self, root, cfg, on_save):
        self.cfg, self.on_save = cfg, on_save
        w = self.win = tk.Toplevel(root)
        w.title('Kalam settings')
        w.resizable(False, False)
        w.attributes('-topmost', True)
        f = ttk.Frame(w, padding=16)
        f.pack(fill='both')
        self.v = {}
        row = 0

        def label(text):
            nonlocal row
            ttk.Label(f, text=text).grid(row=row, column=0, sticky='w', pady=4, padx=(0, 12))

        label('Whisper model')
        self.v['model'] = tk.StringVar(value=cfg['model'])
        ttk.Combobox(f, textvariable=self.v['model'], values=config.MODELS, width=44).grid(row=row, column=1, columnspan=2, sticky='we')
        row += 1
        ttk.Label(f, text='large-v3 = best for Egyptian. Turbo = faster. You can also paste a Hugging Face model id.',
                  foreground='#666').grid(row=row, column=1, columnspan=2, sticky='w')
        row += 1

        label('Run on')
        self.v['device'] = tk.StringVar(value=cfg['device'])
        ttk.Combobox(f, textvariable=self.v['device'], values=['auto', 'cuda', 'cpu'], state='readonly', width=12).grid(row=row, column=1, sticky='w')
        row += 1

        label('Language')
        self.v['language'] = tk.StringVar(value=LANGS[cfg['language']])
        ttk.Combobox(f, textvariable=self.v['language'], values=list(LANGS.values()), state='readonly', width=44).grid(row=row, column=1, columnspan=2, sticky='we')
        row += 1

        for key, text in (('hold_key', 'Hold to talk'), ('toggle_key', 'Press to start / stop')):
            label(text)
            self.v[key] = tk.StringVar(value=cfg[key])
            ttk.Entry(f, textvariable=self.v[key], width=30).grid(row=row, column=1, sticky='we')
            ttk.Button(f, text='Set…', command=lambda k=key: self.capture(k)).grid(row=row, column=2, sticky='e', padx=(8, 0))
            row += 1

        label('Microphone')
        mics = [DEFAULT_MIC] + audio.list_mics()
        self.v['mic_device'] = tk.StringVar(value=cfg['mic_device'] or DEFAULT_MIC)
        ttk.Combobox(f, textvariable=self.v['mic_device'], values=mics, state='readonly', width=44).grid(row=row, column=1, columnspan=2, sticky='we')
        row += 1

        label('Insert text by')
        self.v['insert_method'] = tk.StringVar(value=cfg['insert_method'])
        ttk.Combobox(f, textvariable=self.v['insert_method'], values=['paste', 'type'], state='readonly', width=12).grid(row=row, column=1, sticky='w')
        row += 1

        for key, text in (('trailing_space', 'Add a space after each dictation'),
                          ('use_context', 'Remember my last sentence (keeps the style consistent)'),
                          ('remove_fillers', 'Remove fillers (إممم، ااا، umm)'),
                          ('keep_mic_open', 'Keep mic open so the first word is never cut')):
            self.v[key] = tk.BooleanVar(value=cfg[key])
            ttk.Checkbutton(f, text=text, variable=self.v[key]).grid(row=row, column=0, columnspan=3, sticky='w')
            row += 1

        files = ttk.Frame(f)
        files.grid(row=row, column=0, columnspan=3, sticky='w', pady=(12, 0))
        for name, text in (('prompt_ar.txt', 'My Egyptian style prompt'), ('words.txt', 'Hint words'), ('fixes.txt', 'Fixes')):
            ttk.Button(files, text=text, command=lambda n=name: open_file(n)).pack(side='left', padx=(0, 6))
        row += 1

        btns = ttk.Frame(f)
        btns.grid(row=row, column=0, columnspan=3, sticky='e', pady=(16, 0))
        ttk.Button(btns, text='Cancel', command=w.destroy).pack(side='right')
        ttk.Button(btns, text='Save', command=self.save).pack(side='right', padx=6)
        w.focus_force()

    def capture(self, key):
        var = self.v[key]
        var.set('press the keys…')

        def run():
            hk = keyboard.read_hotkey(suppress=False)
            self.win.after(0, lambda: var.set(hk))
        threading.Thread(target=run, daemon=True).start()

    def save(self):
        new = dict(self.cfg)
        for k, var in self.v.items():
            new[k] = var.get()
        new['language'] = next(k for k, v in LANGS.items() if v == new['language'])
        if new['mic_device'] == DEFAULT_MIC:
            new['mic_device'] = ''
        new['model'] = new['model'].strip() or 'large-v3'
        self.win.destroy()
        self.on_save(new)
