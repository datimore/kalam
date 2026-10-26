@echo off
rem Builds dist\Kalam\Kalam.exe and installer\output\Kalam-Setup-x.y.z.exe
cd /d "%~dp0"
.venv\Scripts\python -m pip install -r requirements-build.txt || exit /b 1
.venv\Scripts\python tools\make_icon.py || exit /b 1
.venv\Scripts\pyinstaller kalam.spec --noconfirm || exit /b 1
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\kalam.iss || exit /b 1
echo Done: installer\output
