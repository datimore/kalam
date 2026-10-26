"""A small pill near the bottom of the screen that never takes focus from Word / Notion."""
import ctypes
import tkinter as tk

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x8
WS_EX_TRANSPARENT = 0x20      # clicks go through
WS_EX_TOOLWINDOW = 0x80       # no taskbar button
WS_EX_LAYERED = 0x80000
WS_EX_NOACTIVATE = 0x8000000  # never steals the cursor

COLORS = {'listen': '#E5484D', 'work': '#F5A524', 'info': '#3E8EF7', 'error': '#E5484D', 'ok': '#30A46C'}
BG = '#1C1C1F'


class Overlay:
    W, H = 230, 40

    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.0)
        self.win.configure(bg='#010101')
        self.win.attributes('-transparentcolor', '#010101')
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry(f'{self.W}x{self.H}+{(sw - self.W) // 2}+{sh - self.H - 90}')
        self.c = tk.Canvas(self.win, width=self.W, height=self.H, bg='#010101', highlightthickness=0)
        self.c.pack()
        self._pill()
        self.dot = self.c.create_oval(16, 14, 28, 26, fill=COLORS['listen'], outline='')
        self.label = self.c.create_text(40, 20, anchor='w', fill='#EDEDEF', font=('Segoe UI', 10, 'bold'), text='')
        self.meter = self.c.create_rectangle(150, 18, 150, 22, fill='#EDEDEF', outline='')
        self.hide_job = None
        self.win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
                                            | WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT)

    def _pill(self):
        r, w, h = self.H // 2, self.W, self.H
        self.c.create_oval(0, 0, h, h, fill=BG, outline='')
        self.c.create_oval(w - h, 0, w, h, fill=BG, outline='')
        self.c.create_rectangle(r, 0, w - r, h, fill=BG, outline='')

    def show(self, text, kind='info', hide_after=None, level=None):
        if self.hide_job:
            self.win.after_cancel(self.hide_job)
            self.hide_job = None
        self.c.itemconfigure(self.dot, fill=COLORS.get(kind, COLORS['info']))
        self.c.itemconfigure(self.label, text=text)
        self.set_level(level)
        self.win.attributes('-alpha', 0.94)
        if hide_after:
            self.hide_job = self.win.after(int(hide_after * 1000), self.hide)

    def set_level(self, level):
        if level is None:
            self.c.coords(self.meter, 150, 18, 150, 22)
        else:
            self.c.coords(self.meter, 150, 18, 150 + min(60, int(level * 600)), 22)

    def hide(self):
        self.hide_job = None
        self.win.attributes('-alpha', 0.0)
