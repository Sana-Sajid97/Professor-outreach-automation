@echo off
REM Run any command, for example:  outreach status   or   outreach mark-sent --ids R0012
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.cli %*
