@echo off
cd /d "%~dp0"
echo Creating the Python environment...
py -3 -m venv .venv 2>nul || python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
where nvidia-smi >nul 2>&1 && (echo NVIDIA card found, installing GPU support... & .venv\Scripts\python -m pip install -r requirements-gpu.txt)
echo.
echo Done. Double-click "Start Kalam.bat". The first start downloads the model (about 3 GB).
pause
