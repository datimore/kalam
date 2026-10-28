"""Colours, fonts and the app-wide stylesheet. Follows the Windows light / dark setting."""
import ctypes
import os
import tempfile

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPalette, QPen, QPixmap

LIGHT = dict(bg='#F5F5F7', surface='#FFFFFF', surface2='#F0F0F3', border='#E3E3E8', text='#18181B', muted='#71717A',
             accent='#2F9E6A', accent_hover='#278A5C', accent_text='#FFFFFF', danger='#E5484D', field='#FFFFFF',
             selection='#D4EFE1')
DARK = dict(bg='#111113', surface='#1B1B1F', surface2='#26262B', border='#303036', text='#EDEDEF', muted='#9B9BA6',
            accent='#3DD68C', accent_hover='#5BE3A1', accent_text='#0B1F14', danger='#FF6369', field='#17171A',
            selection='#1E3B2D')

ICON_FONTS = ['Segoe Fluent Icons', 'Segoe MDL2 Assets']
# Segoe MDL2 / Fluent glyphs
I_SETTINGS, I_HISTORY, I_COPY, I_TEACH, I_ADD, I_DELETE, I_IMAGE, I_CHECK, I_PASTE, I_MIC = (
    '', '', '', '', '', '', '', '', '', '')


def is_dark():
    return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark


def tokens():
    return DARK if is_dark() else LIGHT


def icon_font(size=11):
    f = QFont()
    f.setFamilies(ICON_FONTS)
    f.setPointSizeF(size)
    return f


def _arrow(color):
    """Small chevron PNG for combo boxes (Qt style sheets need an image file)."""
    path = os.path.join(tempfile.gettempdir(), f'kalam-arrow-{color.lstrip("#")}.png')
    if not os.path.exists(path):
        pm = QPixmap(20, 20)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(color), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline([QPointF(5, 8), QPointF(10, 13), QPointF(15, 8)])
        p.end()
        pm.save(path)
    return path.replace(os.sep, '/')


def qss(t):
    return f"""
    QWidget {{ color: {t['text']}; font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 10pt; }}
    QMainWindow, QDialog, QWidget#page {{ background: {t['bg']}; }}
    QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 14px; }}
    QLabel {{ background: transparent; }}
    QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
    QLabel#h2 {{ font-size: 12pt; font-weight: 600; }}
    QLabel#section {{ font-size: 10.5pt; font-weight: 600; }}
    QLabel#muted {{ color: {t['muted']}; }}
    QLabel#small {{ color: {t['muted']}; font-size: 8.5pt; }}
    QLabel#status {{ font-size: 13pt; font-weight: 600; }}
    QLabel#keycap {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-bottom-width: 2px;
                     border-radius: 6px; padding: 1px 7px; font-size: 8.5pt; font-weight: 600; }}
    QLabel#chip {{ background: {t['surface2']}; border-radius: 10px; padding: 3px 10px; font-size: 8.5pt; }}
    QLabel#toast {{ background: {t['selection']}; border-radius: 8px; padding: 6px 10px; }}
    QPushButton {{ background: {t['surface2']}; border: 1px solid {t['border']}; border-radius: 9px; padding: 6px 14px; }}
    QPushButton:hover {{ border-color: {t['muted']}; }}
    QPushButton:pressed {{ background: {t['border']}; }}
    QPushButton:disabled {{ color: {t['muted']}; border-color: {t['border']}; }}
    QPushButton#accent {{ background: {t['accent']}; color: {t['accent_text']}; border: none; font-weight: 600; }}
    QPushButton#accent:hover {{ background: {t['accent_hover']}; }}
    QPushButton#accent:disabled {{ background: {t['surface2']}; color: {t['muted']}; }}
    QPushButton#ghost {{ background: transparent; border: none; padding: 6px 10px; color: {t['muted']}; }}
    QPushButton#ghost:hover {{ background: {t['surface2']}; color: {t['text']}; }}
    QPushButton#seg {{ border-radius: 8px; padding: 5px 12px; }}
    QPushButton#seg:checked {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']}; font-weight: 600; }}
    QPushButton#skin {{ background: transparent; border: 2px solid transparent; border-radius: 12px; padding: 4px; }}
    QPushButton#skin:hover {{ background: {t['surface2']}; }}
    QPushButton#skin:checked {{ border-color: {t['accent']}; background: {t['surface2']}; }}
    QComboBox, QLineEdit, QPlainTextEdit, QTableWidget, QListWidget#list {{ background: {t['field']}; border: 1px solid {t['border']};
        border-radius: 9px; padding: 5px 9px; selection-background-color: {t['selection']}; selection-color: {t['text']}; }}
    QComboBox:hover, QLineEdit:hover, QPlainTextEdit:hover {{ border-color: {t['muted']}; }}
    QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {t['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{ image: url({_arrow(t['muted'])}); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']}; padding: 4px;
        selection-background-color: {t['surface2']}; selection-color: {t['text']}; outline: none; }}
    QListWidget#nav {{ background: transparent; border: none; outline: none; font-size: 10pt; }}
    QListWidget#nav::item {{ padding: 9px 12px; border-radius: 8px; margin: 1px 0; color: {t['muted']}; }}
    QListWidget#nav::item:hover {{ background: {t['surface2']}; color: {t['text']}; }}
    QListWidget#nav::item:selected {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; }}
    QListWidget#list {{ padding: 4px; outline: none; }}
    QListWidget#list::item {{ padding: 8px; border-radius: 7px; border-bottom: 1px solid {t['border']}; }}
    QListWidget#list::item:selected {{ background: {t['selection']}; color: {t['text']}; }}
    QTableWidget {{ gridline-color: {t['border']}; padding: 2px; }}
    QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']}; border: none; padding: 6px; font-weight: 600; }}
    QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ width: 10px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border']}; border-radius: 4px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; padding: 5px; }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; }}
    QMenu::item:selected {{ background: {t['surface2']}; }}
    QMenu::item:disabled {{ color: {t['muted']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 8px; }}
    QMenu::indicator {{ width: 14px; height: 14px; }}
    """


def apply(app):
    t = tokens()
    app.setStyle('Fusion')
    pal = QPalette()
    for role, key in ((QPalette.Window, 'bg'), (QPalette.Base, 'field'), (QPalette.AlternateBase, 'surface2'),
                      (QPalette.Text, 'text'), (QPalette.WindowText, 'text'), (QPalette.ButtonText, 'text'),
                      (QPalette.Button, 'surface2'), (QPalette.Highlight, 'selection'), (QPalette.HighlightedText, 'text'),
                      (QPalette.ToolTipBase, 'surface'), (QPalette.ToolTipText, 'text'), (QPalette.PlaceholderText, 'muted')):
        pal.setColor(role, QColor(t[key]))
    app.setPalette(pal)
    app.setStyleSheet(qss(t))


def style_titlebar(widget):
    """Windows 11: dark title bar in dark mode, and a caption colour that matches the window."""
    t = tokens()
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if is_dark() else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)  # DWMWA_USE_IMMERSIVE_DARK_MODE
        c = QColor(t['bg'])
        colorref = ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colorref), 4)  # DWMWA_CAPTION_COLOR (Windows 11)
    except (OSError, AttributeError):
        pass
