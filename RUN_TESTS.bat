@echo off
setlocal EnableExtensions
title Signal - tests
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" ( echo Run RUN_PROJECT.bat first to create the environment. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements-dev.txt
echo Running the backend test-suite ^(builds the data first if it does not exist^) ...
".venv\Scripts\python.exe" -m pytest -q
echo.
pause
