@echo off
REM ==== Step 5: read each draft and approve it by typing yes. Then send it yourself. ====
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.cli approve
echo.
echo Making your outbox page (open it and send each approved email from Gmail)...
".venv\Scripts\python.exe" -m src.cli send --method manual
if exist "exports" start "" "exports"
pause
