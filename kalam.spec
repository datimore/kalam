# PyInstaller recipe for Kalam.exe:  .venv\Scripts\pyinstaller kalam.spec --noconfirm
import glob, os, sys
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

site = os.path.join(sys.prefix, 'Lib', 'site-packages')
# Whisper on the GPU only loads cuBLAS from the NVIDIA wheels (cuDNN comes with ctranslate2),
# so the other ~1.3 GB of NVIDIA DLLs stay out of the installer
cublas = [(f, 'nvidia/cublas/bin') for f in glob.glob(os.path.join(site, 'nvidia', 'cublas', 'bin', 'cublas*64_12.dll'))]

a = Analysis(
    ['kalam.pyw'],
    pathex=['.'],
    binaries=cublas + collect_dynamic_libs('ctranslate2'),
    datas=[('defaults', 'defaults'), ('assets', 'assets')] + collect_data_files('faster_whisper'),
    hiddenimports=['PySide6.QtNetwork'],
    excludes=['tkinter', 'pystray', 'matplotlib', 'IPython', 'pytest', 'torch'],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Kalam', icon='assets/kalam.ico',
          console=False, upx=False, version='version_info.txt')
coll = COLLECT(exe, a.binaries, a.datas, name='Kalam', upx=False)
