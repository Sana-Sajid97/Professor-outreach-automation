@echo off
REM ==== Step 4: one-click run: validate, remove duplicates, score, write drafts, export, then open the editor ====
REM It NEVER sends email.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.run_pipeline --intake "both" --limit 30 --mode drafts
if errorlevel 1 (
  echo.
  echo The run stopped with a problem - read the message above. The review page was not opened.
  pause
  exit /b 1
)
echo.
echo Opening the email editor in your browser: check every email, edit it if needed, and press Save.
echo Keep this window open while you edit. Close it when you are done, then run 5_approve_drafts.bat.
".venv\Scripts\python.exe" -m src.cli edit
pause
