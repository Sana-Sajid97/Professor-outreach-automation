@echo off
REM ==== Step 4: one-click run: validate, remove duplicates, score, write drafts, export ====
REM It NEVER sends email.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.run_pipeline --intake "both" --limit 30 --mode drafts
if errorlevel 1 (
  echo.
  echo The run stopped with a problem - read the message above. The review page was not opened.
  pause
  exit /b 1
)
if exist "exports\review_latest.html" start "" "exports\review_latest.html"
pause
