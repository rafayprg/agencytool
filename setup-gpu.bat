@echo off
REM ============================================================
REM  Optional: let Whisper (Transcriber) use an NVIDIA graphics card (RTX 2060, GTX 1660, ...)
REM  5-10x faster transcription. Needs an up-to-date NVIDIA driver. ~1.5 GB download.
REM  Run after setup.bat. Safe to skip: without it everything runs on the CPU.
REM ============================================================
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause & exit /b 1
)
where nvidia-smi >nul 2>nul || (
  echo No NVIDIA driver found ^(nvidia-smi missing^). Install the latest driver from nvidia.com first.
  pause & exit /b 1
)
where uv >nul 2>nul
if %errorlevel%==0 (
  uv pip install -p .venv\Scripts\python.exe "nvidia-cublas-cu12" "nvidia-cudnn-cu12==9.*" || goto :fail
) else (
  .venv\Scripts\python.exe -m pip install "nvidia-cublas-cu12" "nvidia-cudnn-cu12==9.*" || goto :fail
)
echo.
echo Checking the graphics card ...
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, 'app/agents'); import whisper_worker as w; w._add_cuda_dlls(); print('GPU ready' if w._gpu_available() else 'GPU NOT found - the studio will keep using the CPU')"
echo In Settings, "Transcription device" can stay on Auto.
pause
exit /b 0
:fail
echo GPU setup failed - the studio still works on the CPU.
pause
exit /b 1
