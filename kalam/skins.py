"""Looks for the floating mic: the classic mic, an emoji character, or any image / animated GIF.

Whatever the look, a ring around it shows the state (green ready, red listening, amber writing, grey paused).
"""
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImageReader, QMovie, QPainter, QPainterPath, QPen, QPixmap

from . import config
from .icons import STATE_COLORS, draw_mic

EMOJI = ['🤖', '🐱', '🦊', '🐸', '🐼', '🦁', '🐪', '👽', '👻', '😎', '🔥', '⭐', '🎧', '🦜']
BUILTIN = ['mic'] + [f'emoji:{e}' for e in EMOJI]
SKINS_DIR = 'skins'  # inside the user's data folder


def import_image(path):
    """Copy the user's picture into Kalam's data folder; returns the skin id to store in settings."""
    src = Path(path)
    dst_dir = config.DATA_DIR / SKINS_DIR
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if src.resolve() != dst.resolve():
        shutil.copy(src, dst)
    return f'image:{SKINS_DIR}/{src.name}'


class Skin(QObject):
    """Draws one look; emits `changed` when an animated GIF moves to its next frame."""
    changed = Signal()

    def __init__(self, skin_id='mic', parent=None):
        super().__init__(parent)
        self.movie = None
        self.pixmap = None
        self.set(skin_id)

    def set(self, skin_id):
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
        self.movie, self.pixmap = None, None
        self.id = skin_id or 'mic'
        if self.id.startswith('image:'):
            path = str(config.DATA_DIR / self.id[6:])
            if QImageReader(path).supportsAnimation() and QImageReader(path).imageCount() != 1:
                self.movie = QMovie(path, parent=self)
                self.movie.frameChanged.connect(lambda _: self.changed.emit())
                self.movie.jumpToFrame(0)
                self.movie.start()
            else:
                pm = QPixmap(path)
                self.pixmap = pm if not pm.isNull() else None
            if not self.movie and not self.pixmap:
                self.id = 'mic'  # the file is gone or unreadable
        self.changed.emit()

    def paint(self, p, rect, state='ready', level=0.0, angle=0):
        """Draw into `rect` (the circle's bounding square)."""
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        c = QColor(STATE_COLORS.get(state, STATE_COLORS['ready']))
        r = rect.width() / 2
        cx, cy = rect.center().x(), rect.center().y()
        if self.id == 'mic':
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(rect)
            if state == 'work':
                self._spinner(p, rect.adjusted(r * 0.2, r * 0.2, -r * 0.2, -r * 0.2), angle, QColor('white'), r * 0.09)
            draw_mic(p, cx, cy, rect.width() * 0.46)
            p.restore()
            return
        # picture looks: the picture fills the circle, a ring shows the state
        ring = max(2.5, r * (0.13 if state in ('listen', 'work') else 0.08))
        inner = rect.adjusted(ring, ring, -ring, -ring)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor('#FFFFFF'))
        p.drawEllipse(inner)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.setClipPath(clip)
        if self.id.startswith('emoji:'):
            f = QFont('Segoe UI Emoji')
            f.setPixelSize(max(8, int(inner.width() * 0.62)))
            p.setFont(f)
            p.setPen(QColor('black'))
            p.drawText(inner.adjusted(0, inner.height() * 0.03, 0, 0), Qt.AlignCenter, self.id[6:])
        else:
            pm = self.movie.currentPixmap() if self.movie else self.pixmap
            if pm is not None and not pm.isNull():
                scaled = pm.scaled(int(inner.width()) * 2, int(inner.height()) * 2,
                                   Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                src = QRectF((scaled.width() - inner.width() * 2) / 2, (scaled.height() - inner.height() * 2) / 2,
                             inner.width() * 2, inner.height() * 2)
                p.drawPixmap(inner, scaled, src)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(c, ring))
        p.drawEllipse(rect.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2))
        if state == 'work':
            self._spinner(p, rect.adjusted(ring / 2, ring / 2, -ring / 2, -ring / 2), angle, QColor('white'), ring * 0.55)
        p.restore()

    @staticmethod
    def _spinner(p, rect, angle, color, width):
        p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, int(-angle * 16), 100 * 16)


def preview_pixmap(skin_id, size=48, state='ready'):
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    Skin(skin_id).paint(p, QRectF(1, 1, size - 2, size - 2), state)
    p.end()
    return pm
