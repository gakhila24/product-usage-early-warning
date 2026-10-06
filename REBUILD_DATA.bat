@echo off
setlocal EnableExtensions
title Signal - rebuild synthetic data
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" ( echo Run RUN_PROJECT.bat first to create the environment. & pause & exit /b 1 )
echo Stop the API window first ^(the database file must not be in use^).
echo.
set "SEED=%~1"
if "%SEED%"=="" set "SEED=42"
echo Rebuilding data with seed %SEED% ...
".venv\Scripts\python.exe" src\run_pipeline.py --seed %SEED%
if errorlevel 1 ( echo [ERROR] pipeline failed. & pause & exit /b 1 )
echo ok> "data\.pipeline_ok"
echo.
echo Done. Start the app again with RUN_PROJECT.bat.
pause
