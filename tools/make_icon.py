"""Render the mic icon to assets/kalam.ico (all Windows sizes) and assets/kalam.png."""
import io, sys
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QGuiApplication
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from kalam.icons import mic_pixmap

app = QGuiApplication(sys.argv)
def pil(size):
    buf = QBuffer(); buf.open(QIODevice.WriteOnly); mic_pixmap('ready', size).save(buf, 'PNG')
    return Image.open(io.BytesIO(bytes(buf.data())))
big = pil(256)
big.save(ROOT / 'assets' / 'kalam.png')
big.save(ROOT / 'assets' / 'kalam.ico', sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
print('ok')
