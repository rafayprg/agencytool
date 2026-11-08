@echo off
REM ============================================================
REM  Media Agency Studio - one-time setup (Windows)
REM  Needs: internet, Python 3.12 (or uv), Node.js 20+
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo [1/4] Checking Node.js ...
where node >nul 2>nul || (
  echo   Node.js is missing. Install the LTS version from https://nodejs.org and run setup.bat again.
  pause & exit /b 1
)

echo [2/4] Creating the Python environment (.venv) ...
where uv >nul 2>nul
if %errorlevel%==0 (
  uv venv -p 3.12 .venv || goto :fail
  uv pip install -p .venv\Scripts\python.exe -r requirements.txt || goto :fail
) else (
  where py >nul 2>nul || (
    echo   Python 3.12 is missing. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^)
    pause & exit /b 1
  )
  py -3.12 -m venv .venv || goto :fail
  .venv\Scripts\python.exe -m pip install --upgrade pip || goto :fail
  .venv\Scripts\python.exe -m pip install -r requirements.txt || goto :fail
)

echo [3/4] Installing the video editor (Remotion) ...
pushd studio
call npm install --no-audit --no-fund || (popd & goto :fail)
popd

echo [4/4] Downloading the speech models (one time, ~500 MB) ...
.venv\Scripts\python.exe -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); WhisperModel('small.en', device='cpu', compute_type='int8')" || goto :fail

echo.
echo Setup finished. Double-click start.bat to open the studio.
pause
exit /b 0

:fail
echo.
echo Setup failed - read the error above. Fix it and run setup.bat again (it is safe to repeat).
pause
exit /b 1
