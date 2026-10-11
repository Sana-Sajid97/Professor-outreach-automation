@echo off
REM ==== Step 3: check professors on their OFFICIAL university pages (needs internet) ====
cd /d "%~dp0"
echo This visits each official faculty page slowly and politely (a few seconds apart).
echo It can take 5-15 minutes for 40 professors. You can stop it any time with Ctrl+C.
".venv\Scripts\python.exe" -m src.cli verify --limit 40
pause
