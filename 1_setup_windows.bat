@echo off
REM ==== Step 1: one-time setup. Double-click this file. ====
cd /d "%~dp0"
echo.
echo Setting up the Professor Outreach Assistant...
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo Python was not found. Install it from https://www.python.org/downloads/
  echo During installation TICK the box "Add python.exe to PATH", then run this file again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment in the .venv folder...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Could not create the environment. See docs\WINDOWS_SETUP.md, section Troubleshooting.
    pause
    exit /b 1
  )
)
echo Installing the required packages (this can take a minute)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check your internet connection and try again.
  pause
  exit /b 1
)
if not exist "private_profile" mkdir private_profile
if not exist ".env" copy ".env.example" ".env" >nul
echo.
".venv\Scripts\python.exe" -m src.cli doctor
echo.
echo Setup finished. Next: put your CV/portfolio PDF in the "private_profile" folder,
echo then double-click 2_import_profile.bat
pause
