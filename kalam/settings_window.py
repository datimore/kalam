"""Kalam's control centre: General, Floating mic, Teach Kalam, History, Shortcuts, Advanced.

Every change applies at once (no Save button). Fixes are written straight to fixes.txt.
"""
import os
import threading

import keyboard
from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit, QProgressBar,
                               QPushButton, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from . import audio, config, learn, meeting, skins, speakers, system, theme
from .bubble import SIZES
from .widgets import Segmented, Toggle, button, card, label, row

LANGS = {
    'smart': 'Egyptian Arabic + English',
    'ar': 'Always Egyptian Arabic',
    'en': 'Always English',
}
PAUSES = [('Quick', 0.6), ('Normal', 1.0), ('Relaxed', 1.5)]
DEFAULT_MIC = 'Windows default'
PAGES = ['General', 'Floating mic', 'Meetings', 'Teach Kalam', 'History', 'Shortcuts', 'Advanced']
PROMPT_HEADER = ('# The style Whisper copies. Keep it SHORT: it should describe how you talk, not contain topics.\n'
                 '# Longer prompts with real sentences make Whisper reuse their words or skip parts of what you said.\n')
DEFAULT_PROMPT = 'كلام بالمصري، والكلمات الـ English بتتكتب English.'


def open_file(name):
    config.ensure_data_dir()
    path = config.DATA_DIR / name
    if not path.exists():
        path.write_text('', encoding='utf-8')
    os.startfile(path)


def _is_rtl(text):
    first = next((ch for ch in text if ch.isalpha()), 'a')
    return '\u0600' <= first <= '\u06ff'  # Arabic block


def _rtl(widget, text):
    rtl = _is_rtl(text)
    opt = widget.document().defaultTextOption()
    opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
    opt.setAlignment(Qt.AlignRight if rtl else Qt.AlignLeft)
    widget.document().setDefaultTextOption(opt)


class _Captured(QObject):
    done = Signal(str)


class ConfirmFixes(QDialog):
    """Shows what Kalam is about to learn; untick anything that would be a bad rule."""

    def __init__(self, pairs, parent=None, title='Kalam will learn these'):
        super().__init__(parent)
        self.setWindowTitle('Teach Kalam')
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label(title, 'h2'))
        lay.addWidget(label('Untick anything that is a real word you also use elsewhere.', 'muted', wrap=True))
        self.list = QListWidget()
        self.list.setObjectName('list')
        for wrong, right in pairs:
            it = QListWidgetItem(learn.pair_text(wrong, right))
            it.setData(Qt.UserRole, (wrong, right))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.list.addItem(it)
        self.list.setMinimumHeight(min(320, 46 * len(pairs) + 16))
        lay.addWidget(self.list)
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button('Cancel')
        save = button('Learn', theme.I_CHECK, 'accent')
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)
        theme.style_titlebar(self)

    def chosen(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


def confirm_and_learn(pairs, parent):
    """Returns the fixes that were saved (possibly none)."""
    if not pairs:
        return []
    dlg = ConfirmFixes(pairs, parent)
    if dlg.exec() != QDialog.Accepted:
        return []
    return learn.add_fixes(dlg.chosen())


class RenameSpeakers(QDialog):
    def __init__(self, people, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Rename speakers')
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label('Who is who?', 'h2'))
        lay.addWidget(label('Type the real names; the transcript is updated everywhere.', 'muted', wrap=True))
        self.edits = {}
        for p in people:
            e = QLineEdit(p)
            e.setFixedWidth(200)
            self.edits[p] = e
            lay.addWidget(row(p, e))
        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel, save = button('Cancel'), button('Save', theme.I_CHECK, 'accent')
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(save)
        lay.addLayout(btns)
        theme.style_titlebar(self)

    def names(self):
        return {old: e.text() for old, e in self.edits.items()}


class VoiceDialog(QDialog):
    """Records 20 seconds of your voice and keeps its fingerprint (never the audio)."""
    SECS = 20
    TEXT = ('أهلاً، أنا بسجّل صوتي عشان Kalam يعرفني في الـ meetings. النهارده عندنا شوية tasks محتاجين نخلّصها، '
            'وأول حاجة هنراجع الـ dashboard ونشوف الـ numbers بتاعة الأسبوع اللي فات. بعد كده هنتكلم عن الـ plan '
            'بتاع الشهر الجاي، ومين هيمسك إيه. لو فيه أي أسئلة قولوا، وأنا هبعت الـ notes بعد الـ meeting.')

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle('Record my voice')
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.addWidget(label('Record your voice', 'h2'))
        lay.addWidget(label(f'Press Start and read this out loud the way you normally talk ({self.SECS} seconds):',
                            'muted', wrap=True))
        text = QPlainTextEdit(self.TEXT)
        text.setReadOnly(True)
        text.setFixedHeight(110)
        _rtl(text, self.TEXT)
        lay.addWidget(text)
        self.bar = QProgressBar()
        self.bar.setRange(0, self.SECS * 10)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        self.status = label('Kalam keeps only a voice fingerprint, not the recording.', 'small', wrap=True)
        lay.addWidget(self.status)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self.close_b, self.start_b = button('Close'), button('Start', theme.I_RECORD, 'accent')
        self.close_b.clicked.connect(self.reject)
        self.start_b.clicked.connect(self._start)
        btns.addWidget(self.close_b)
        btns.addWidget(self.start_b)
        lay.addLayout(btns)
        self.timer = QTimer(self, interval=100, timeout=self._tick)
        theme.style_titlebar(self)

    def _start(self):
        self.rec = audio.Recorder(dict(self.cfg, keep_mic_open=False))
        try:
            self.rec.start()
        except Exception as e:  # noqa: BLE001
            self.status.setText(f'Microphone error: {e}')
            return
        self.start_b.setEnabled(False)
        self.ticks = 0
        self.status.setText('Listening… read the text above.')
        self.timer.start()

    def _tick(self):
        self.ticks += 1
        self.bar.setValue(self.ticks)
        if self.ticks < self.SECS * 10:
            return
        self.timer.stop()
        clip = self.rec.stop()
        self.status.setText('Saving…')
        QGuiApplication.processEvents()
        try:
            speakers.save_my_voice(clip)
            self.status.setText('Done. Kalam will recognise you in meetings.')
            self.start_b.setText('Record again')
        except Exception as e:  # noqa: BLE001
            self.status.setText(f'Could not save it: {e}')
        self.start_b.setEnabled(True)


class SettingsDialog(QDialog):
    def __init__(self, cfg, on_change, parent=None, page='General'):
        super().__init__(parent)
        self.cfg, self.on_change = cfg, on_change
        self.setWindowTitle('Kalam settings')
        self.resize(820, 600)
        self.nav = QListWidget()
        self.nav.setObjectName('nav')
        self.nav.setFixedWidth(170)
        self.stack = QStackedWidget()
        builders = [self._general, self._floating, self._meetings, self._teach, self._history, self._shortcuts,
                    self._advanced]
        for name, build in zip(PAGES, builders):
            self.nav.addItem(name)
            self.stack.addWidget(self._scroll(build()))
        self.nav.currentRowChanged.connect(self._goto)
        done = button('Done', None, 'accent')
        done.clicked.connect(self.accept)
        left = QVBoxLayout()
        left.addWidget(label('Settings', 'h2'))
        left.addSpacing(6)
        left.addWidget(self.nav, 1)
        left.addWidget(done)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        lay.addLayout(left)
        lay.addWidget(self.stack, 1)
        self.nav.setCurrentRow(PAGES.index(page) if page in PAGES else 0)

    def showEvent(self, e):
        super().showEvent(e)
        theme.style_titlebar(self)

    def _goto(self, i):
        self.stack.setCurrentIndex(i)
        if PAGES[i] == 'History':
            self._load_history()
        if PAGES[i] == 'Teach Kalam':
            self._load_fixes()
        if PAGES[i] == 'Meetings':
            self._load_meetings()

    def _scroll(self, page):
        page.setObjectName('page')
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        return sa

    def _set(self, **kw):
        self.on_change(dict(self.cfg, **kw))

    def _page(self, title, subtitle=None):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 0, 12, 12)
        lay.setSpacing(12)
        lay.addWidget(label(title, 'h1'))
        if subtitle:
            lay.addWidget(label(subtitle, 'muted', wrap=True))
        return w, lay

    def _card(self, lay, title=None):
        c = card()
        cl = QVBoxLayout(c)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(6)
        if title:
            cl.addWidget(label(title, 'section'))
        lay.addWidget(c)
        return cl

    def _toggle(self, key, on_toggle=None):
        t = Toggle(bool(self.cfg[key]))
        t.toggled.connect(on_toggle or (lambda v, k=key: self._set(**{k: v})))
        return t

    # ── General ──────────────────────────────────────────────────────────────
    def _general(self):
        w, lay = self._page('General')
        c = self._card(lay, 'Live mode')
        c.addWidget(row('Write each sentence as soon as you pause', self._toggle('live_mode'),
                        'You see the words live in a caption while you talk. With the floating mic or '
                        'the start / stop shortcut, every sentence lands in your document when you pause. '
                        'Holding the key writes everything when you let go, almost instantly.'))
        pause = Segmented(PAUSES, min(PAUSES, key=lambda p: abs(p[1] - self.cfg['live_pause']))[1])
        pause.changed.connect(lambda v: self._set(live_pause=v))
        c.addWidget(row('Pause that ends a sentence', pause, 'Relaxed waits longer, for people who stop to think.'))
        c.addWidget(row('Show the live caption', self._toggle('show_caption'),
                        'A strip at the bottom of the screen with what Kalam hears while you talk. '
                        'Your text still goes straight into your document.'))
        c.addWidget(row('Show the status strip', self._toggle('show_status'),
                        'Listening / Writing… at the bottom of the screen. Off: the floating mic\'s ring shows it.'))

        c = self._card(lay, 'Speaking')
        lang = QComboBox()
        lang.addItems(list(LANGS.values()))
        lang.setCurrentText(LANGS[self.cfg['language']])
        lang.currentTextChanged.connect(lambda v: self._set(language=next(k for k, x in LANGS.items() if x == v)))
        c.addWidget(row('Language', lang, 'Pure-English sentences are detected automatically.'))
        mic = QComboBox()
        mic.addItems([DEFAULT_MIC] + audio.list_mics())
        mic.setCurrentText(self.cfg['mic_device'] or DEFAULT_MIC)
        mic.setMaximumWidth(260)
        mic.currentTextChanged.connect(lambda v: self._set(mic_device='' if v == DEFAULT_MIC else v))
        c.addWidget(row('Microphone', mic))

        c = self._card(lay, 'Text')
        c.addWidget(row('Add a space after each dictation', self._toggle('trailing_space')))
        c.addWidget(row('Remove filler sounds', self._toggle('remove_fillers'), 'umm, uh, إممم, ااا'))

        c = self._card(lay, 'App')
        auto = Toggle(system.autostart_enabled())
        auto.toggled.connect(system.set_autostart)
        c.addWidget(row('Start Kalam when I sign in to Windows', auto))
        lay.addStretch(1)
        return w

    # ── Floating mic ─────────────────────────────────────────────────────────
    def _floating(self):
        w, lay = self._page('Floating mic', 'A mic that floats on top of every window. Click it to talk, '
                                             'drag it anywhere, drop it on a screen edge to tuck it away.')
        c = self._card(lay)
        c.addWidget(row('Show the floating mic', self._toggle('show_bubble')))
        size = Segmented(list(SIZES.items()), self.cfg['bubble_size'])
        size.changed.connect(lambda v: self._set(bubble_size=v))
        c.addWidget(row('Size', size))

        c = self._card(lay, 'Look')
        c.addWidget(label('Pick a look, or use any picture or GIF. The ring shows what Kalam is doing.', 'small', wrap=True))
        self.skin_grid = QGridLayout()
        self.skin_grid.setSpacing(6)
        c.addLayout(self.skin_grid)
        own = button('Use my own picture or GIF…', theme.I_IMAGE)
        own.clicked.connect(self._pick_image)
        c.addWidget(own, 0, Qt.AlignLeft)
        self._fill_skins()
        lay.addStretch(1)
        return w

    def _fill_skins(self):
        while self.skin_grid.count():
            self.skin_grid.takeAt(0).widget().deleteLater()
        ids = list(skins.BUILTIN)
        if self.cfg['bubble_skin'] not in ids:
            ids.append(self.cfg['bubble_skin'])  # the user's own picture
        for i, sid in enumerate(ids):
            b = QPushButton()
            b.setObjectName('skin')
            b.setCheckable(True)
            b.setChecked(sid == self.cfg['bubble_skin'])
            b.setIcon(QIcon(skins.preview_pixmap(sid, 48)))
            b.setIconSize(QSize(48, 48))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip('Classic mic' if sid == 'mic' else ('Your picture' if sid.startswith('image:') else sid[6:]))
            b.clicked.connect(lambda _=False, s=sid: self._choose_skin(s))
            self.skin_grid.addWidget(b, i // 8, i % 8)

    def _choose_skin(self, sid):
        self._set(bubble_skin=sid)
        self._fill_skins()

    def _pick_image(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Choose a picture or GIF', os.path.expanduser('~'),
                                              'Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)')
        if path:
            self._choose_skin(skins.import_image(path))

    # ── Meetings ─────────────────────────────────────────────────────────────
    def _meetings(self):
        w, lay = self._page('Meetings', 'Kalam writes down a whole meeting: who said what, in Arabic and English. '
                                        'Nothing shows on screen while it records; the floating mic turns violet.')
        c = self._card(lay, 'Start and stop')
        c.addWidget(label(f'Right-click the floating mic > Start meeting mode, or press {self.cfg["meeting_key"].title()}. '
                          'Click the floating mic (or press the shortcut again) to stop: the transcript is saved and '
                          'a notification opens it.', 'muted', wrap=True))
        c.addWidget(label('It records your microphone and the sound of your computer (the other people in Zoom, '
                          'Teams or Meet). Let everyone know you are recording.', 'small', wrap=True))

        c = self._card(lay, 'People')
        c.addWidget(row('Tell the other people apart', self._toggle('meeting_speakers'),
                        'Speaker 1, Speaker 2… by voice. Off: everyone else is "Others".'))
        name = QLineEdit(self.cfg['your_name'] or meeting.default_name())
        name.setFixedWidth(200)
        name.editingFinished.connect(lambda: self._set(your_name=name.text().strip()))
        c.addWidget(row('Your name in transcripts', name))
        self.voice_status = label('', 'small', wrap=True)
        rec = button('Record my voice', theme.I_RECORD)
        rec.clicked.connect(self._record_voice)
        rec.setEnabled(speakers.available())
        vb = QWidget()
        vl = QHBoxLayout(vb)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(rec)
        c.addWidget(row('Your voice', vb, 'For meetings in one room with one microphone: Kalam finds you among '
                                         'the speakers. 20 seconds, once.'))
        c.addWidget(self.voice_status)
        self._voice_label()

        c = self._card(lay, 'Files')
        folder = button(str(meeting.meetings_dir()), theme.I_FOLDER, 'ghost', 'Open the folder')
        folder.clicked.connect(lambda: os.startfile(meeting.meetings_dir()))
        c.addWidget(folder, 0, Qt.AlignLeft)
        c.addWidget(row('Keep the recordings', self._toggle('keep_meeting_audio'),
                        'Saves your track and the others\' track next to each transcript.'))

        c = self._card(lay, 'Your meetings')
        self.meet_list = QListWidget()
        self.meet_list.setObjectName('list')
        self.meet_list.setMinimumHeight(170)
        self.meet_list.itemDoubleClicked.connect(lambda _: self._open_meeting())
        c.addWidget(self.meet_list)
        mb = QHBoxLayout()
        for text, glyph, fn, kind in (('Open', theme.I_OPEN, self._open_meeting, None),
                                      ('Rename speakers…', theme.I_RENAME, self._rename_meeting, None),
                                      ('Copy for AI', theme.I_COPY, self._copy_meeting, 'accent')):
            b = button(text, glyph, kind)
            b.clicked.connect(fn)
            mb.addWidget(b)
        mb.insertStretch(2, 1)
        c.addLayout(mb)
        self.meet_note = label('Copy for AI copies the transcript with a prompt: paste it into ChatGPT, Claude or '
                               'Gemini for a summary, decisions and action items.', 'small', wrap=True)
        c.addWidget(self.meet_note)
        lay.addStretch(1)
        return w

    def _voice_label(self):
        if not speakers.available():
            self.voice_status.setText('Speaker models are missing from this installation.')
        elif speakers.my_voice() is not None:
            self.voice_status.setText('Recorded. You can record it again any time.')
        else:
            self.voice_status.setText('Not recorded yet.')

    def _record_voice(self):
        VoiceDialog(self.cfg, self).exec()
        self._voice_label()

    def _load_meetings(self):
        self.meet_list.clear()
        for m in meeting.list_meetings():
            it = QListWidgetItem(f'{m["title"]}\n{m["length"]}  ·  {m["people"]}')
            it.setData(Qt.UserRole, str(m['path']))
            self.meet_list.addItem(it)
        if not self.meet_list.count():
            it = QListWidgetItem('No meetings yet.')
            it.setFlags(Qt.NoItemFlags)
            self.meet_list.addItem(it)
        else:
            self.meet_list.setCurrentRow(0)

    def _picked_meeting(self):
        it = self.meet_list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _open_meeting(self):
        path = self._picked_meeting()
        if path:
            os.startfile(path)

    def _copy_meeting(self):
        path = self._picked_meeting()
        if path:
            QGuiApplication.clipboard().setText(meeting.ai_prompt(path))
            self.meet_note.setText('Copied: paste it into your AI.')

    def _rename_meeting(self):
        path = self._picked_meeting()
        if not path:
            return
        dlg = RenameSpeakers(meeting.speakers_in(path), self)
        if dlg.exec() == QDialog.Accepted:
            meeting.rename_speakers(path, dlg.names())
            self._load_meetings()

    # ── Teach Kalam ──────────────────────────────────────────────────────────
    def _teach(self):
        w, lay = self._page('Teach Kalam', 'Kalam fixes words it keeps getting wrong. Teach it in one of two ways; '
                                           'no files to edit.')
        c = self._card(lay, 'Quickest: correct it right away')
        c.addWidget(label('After a dictation, fix the wrong word in the Kalam window (Last dictation) and press '
                          'Learn. You can do the same for any older dictation in History.', 'muted', wrap=True))

        c = self._card(lay, 'Ask your AI (ChatGPT, Claude, Gemini…)')
        c.addWidget(label('Your AI knows your work and the names you use. Kalam gives it your recent dictations '
                          'and it tells Kalam what was misheard.', 'muted', wrap=True))
        n = len(learn.recent_dictations())
        step1 = QHBoxLayout()
        step1.addWidget(label('1.  Copy the prompt and paste it into your AI'))
        step1.addStretch(1)
        self.copy_prompt = button('Copy prompt', theme.I_COPY, 'accent')
        self.copy_prompt.setToolTip(f'Includes your last {n} dictations')
        self.copy_prompt.clicked.connect(self._copy_prompt)
        step1.addWidget(self.copy_prompt)
        c.addLayout(step1)
        c.addWidget(label('2.  Paste its answer here'))
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText('wrong = right\nwrong = right\n…')
        self.answer.setFixedHeight(96)
        self.answer.textChanged.connect(self._parse_answer)
        c.addWidget(self.answer)
        step3 = QHBoxLayout()
        self.found = label('', 'small')
        step3.addWidget(self.found)
        step3.addStretch(1)
        self.add_answer = button('Review and learn', theme.I_CHECK, 'accent')
        self.add_answer.setEnabled(False)
        self.add_answer.clicked.connect(self._learn_answer)
        step3.addWidget(self.add_answer)
        c.addLayout(step3)

        c = self._card(lay, 'Your fixes')
        c.addWidget(label('Applied to every dictation. Edit, add or delete them here.', 'small'))
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Kalam writes', 'Change it to'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setMinimumHeight(220)
        self.table.itemChanged.connect(self._save_table)
        c.addWidget(self.table)
        tb = QHBoxLayout()
        add = button('Add', theme.I_ADD)
        delete = button('Delete', theme.I_DELETE)
        add.clicked.connect(self._add_row)
        delete.clicked.connect(self._delete_rows)
        tb.addWidget(add)
        tb.addWidget(delete)
        tb.addStretch(1)
        c.addLayout(tb)
        lay.addStretch(1)
        self._load_fixes()
        return w

    def _copy_prompt(self):
        QGuiApplication.clipboard().setText(learn.ai_prompt())
        self.copy_prompt.setText('Copied: paste it into your AI')

    def _parse_answer(self):
        self.parsed = learn.parse_ai_answer(self.answer.toPlainText())
        n = len(self.parsed)
        self.found.setText(f'Found {n} fix{"es" if n != 1 else ""}' if self.answer.toPlainText().strip() else '')
        self.add_answer.setEnabled(n > 0)

    def _learn_answer(self):
        saved = confirm_and_learn(self.parsed, self)
        if saved:
            self.answer.clear()
            self.found.setText(f'Learned {len(saved)} fix{"es" if len(saved) != 1 else ""}')
            self._load_fixes()

    def _load_fixes(self):
        if not hasattr(self, 'table'):
            return
        self.table.blockSignals(True)
        pairs = learn.read_fixes()
        self.table.setRowCount(len(pairs))
        for i, (wrong, right) in enumerate(pairs):
            self.table.setItem(i, 0, QTableWidgetItem(wrong))
            self.table.setItem(i, 1, QTableWidgetItem(right))
        self.table.blockSignals(False)

    def _table_pairs(self):
        out = []
        for i in range(self.table.rowCount()):
            w, r = self.table.item(i, 0), self.table.item(i, 1)
            if w and w.text().strip():
                out.append((w.text().strip(), r.text().strip() if r else ''))
        return out

    def _save_table(self, *_):
        learn.write_fixes(self._table_pairs())

    def _add_row(self):
        self.table.blockSignals(True)
        self.table.insertRow(0)
        self.table.setItem(0, 0, QTableWidgetItem(''))
        self.table.setItem(0, 1, QTableWidgetItem(''))
        self.table.blockSignals(False)
        self.table.editItem(self.table.item(0, 0))

    def _delete_rows(self):
        for i in sorted({ix.row() for ix in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(i)
        self._save_table()

    # ── History ──────────────────────────────────────────────────────────────
    def _history(self):
        w, lay = self._page('History', 'Everything you dictated, newest first. Select one to copy it, '
                                       'or correct a word and press Learn.')
        self.hist = QListWidget()
        self.hist.setObjectName('list')
        self.hist.setWordWrap(True)
        self.hist.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hist.setMinimumHeight(230)
        self.hist.currentItemChanged.connect(self._pick_history)
        lay.addWidget(self.hist, 1)
        self.hist_text = QPlainTextEdit()
        self.hist_text.setFont(QFont('Segoe UI', 11))
        self.hist_text.setFixedHeight(96)
        self.hist_text.textChanged.connect(
            lambda: self.hist_learn.setEnabled(self.hist_text.toPlainText().strip() != self._hist_original.strip()))
        lay.addWidget(self.hist_text)
        hb = QHBoxLayout()
        openf = button('Open history file', None, 'ghost')
        openf.clicked.connect(lambda: open_file('history.txt'))
        hb.addWidget(openf)
        hb.addStretch(1)
        copy = button('Copy', theme.I_COPY)
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.hist_text.toPlainText()))
        self.hist_learn = button('Learn', theme.I_TEACH, 'accent')
        self.hist_learn.setEnabled(False)
        self.hist_learn.clicked.connect(self._learn_history)
        hb.addWidget(copy)
        hb.addWidget(self.hist_learn)
        lay.addLayout(hb)
        self._hist_original = ''
        return w

    def _load_history(self):
        self.hist.clear()
        for d in learn.recent_dictations(300):
            rtl = _is_rtl(d['text'])
            # RLE…PDF makes mixed Arabic / English read in the right order inside the list
            text = f'\u202b{d["text"]}\u202c' if rtl else d['text']
            it = QListWidgetItem(f'{d["time"]}\n{text}')
            it.setTextAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter)
            it.setData(Qt.UserRole, d['text'])
            self.hist.addItem(it)

    def _pick_history(self, item):
        self._hist_original = item.data(Qt.UserRole) if item else ''
        _rtl(self.hist_text, self._hist_original)
        self.hist_text.setPlainText(self._hist_original)
        self.hist_learn.setEnabled(False)

    def _learn_history(self):
        pairs = learn.learn_from_edit(self._hist_original, self.hist_text.toPlainText())
        saved = confirm_and_learn(pairs, self)
        if saved:
            self._hist_original = self.hist_text.toPlainText()
            self.hist_learn.setEnabled(False)

    # ── Shortcuts ────────────────────────────────────────────────────────────
    def _shortcuts(self):
        w, lay = self._page('Shortcuts', 'They work in every app. Esc cancels while Kalam is listening.')
        c = self._card(lay)
        for key, text, hint in (('hold_key', 'Hold to talk', 'Hold, speak, let go.'),
                                ('toggle_key', 'Press to start / stop', 'For longer dictation; nothing to hold.'),
                                ('meeting_key', 'Meeting mode', 'Start recording a meeting; press again to save it.')):
            edit = QLineEdit(self.cfg[key])
            edit.setFixedWidth(170)
            edit.editingFinished.connect(lambda e=edit, k=key: self._save_key(e, k))
            setb = button('Set…')
            setb.clicked.connect(lambda _=False, e=edit, k=key: self._capture(e, k))
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.addWidget(edit)
            bl.addWidget(setb)
            c.addWidget(row(text, box, hint))
        c.addWidget(label('Avoid Alt+Shift: Windows uses it to switch keyboard language.', 'small', wrap=True))
        lay.addStretch(1)
        return w

    def _save_key(self, edit, key):
        text = edit.text().strip()
        if not text or edit.property('capturing'):
            edit.setText(self.cfg[key])  # never save an empty shortcut or the placeholder
            return
        if text != self.cfg[key]:
            self._set(**{key: text})

    def _capture(self, edit, key):
        edit.setProperty('capturing', True)
        edit.clear()
        edit.setPlaceholderText('press the keys…')
        sig = _Captured(self)
        sig.done.connect(lambda hk: (edit.setProperty('capturing', False), edit.setText(hk or self.cfg[key]),
                                     self._save_key(edit, key)))
        threading.Thread(target=lambda: sig.done.emit(keyboard.read_hotkey(suppress=False)), daemon=True).start()

    # ── Advanced ─────────────────────────────────────────────────────────────
    def _advanced(self):
        w, lay = self._page('Advanced', 'The defaults were picked by testing on real Egyptian Arabic + English. '
                                        'Change these only if you have a reason to.')
        c = self._card(lay, 'Speech model')
        model = QComboBox(editable=True)
        model.addItems(config.MODELS)
        model.setCurrentText(self.cfg['model'])
        model.setFixedWidth(200)
        model.activated.connect(lambda _: self._set(model=model.currentText().strip() or 'large-v3'))
        c.addWidget(row('Whisper model', model, 'large-v3 is the most accurate for Egyptian Arabic; turbo is faster. '
                                                'A Hugging Face model id works too.'))
        dev = QComboBox()
        dev.addItems(['auto', 'cuda', 'cpu'])
        dev.setCurrentText(self.cfg['device'])
        dev.currentTextChanged.connect(lambda v: self._set(device=v))
        c.addWidget(row('Run on', dev, 'auto uses your NVIDIA graphics card when there is one.'))

        c = self._card(lay, 'Typing')
        ins = QComboBox()
        ins.addItems(['paste', 'type'])
        ins.setCurrentText(self.cfg['insert_method'])
        ins.currentTextChanged.connect(lambda v: self._set(insert_method=v))
        c.addWidget(row('Insert text by', ins, 'paste is fast and restores your clipboard; type is for apps that block paste.'))
        c.addWidget(row('Keep the mic open', self._toggle('keep_mic_open'),
                        'Never cuts your first word; the Windows mic indicator stays on.'))

        c = self._card(lay, 'Style prompt')
        c.addWidget(label('One short line telling Whisper how you talk. Long prompts make it copy their words '
                          'into your text.', 'small', wrap=True))
        self.prompt = QLineEdit(config.read_text('prompt_ar.txt'))
        self.prompt.editingFinished.connect(self._save_prompt)
        reset = button('Reset')
        reset.clicked.connect(lambda: (self.prompt.setText(DEFAULT_PROMPT), self._save_prompt()))
        pr = QHBoxLayout()
        pr.addWidget(self.prompt, 1)
        pr.addWidget(reset)
        c.addLayout(pr)

        c = self._card(lay, 'Experimental')
        c.addWidget(row('Use hint words', self._toggle('use_hint_words'),
                        'Helps spell names, but in testing it made Whisper skip parts of sentences.'))
        self.words = QPlainTextEdit('\n'.join(config.read_lines('words.txt')))
        self.words.setPlaceholderText('One word or name per line')
        self.words.setFixedHeight(90)
        self.words.focusOutEvent = lambda e: (self._save_words(), QPlainTextEdit.focusOutEvent(self.words, e))
        c.addWidget(self.words)
        c.addWidget(row('Feed my last sentence back', self._toggle('use_context'),
                        'Keeps the style consistent, but one mistake can repeat in the next dictation.'))

        c = self._card(lay)
        folder = button('Open Kalam’s data folder', None, 'ghost')
        folder.clicked.connect(lambda: os.startfile(config.DATA_DIR))
        c.addWidget(folder, 0, Qt.AlignLeft)
        lay.addStretch(1)
        return w

    def _save_prompt(self):
        text = self.prompt.text().strip() or DEFAULT_PROMPT
        (config.DATA_DIR / 'prompt_ar.txt').write_text(PROMPT_HEADER + text + '\n', encoding='utf-8')

    def _save_words(self):
        path = config.DATA_DIR / 'words.txt'
        header = [ln for ln in path.read_text(encoding='utf-8-sig').splitlines() if ln.startswith('#')] \
            if path.exists() else []
        body = [ln.strip() for ln in self.words.toPlainText().splitlines() if ln.strip()]
        path.write_text('\n'.join(header + body) + '\n', encoding='utf-8')
