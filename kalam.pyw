r"""Start Kalam without a console window:  .venv\Scripts\pythonw.exe kalam.pyw"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.stdout is None:  # pythonw: model-download progress bars need somewhere to write
    sys.stdout = sys.stderr = open(os.devnull, 'w', encoding='utf-8')

from kalam.app import main

main()
