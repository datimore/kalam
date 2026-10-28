"""Small building blocks for the modern look: switch, keycap, card, segmented buttons, icon glyphs."""
from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                               QWidget)

from . import theme


class Toggle(QAbstractButton):
    """iOS-style switch."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(QSize(40, 22))

    def paintEvent(self, _):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t['accent'] if self.isChecked() else t['border']))
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11)
        p.setBrush(QColor('#FFFFFF'))
        x = 20 if self.isChecked() else 2
        p.drawEllipse(QRectF(x, 2, 18, 18))


def card():
    f = QFrame()
    f.setObjectName('card')
    return f


def label(text='', name=None, wrap=False):
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    return lab


def keycap(text):
    return label(text, 'keycap')


def glyph_icon(glyph, color=None, size=16):
    color = color or theme.tokens()['muted']
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setFont(theme.icon_font(size * 0.68))
    p.setPen(QColor(color))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, glyph)
    p.end()
    return QIcon(pm)


def button(text, glyph=None, kind=None, tooltip=None):
    b = QPushButton(text)
    if kind:
        b.setObjectName(kind)
    if glyph:
        color = theme.tokens()['accent_text'] if kind == 'accent' else None
        icon = glyph_icon(glyph, color)
        icon.addPixmap(glyph_icon(glyph, theme.tokens()['muted']).pixmap(16, 16), QIcon.Disabled)
        b.setIcon(icon)
    if tooltip:
        b.setToolTip(tooltip)
    b.setCursor(Qt.PointingHandCursor)
    return b


class Segmented(QWidget):
    """A row of mutually exclusive buttons, e.g. Quick / Normal / Relaxed."""
    changed = Signal(object)

    def __init__(self, options, value):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.group = QButtonGroup(self)
        self.values = {}
        for text, val in options:
            b = QPushButton(text)
            b.setObjectName('seg')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(val == value)
            self.group.addButton(b)
            self.values[b] = val
            lay.addWidget(b)
        lay.addStretch(1)
        self.group.buttonClicked.connect(lambda b: self.changed.emit(self.values[b]))

    def value(self):
        b = self.group.checkedButton()
        return self.values[b] if b else None


def row(label_text, widget, hint=None):
    """Settings row: title (+ grey hint) on the left, control on the right."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 4, 0, 4)
    left = QVBoxLayout()
    left.setSpacing(1)
    left.addWidget(label(label_text))
    if hint:
        left.addWidget(label(hint, 'small', wrap=True))
    lay.addLayout(left, 1)
    lay.addWidget(widget, 0, Qt.AlignVCenter)
    return w
