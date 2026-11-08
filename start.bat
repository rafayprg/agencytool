@echo off
REM Starts Media Agency Studio on http://127.0.0.1:8790 and opens the browser.
REM   start.bat --background   (used by auto-start: no browser window)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run setup.bat
  pause & exit /b 1
)
if "%STUDIO_PORT%"=="" set STUDIO_PORT=8790
set STUDIO_OPEN_BROWSER=1
if /i "%~1"=="--background" set STUDIO_OPEN_BROWSER=0
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
echo Media Agency Studio is running at http://127.0.0.1:%STUDIO_PORT%  (close this window to stop it)
.venv\Scripts\python.exe app\server.py
if /i not "%~1"=="--background" pause
