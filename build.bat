@echo off
setlocal EnableExtensions
cd /d "%~dp0"
echo.
echo [1/4] Creating isolated build environment...
if not exist ".buildenv\Scripts\python.exe" (
    py -3 -m venv ".buildenv"
    if errorlevel 1 goto :failed
)
echo [2/4] Installing pinned PyInstaller...
".buildenv\Scripts\python.exe" -m pip install --disable-pip-version-check "pyinstaller==6.22.3"
if errorlevel 1 goto :failed
echo [3/4] Running automated tests...
".buildenv\Scripts\python.exe" -m unittest discover -s tests -v
if errorlevel 1 goto :failed
echo [4/4] Building single-file GUI executable...
".buildenv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed --name "DatatelcomSystemManager" "launcher.py"
if errorlevel 1 goto :failed
echo.
echo SUCCESS: %~dp0dist\DatatelcomSystemManager.exe
echo NOTE: app.py systems still require their own Python interpreter and packages.
exit /b 0
:failed
echo.
echo ERROR: Build failed. See the messages above.
exit /b 1
