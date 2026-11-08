@echo off
REM Start Media Agency Studio automatically (minimised, no browser) every time you log in to Windows.
REM Autopilot continues where it stopped. Undo with remove-autostart.bat.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup') + '\Media Agency Studio.lnk');" ^
  "$s.TargetPath='%~dp0start.bat'; $s.Arguments='--background'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
if %errorlevel%==0 (echo Auto-start installed. The studio will start by itself after you log in.) else (echo Could not create the shortcut.)
echo Tip: in Windows power settings set "Sleep" to Never, so the PC keeps working at night.
pause
