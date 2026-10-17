@echo off
REM ==== Open the email editor any time: check, edit and save your drafts. Nothing is sent from it. ====
cd /d "%~dp0"
echo Opening the email editor in your browser.
echo Keep this window open while you edit. When you are done, press "I'm done editing" on the page.
".venv\Scripts\python.exe" -m src.cli edit
pause
