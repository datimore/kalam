"""Status pill + live caption near the bottom of the screen. It never takes focus from Word / Notion."""
import ctypes

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QTextOption
from PySide6.QtWidgets import QWidget

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x8000000
WS_EX_TRANSPARENT = 0x20

COLORS = {'listen': '#E5484D', 'work': '#F5A524', 'info': '#3E8EF7', 'error': '#E5484D', 'ok': '#30A46C'}
PILL_W, PILL_H = 300, 40
CAP_W, CAP_LINES = 620, 2


def _is_arabic(text):
    first = next((ch for ch in text if ch.isalpha()), 'a')
    return '؀' <= first <= 'ۿ'


class Overlay(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text, self.kind, self.level, self.caption = '', 'info', None, ''
        self.status_font = QFont('Segoe UI', 10, QFont.DemiBold)
        self.caption_font = QFont('Segoe UI', 13)
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._styled = False
        self.resize(PILL_W, PILL_H)

    def _place(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.width() // 2, geo.bottom() - self.height() - 40)

    def _show(self):
        self._place()
        if not self.isVisible():
            self.show()
            if not self._styled:  # belt and braces: Windows must never activate this window
                hwnd = int(self.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT)
                self._styled = True
        self.update()

    def show_msg(self, text, kind='info', hide_after=None, level=None, caption=None):
        """Status line, plus (while dictating in live mode) the words heard so far."""
        self.text, self.kind, self.level = text, kind, level
        if caption is not None:
            self.caption = caption
        self.timer.stop()
        h = PILL_H + (self._caption_height() if self.caption else 0)
        w = CAP_W if self.caption else PILL_W
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        self._show()
        if hide_after:
            self.timer.start(int(hide_after * 1000))

    def clear_caption(self):
        self.caption = ''

    def _caption_height(self):
        return QFontMetrics(self.caption_font).lineSpacing() * CAP_LINES + 18

    def _tail(self, text):
        """Keep the newest words: drop from the start until it fits in the caption lines."""
        fm = QFontMetrics(self.caption_font)
        room = (CAP_W - 40) * CAP_LINES * 0.92
        words = text.split()
        while len(words) > 1 and fm.horizontalAdvance(' '.join(words)) > room:
            words.pop(0)
        return ('… ' if len(words) < len(text.split()) else '') + ' '.join(words)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 24, 27, 238))
        radius = 20 if not self.caption else 16
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)
        # status row
        p.setBrush(QColor(COLORS.get(self.kind, COLORS['info'])))
        p.drawEllipse(QRectF(16, 14, 12, 12))
        p.setPen(QColor('#EDEDEF'))
        p.setFont(self.status_font)
        p.drawText(QRectF(38, 0, self.width() - 110, PILL_H), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        if self.level is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#EDEDEF'))
            p.drawRoundedRect(QRectF(self.width() - 70, 18, max(3, min(52, self.level * 520)), 4), 2, 2)
        # live caption
        if self.caption:
            text = self._tail(self.caption)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WordWrap)
            rtl = _is_arabic(text.lstrip('… '))
            opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
            opt.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignTop)
            p.setPen(QColor('#FFFFFF'))
            p.setFont(self.caption_font)
            p.drawText(QRectF(20, PILL_H - 4, self.width() - 40, self.height() - PILL_H), text, opt)
