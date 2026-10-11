@echo off
REM ==== Step 2: read your CV/portfolio PDF from the private_profile folder ====
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.cli import-profile %*
echo.
echo Open private_profile\profile.json in Notepad to check the details.
echo If the tracker is not started yet, starting it now from the researched leads...
if not exist "workspace\tracker.csv" ".venv\Scripts\python.exe" -m src.cli init
pause
