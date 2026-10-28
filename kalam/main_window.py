"""The mini window: big mic in your chosen look, status, last dictation (fix it to teach Kalam), model, shortcuts."""
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMainWindow, QPlainTextEdit, QVBoxLayout, QWidget

from . import __version__, config, theme
from .icons import STATE_COLORS, mic_icon
from .skins import Skin
from .widgets import button, card, keycap, label


class SkinButton(QWidget):
    """The big mic in the window, drawn in the same look as the floating mic."""
    clicked = Signal()
    SIZE = 118

    def __init__(self, skin_id):
        super().__init__()
        self.state, self.level, self.angle = 'loading', 0.0, 0
        self.skin = Skin(skin_id, self)
        self.skin.changed.connect(self.update)
        self.setFixedSize(QSize(self.SIZE + 34, self.SIZE + 34))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Click to start / stop dictation')
        self.spinner = QTimer(self, interval=30, timeout=self._spin)

    def _spin(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def set_state(self, state, level=0.0):
        self.state, self.level = state, level
        self.spinner.start() if state == 'work' else self.spinner.stop()
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, r = self.width() / 2, self.height() / 2, self.SIZE / 2
        if self.state == 'listen':  # ring grows with the voice level
            halo = QColor(STATE_COLORS['listen'])
            halo.setAlpha(60)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            rr = r + 5 + min(12, self.level * 140)
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
        self.skin.paint(p, QRectF(cx - r, cy - r, 2 * r, 2 * r), self.state, self.level, self.angle)


class MainWindow(QMainWindow):
    mic_clicked = Signal()
    model_chosen = Signal(str)
    settings_clicked = Signal()
    history_clicked = Signal()
    teach_clicked = Signal()
    learn_requested = Signal(str, str)  # what Kalam wrote, what you corrected it to
    closed_to_tray = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.quitting = False
        self.original = ''
        self.setWindowTitle('Kalam · كلام')
        self.setWindowIcon(mic_icon('ready'))
        self.setFixedWidth(400)

        # header
        title = label('Kalam', 'h1')
        sub = label('كلام', 'muted')
        sub.setFont(QFont('Segoe UI', 13))
        self.chip = label('Loading…', 'chip')
        head = QHBoxLayout()
        head.addWidget(title)
        head.addWidget(sub)
        head.addStretch(1)
        head.addWidget(self.chip)

        # hero: the mic
        hero = card()
        self.mic = SkinButton(cfg['bubble_skin'])
        self.mic.clicked.connect(self.mic_clicked)
        self.status = label('Loading…', 'status')
        self.status.setAlignment(Qt.AlignCenter)
        self.keys = QHBoxLayout()
        self.keys.setSpacing(6)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(16, 14, 16, 16)
        hl.addWidget(self.mic, 0, Qt.AlignHCenter)
        hl.addWidget(self.status)
        hl.addSpacing(6)
        hl.addLayout(self.keys)

        # last dictation: fix a word here and press Learn
        last = card()
        self.copy = button('Copy', theme.I_COPY, 'ghost', 'Copy to the clipboard')
        self.copy.clicked.connect(self._copy)
        self.learn = button('Learn', theme.I_TEACH, 'accent', 'Teach Kalam the words you corrected')
        self.learn.setEnabled(False)
        self.learn.clicked.connect(lambda: self.learn_requested.emit(self.original, self.last.toPlainText()))
        top = QHBoxLayout()
        top.addWidget(label('Last dictation', 'section'))
        top.addStretch(1)
        top.addWidget(self.copy)
        top.addWidget(self.learn)
        self.last = QPlainTextEdit()
        self.last.setPlaceholderText('What you dictate shows up here.')
        self.last.setFont(QFont('Segoe UI', 11))
        self.last.setFixedHeight(104)
        self.last.textChanged.connect(self._edited)
        self.tip = label('Wrong word? Correct it above and press Learn. Kalam fixes it from now on.', 'small', wrap=True)
        ll = QVBoxLayout(last)
        ll.setContentsMargins(14, 10, 14, 12)
        ll.addLayout(top)
        ll.addWidget(self.last)
        ll.addWidget(self.tip)

        # footer
        self.model = QComboBox(editable=True)
        self.model.addItems(config.MODELS)
        self.model.setCurrentText(cfg['model'])
        self.model.setFixedWidth(150)
        self.model.setToolTip('Whisper model (large-v3 = best for Egyptian Arabic)')
        self.model.activated.connect(lambda _: self.model_chosen.emit(self.model.currentText().strip()))
        self.model.lineEdit().returnPressed.connect(lambda: self.model_chosen.emit(self.model.currentText().strip()))
        teach = button('Teach', theme.I_TEACH, 'ghost', 'Teach Kalam your words, with your AI')
        history = button('History', theme.I_HISTORY, 'ghost', 'Everything you dictated')
        settings = button('', theme.I_SETTINGS, 'ghost', 'Settings')
        teach.clicked.connect(self.teach_clicked)
        history.clicked.connect(self.history_clicked)
        settings.clicked.connect(self.settings_clicked)
        foot = QHBoxLayout()
        foot.addWidget(self.model)
        foot.addStretch(1)
        foot.addWidget(teach)
        foot.addWidget(history)
        foot.addWidget(settings)
        self.footer = label('', 'small')
        self.footer.setAlignment(Qt.AlignCenter)

        lay = QVBoxLayout()
        lay.setContentsMargins(18, 14, 18, 10)
        lay.setSpacing(12)
        lay.addLayout(head)
        lay.addWidget(hero)
        lay.addWidget(last)
        lay.addLayout(foot)
        lay.addWidget(self.footer)
        central = QWidget()
        central.setObjectName('page')
        central.setLayout(lay)
        self.setCentralWidget(central)
        self.refresh_hint()

    def refresh_hint(self):
        while self.keys.count():
            item = self.keys.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.keys.addStretch(1)
        self.keys.addWidget(keycap(self.cfg['hold_key'].title()))
        self.keys.addWidget(label('hold', 'small'))
        self.keys.addSpacing(10)
        self.keys.addWidget(keycap(self.cfg['toggle_key'].title()))
        self.keys.addWidget(label('start / stop', 'small'))
        self.keys.addStretch(1)
        self.model.setCurrentText(self.cfg['model'])
        self.mic.skin.set(self.cfg['bubble_skin'])

    def set_state(self, state, text, level=0.0):
        self.mic.set_state(state, level)
        self.status.setText(text)

    def set_chip(self, text):
        self.chip.setText(text)

    def set_last(self, text):
        # right-align when the dictation starts in Arabic
        first = next((ch for ch in text if ch.isalpha()), 'a')
        rtl = '؀' <= first <= 'ۿ'  # Arabic block
        opt = self.last.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        opt.setAlignment(Qt.AlignRight if rtl else Qt.AlignLeft)
        self.last.document().setDefaultTextOption(opt)
        self.original = text
        self.last.setPlainText(text)
        self.learn.setEnabled(False)

    def _edited(self):
        self.learn.setEnabled(bool(self.original) and self.last.toPlainText().strip() != self.original.strip())

    def show_tip(self, text, secs=5):
        """Temporary message under the last dictation (e.g. what Kalam just learned)."""
        self.tip.setText(text)
        QTimer.singleShot(secs * 1000, lambda: self.tip.setText(
            'Wrong word? Correct it above and press Learn. Kalam fixes it from now on.'))

    def set_footer(self, text):
        self.footer.setText(f'{text} · v{__version__}')

    def _copy(self):
        QGuiApplication.clipboard().setText(self.last.toPlainText())
        self.copy.setText('Copied')
        QTimer.singleShot(1200, lambda: self.copy.setText('Copy'))

    def showEvent(self, e):
        super().showEvent(e)
        theme.style_titlebar(self)

    def closeEvent(self, e):
        # ✕ hides to the tray: the shortcut and floating mic keep working; Quit is in the tray menu
        if self.quitting:
            e.accept()
            return
        e.ignore()
        self.hide()
        self.closed_to_tray.emit()

    def show_front(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
