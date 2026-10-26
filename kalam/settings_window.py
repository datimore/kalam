"""Settings dialog: model, language, shortcuts, mic, insert method."""
import os
import threading

import keyboard
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget)

from . import audio, config

LANGS = {
    'smart': 'Egyptian Arabic + English (detects pure English)',
    'ar': 'Always Egyptian Arabic (with English words)',
    'en': 'Always English',
}
DEFAULT_MIC = '(Windows default)'


def open_file(name):
    config.ensure_data_dir()
    path = config.DATA_DIR / name
    if not path.exists():
        path.write_text('', encoding='utf-8')
    os.startfile(path)


class _Captured(QObject):
    done = Signal(str)


class SettingsDialog(QDialog):
    def __init__(self, cfg, on_save, parent=None):
        super().__init__(parent)
        self.cfg, self.on_save = cfg, on_save
        self.setWindowTitle('Kalam settings')
        self.setMinimumWidth(520)
        form = QFormLayout()
        form.setVerticalSpacing(10)

        self.model = QComboBox(editable=True)
        self.model.addItems(config.MODELS)
        self.model.setCurrentText(cfg['model'])
        form.addRow('Whisper model', self.model)
        hint = QLabel('large-v3 = best for Egyptian. Turbo = faster. You can also paste a Hugging Face model id.')
        hint.setWordWrap(True)
        hint.setStyleSheet('color: gray;')
        form.addRow('', hint)

        self.device = QComboBox()
        self.device.addItems(['auto', 'cuda', 'cpu'])
        self.device.setCurrentText(cfg['device'])
        form.addRow('Run on', self.device)

        self.language = QComboBox()
        self.language.addItems(list(LANGS.values()))
        self.language.setCurrentText(LANGS[cfg['language']])
        form.addRow('Language', self.language)

        self.keys = {}
        for key, text in (('hold_key', 'Hold to talk'), ('toggle_key', 'Press to start / stop')):
            edit = QLineEdit(cfg[key])
            btn = QPushButton('Set…')
            btn.clicked.connect(lambda _=False, k=key: self.capture(k))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(btn)
            w = QWidget()
            w.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.keys[key] = edit
            form.addRow(text, w)

        self.mic = QComboBox()
        self.mic.addItems([DEFAULT_MIC] + audio.list_mics())
        self.mic.setCurrentText(cfg['mic_device'] or DEFAULT_MIC)
        form.addRow('Microphone', self.mic)

        self.insert = QComboBox()
        self.insert.addItems(['paste', 'type'])
        self.insert.setCurrentText(cfg['insert_method'])
        form.addRow('Insert text by', self.insert)

        self.checks = {}
        for key, text in (('trailing_space', 'Add a space after each dictation'),
                          ('use_context', 'Remember my last sentence (keeps the style consistent)'),
                          ('remove_fillers', 'Remove fillers like “umm” and “إممم”'),
                          ('keep_mic_open', 'Keep mic open so the first word is never cut')):
            cb = QCheckBox(text)
            cb.setChecked(bool(cfg[key]))
            self.checks[key] = cb
            form.addRow('', cb)

        files = QHBoxLayout()
        for name, text in (('prompt_ar.txt', 'My Egyptian style prompt'), ('words.txt', 'Hint words'), ('fixes.txt', 'Fixes')):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, n=name: open_file(n))
            files.addWidget(b)
        files.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addLayout(files)
        lay.addSpacing(8)
        lay.addWidget(buttons)

    def capture(self, key):
        edit = self.keys[key]
        edit.setText('press the keys…')
        sig = _Captured(self)
        sig.done.connect(edit.setText)
        threading.Thread(target=lambda: sig.done.emit(keyboard.read_hotkey(suppress=False)), daemon=True).start()

    def save(self):
        new = dict(self.cfg)
        new['model'] = self.model.currentText().strip() or 'large-v3'
        new['device'] = self.device.currentText()
        new['language'] = next(k for k, v in LANGS.items() if v == self.language.currentText())
        for k, edit in self.keys.items():
            new[k] = edit.text().strip()
        new['mic_device'] = '' if self.mic.currentText() == DEFAULT_MIC else self.mic.currentText()
        new['insert_method'] = self.insert.currentText()
        for k, cb in self.checks.items():
            new[k] = cb.isChecked()
        self.accept()
        self.on_save(new)
