"""Floating mic bubble: always on top, click to start / stop, drag to move, drag to a screen edge to tuck it away.

It never takes focus, so clicking it leaves the cursor in Word / Notion and the text still lands there.
Its look comes from skins.py (classic mic, an emoji, or your own picture / GIF).
"""
import ctypes

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from .icons import STATE_COLORS
from .skins import Skin

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x8000000
WS_EX_TOOLWINDOW = 0x80

SIZES = {'Small': 44, 'Medium': 56, 'Large': 72}
PAD = 10            # room around the circle for the voice-level halo
SNAP = 48           # drop the bubble this close to an edge and it tucks in
DRAG_START = 5      # pixels the mouse must move before a press becomes a drag


class Bubble(QWidget):
    clicked = Signal()
    menu_requested = Signal(QPoint)
    placed = Signal(int, int, str)  # x, y, dock ('' | 'left' | 'right')

    def __init__(self, x=None, y=None, dock='', skin='mic', diameter=56):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip('Click to talk, click again to stop\nDrag to move · drag to the screen edge to tuck it away\n'
                        'Right-click for meeting mode and options')
        self.skin = Skin(skin, self)
        self.skin.changed.connect(self.update)
        self.set_size(diameter)
        self.state, self.level, self.angle = 'loading', 0.0, 0
        self.dock = dock
        self.press_pos = self.press_win = None
        self.dragging = self.hovered = False
        self.anim = QPropertyAnimation(self, b'pos', self, duration=160, easingCurve=QEasingCurve.OutCubic)
        self.spinner = QTimer(self, interval=30, timeout=self._spin)
        self.tuck_timer = QTimer(self, singleShot=True, interval=600, timeout=self._tuck_if_idle)
        self._styled = False
        self._initial = (x, y)

    def set_size(self, diameter):
        self.diameter = diameter
        self.size_ = diameter + 2 * PAD
        self.peek = max(16, int(diameter * 0.4))  # how much stays on screen when tucked
        self.setFixedSize(self.size_, self.size_)
        if self.isVisible() and self.dock:
            self.move(self._tucked_pos())
        self.update()

    def set_skin(self, skin_id):
        self.skin.set(skin_id)

    # ── placement ────────────────────────────────────────────────────────────
    def _screen_rect(self, center=None):
        center = center or self.geometry().center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        return screen.availableGeometry()

    def _out_pos(self):
        """Fully visible position for the current dock side."""
        r = self._screen_rect()
        x = r.left() - PAD + 4 if self.dock == 'left' else r.right() - self.size_ + PAD - 3
        return QPoint(x, self.y())

    def _tucked_pos(self):
        r = self._screen_rect()
        x = r.left() - self.size_ + PAD + self.peek if self.dock == 'left' else r.right() - PAD - self.peek + 1
        return QPoint(x, self.y())

    def _clamp(self, p):
        r = self._screen_rect(p + QPoint(self.size_ // 2, self.size_ // 2))
        x = min(max(p.x(), r.left() - PAD), r.right() - self.size_ + PAD)
        y = min(max(p.y(), r.top() - PAD), r.bottom() - self.size_ + PAD)
        return QPoint(x, y)

    def start(self):
        x, y = self._initial
        r = QGuiApplication.primaryScreen().availableGeometry()
        if x is None or QGuiApplication.screenAt(QPoint(x + self.size_ // 2, y + self.size_ // 2)) is None:
            # first run (or that monitor is gone): middle of the right edge, tucked in
            self.dock, x, y = 'right', r.right() - PAD - self.peek + 1, r.center().y() - self.size_ // 2
        self.move(x, y)
        self.show()
        if not self._styled:  # belt and braces: Windows must never activate the bubble
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
            self._styled = True
        if self.dock:
            self.move(self._tucked_pos())

    def _slide(self, target):
        if self.pos() == target:
            return
        self.anim.stop()
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(target)
        self.anim.start()

    def tuck(self):
        """Right-click → Tuck into the edge."""
        r = self._screen_rect()
        self.dock = 'left' if self.geometry().center().x() < r.center().x() else 'right'
        self._slide(self._tucked_pos())
        self._emit_placed(self._tucked_pos())

    def _tuck_if_idle(self):
        if self.dock and not self.hovered and not self.dragging and self.state not in ('listen', 'work'):
            self._slide(self._tucked_pos())

    def _emit_placed(self, p=None):
        p = p or self.pos()
        self.placed.emit(p.x(), p.y(), self.dock)

    # ── state ────────────────────────────────────────────────────────────────
    def set_state(self, state, level=0.0):
        self.state, self.level = state, level
        if state in ('work', 'meeting'):  # spinner while writing, pulsing dot during a meeting
            self.spinner.start()
        else:
            self.spinner.stop()
        if self.dock and self.isVisible() and not self.dragging:
            # pop out while listening / writing so you can see it, tuck back afterwards
            if state in ('listen', 'work'):
                self.tuck_timer.stop()
                self._slide(self._out_pos())
            elif not self.hovered:
                self.tuck_timer.start()
        self.update()

    def _spin(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    # ── mouse ────────────────────────────────────────────────────────────────
    def enterEvent(self, _):
        self.hovered = True
        self.tuck_timer.stop()
        if self.dock and not self.dragging:
            self._slide(self._out_pos())

    def leaveEvent(self, _):
        self.hovered = False
        if self.dock:
            self.tuck_timer.start()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.press_pos = e.globalPosition().toPoint()
            self.press_win = self.pos()
            self.dragging = False

    def mouseMoveEvent(self, e):
        if self.press_pos is None:
            return
        delta = e.globalPosition().toPoint() - self.press_pos
        if not self.dragging and delta.manhattanLength() > DRAG_START:
            self.dragging = True
            self.anim.stop()
        if self.dragging:
            self.move(self._clamp(self.press_win + delta))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self.menu_requested.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton or self.press_pos is None:
            return
        self.press_pos = None
        if not self.dragging:
            self.clicked.emit()
            return
        self.dragging = False
        r = self._screen_rect()
        c = self.geometry().center()
        if c.x() - r.left() < SNAP:
            self.dock = 'left'
        elif r.right() - c.x() < SNAP:
            self.dock = 'right'
        else:
            self.dock = ''
        if self.dock:
            self.move(self._out_pos())
            self.tuck_timer.start()
            self._emit_placed(self._tucked_pos())
        else:
            self._emit_placed()

    # ── drawing ──────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = self.size_ / 2
        r = self.diameter / 2
        if self.state == 'listen':  # halo grows with the voice
            halo = QColor(STATE_COLORS['listen'])
            halo.setAlpha(80)
            rr = r + 2 + min(PAD - 2, self.level * 90)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 60))
        p.drawEllipse(QRectF(cx - r, cy - r + 2, 2 * r, 2 * r))
        self.skin.paint(p, QRectF(cx - r, cy - r, 2 * r, 2 * r), self.state, self.level, self.angle)
