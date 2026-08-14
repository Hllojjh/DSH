@echo off
rem DSH Desktop Launcher - one-click silent start (no window, tray only)
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    start "" pythonw.exe dsh_launcher.py --silent
    exit /b 0
)
where python.exe >nul 2>nul
if not errorlevel 1 (
    start "" python.exe dsh_launcher.py --silent
    exit /b 0
)
echo [ERROR] Python not found. Please install Python 3.10+ from https://www.python.org/downloads/
pause
exit /b 1
