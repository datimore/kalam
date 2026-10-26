"""The mini window: big mic button, status, last dictation, model picker."""
from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMainWindow, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)

from . import __version__, config
from .icons import STATE_COLORS, draw_mic, mic_icon


class MicButton(QWidget):
    clicked = Signal()
    SIZE = 112

    def __init__(self):
        super().__init__()
        self.state, self.level = 'loading', 0.0
        self.setFixedSize(QSize(self.SIZE + 28, self.SIZE + 28))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Click to start / stop dictation')

    def set_state(self, state, level=0.0):
        self.state, self.level = state, level
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(STATE_COLORS.get(self.state, STATE_COLORS['ready']))
        cx, cy, r = self.width() / 2, self.height() / 2, self.SIZE / 2
        if self.state == 'listen':  # ring grows with the voice level
            halo = QColor(c)
            halo.setAlpha(70)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            rr = r + 4 + min(10, self.level * 120)
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        draw_mic(p, cx, cy, self.SIZE * 0.5)


class MainWindow(QMainWindow):
    mic_clicked = Signal()
    model_chosen = Signal(str)
    settings_clicked = Signal()
    history_clicked = Signal()
    closed_to_tray = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.quitting = False
        self.setWindowTitle('Kalam · كلام')
        self.setWindowIcon(mic_icon('ready'))
        self.setFixedWidth(340)

        self.mic = MicButton()
        self.mic.clicked.connect(self.mic_clicked)
        self.status = QLabel('Loading…', alignment=Qt.AlignCenter)
        self.status.setFont(QFont('Segoe UI', 12, QFont.DemiBold))
        self.hint = QLabel(alignment=Qt.AlignCenter)
        self.hint.setStyleSheet('color: gray;')
        self.hint.setWordWrap(True)

        self.last = QPlainTextEdit(readOnly=True)
        self.last.setPlaceholderText('Your last dictation appears here.')
        self.last.setFont(QFont('Segoe UI', 11))
        self.last.setFixedHeight(96)
        self.copy = QPushButton('Copy')
        self.copy.clicked.connect(self._copy)

        self.model = QComboBox(editable=True)
        self.model.addItems(config.MODELS)
        self.model.setCurrentText(cfg['model'])
        self.model.activated.connect(lambda _: self.model_chosen.emit(self.model.currentText().strip()))
        self.model.lineEdit().returnPressed.connect(lambda: self.model_chosen.emit(self.model.currentText().strip()))

        settings, history = QPushButton('Settings'), QPushButton('History')
        settings.clicked.connect(self.settings_clicked)
        history.clicked.connect(self.history_clicked)
        self.footer = QLabel(alignment=Qt.AlignCenter)
        self.footer.setStyleSheet('color: gray; font-size: 9pt;')

        lay = QVBoxLayout()
        lay.setContentsMargins(18, 16, 18, 12)
        lay.addWidget(self.mic, 0, Qt.AlignHCenter)
        lay.addWidget(self.status)
        lay.addWidget(self.hint)
        lay.addSpacing(10)
        last_row = QHBoxLayout()
        last_row.addWidget(QLabel('Last dictation'))
        last_row.addStretch(1)
        last_row.addWidget(self.copy)
        lay.addLayout(last_row)
        lay.addWidget(self.last)
        lay.addSpacing(8)
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel('Model'))
        model_row.addWidget(self.model, 1)
        lay.addLayout(model_row)
        btn_row = QHBoxLayout()
        btn_row.addWidget(settings)
        btn_row.addWidget(history)
        lay.addLayout(btn_row)
        lay.addSpacing(4)
        lay.addWidget(self.footer)
        central = QWidget()
        central.setLayout(lay)
        self.setCentralWidget(central)
        self.refresh_hint()

    def refresh_hint(self):
        hold, tog = self.cfg['hold_key'].title(), self.cfg['toggle_key'].title()
        self.hint.setText(f'Hold {hold} to talk · or {tog} to start / stop')
        self.model.setCurrentText(self.cfg['model'])

    def set_state(self, state, text, level=0.0):
        self.mic.set_state(state, level)
        self.status.setText(text)

    def set_last(self, text):
        # right-align when the dictation starts in Arabic
        first = next((ch for ch in text if ch.isalpha()), 'a')
        rtl = '\u0600' <= first <= '\u06ff'  # Arabic block
        opt = self.last.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        opt.setAlignment(Qt.AlignRight if rtl else Qt.AlignLeft)
        self.last.document().setDefaultTextOption(opt)
        self.last.setPlainText(text)

    def set_footer(self, text):
        self.footer.setText(f'{text} · v{__version__}')

    def _copy(self):
        QGuiApplication.clipboard().setText(self.last.toPlainText())
        self.copy.setText('Copied')
        self.copy.setEnabled(False)
        QTimer.singleShot(1200, lambda: (self.copy.setText('Copy'), self.copy.setEnabled(True)))

    def closeEvent(self, e):
        # ✕ hides to the tray: the shortcut keeps working; Quit is in the tray menu
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
