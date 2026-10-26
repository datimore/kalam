"""A small pill near the bottom of the screen that never takes focus from Word / Notion."""
import ctypes

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x8000000
WS_EX_TRANSPARENT = 0x20

COLORS = {'listen': '#E5484D', 'work': '#F5A524', 'info': '#3E8EF7', 'error': '#E5484D', 'ok': '#30A46C'}


class Overlay(QWidget):
    W, H = 290, 40

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
                         | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(self.W, self.H)
        self.text, self.kind, self.level = '', 'info', None
        self.timer = QTimer(self, singleShot=True, timeout=self.hide)
        self._styled = False

    def _place(self):
        geo = QGuiApplication.primaryScreen().availableGeometry()
        self.move(geo.center().x() - self.W // 2, geo.bottom() - self.H - 40)

    def show_msg(self, text, kind='info', hide_after=None, level=None):
        self.text, self.kind, self.level = text, kind, level
        self.timer.stop()
        if not self.isVisible():
            self._place()
            self.show()
            if not self._styled:  # belt and braces: Windows must never activate this window
                hwnd = int(self.winId())
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT)
                self._styled = True
        self.update()
        if hide_after:
            self.timer.start(int(hide_after * 1000))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(28, 28, 31, 240))
        p.drawRoundedRect(QRectF(0, 0, self.W, self.H), self.H / 2, self.H / 2)
        p.setBrush(QColor(COLORS.get(self.kind, COLORS['info'])))
        p.drawEllipse(QRectF(16, 14, 12, 12))
        p.setPen(QColor('#EDEDEF'))
        p.setFont(QFont('Segoe UI', 10, QFont.DemiBold))
        p.drawText(QRectF(38, 0, self.W - 100, self.H), Qt.AlignVCenter | Qt.AlignLeft, self.text)
        if self.level is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#EDEDEF'))
            p.drawRoundedRect(QRectF(self.W - 70, 18, max(3, min(52, self.level * 520)), 4), 2, 2)
