"""The mic icon, drawn in code so every state gets its own colour."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

STATE_COLORS = {
    'loading': '#8B8D98', 'ready': '#30A46C', 'listen': '#E5484D',
    'work': '#F5A524', 'paused': '#8B8D98', 'error': '#E5484D',
}


def draw_mic(p, cx, cy, s, color='white'):
    """Mic glyph centred on (cx, cy); s = overall height."""
    pen = QPen(QColor(color), s * 0.09, Qt.SolidLine, Qt.RoundCap)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    w, h = s * 0.34, s * 0.52
    p.drawRoundedRect(QRectF(cx - w / 2, cy - s * 0.5, w, h), w / 2, w / 2)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    aw = s * 0.62
    p.drawArc(QRectF(cx - aw / 2, cy - s * 0.32, aw, s * 0.62), 180 * 16, 180 * 16)
    p.drawLine(int(cx), int(cy + s * 0.3), int(cx), int(cy + s * 0.45))
    p.drawLine(int(cx - s * 0.16), int(cy + s * 0.47), int(cx + s * 0.16), int(cy + s * 0.47))


def mic_pixmap(state='ready', size=64):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(STATE_COLORS.get(state, STATE_COLORS['ready'])))
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    draw_mic(p, size / 2, size / 2, size * 0.56)
    p.end()
    return pm


def mic_icon(state='ready'):
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 256):
        icon.addPixmap(mic_pixmap(state, s))
    return icon
