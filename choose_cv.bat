@echo off
REM ==== Choose the CV that is attached to every email (a PDF, about 2 pages). ====
REM Double-click this file to pick your CV in a window, or drag your CV PDF onto this file.
cd /d "%~dp0"
".venv\Scripts\python.exe" -m src.cli cv --choose "%~1"
pause
