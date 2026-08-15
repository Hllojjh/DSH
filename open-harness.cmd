@echo off
setlocal
title DeepSeek Harness

set "DSH_PORT=3080"
for /f "tokens=2 delims=:" %%P in ('findstr /R /C:"^[ ]*port:" "%USERPROFILE%\.dsh\profiles\web\cordis.patch.yml" 2^>nul') do set "DSH_PORT=%%P"
set "DSH_PORT=%DSH_PORT: =%"

netstat -ano | findstr /R /C:":%DSH_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 goto running

echo DeepSeek Harness is not running. Starting the launcher...
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
  start "" pythonw.exe "D:\DS-harness\DSH-desktop\dsh_launcher.py"
  exit /b 0
)
where python.exe >nul 2>nul
if not errorlevel 1 (
  start "" python.exe "D:\DS-harness\DSH-desktop\dsh_launcher.py"
  exit /b 0
)
start "" "D:\DS-harness\DSH-desktop\dist\DSH-Launcher.exe"
exit /b 0

:running
start "" "http://127.0.0.1:%DSH_PORT%"
exit /b 0
