@echo off
REM ==== Open the email editor any time: check, edit and save your drafts. Nothing is sent from it. ====
cd /d "%~dp0"
echo Opening the email editor in your browser.
echo Keep this window open while you edit. Close it when you are done.
".venv\Scripts\python.exe" -m src.cli edit
pause
