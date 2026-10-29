@echo off
rem Gets the newest coach from GitHub and installs it, voice packages included.
rem Double-click it, or run it in Command Prompt, then start the coach again.
cd /d "%~dp0"
git pull
if errorlevel 1 (
  echo.
  echo Could not download the update. Is Git installed? See README.md, Setup.
  pause
  exit /b 1
)
py -m pip install -e ".[voice]"
echo.
echo Updated. Close any open coach window, then start it again:  py -m coach
pause
