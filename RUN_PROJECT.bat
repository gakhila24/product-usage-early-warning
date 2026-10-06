@echo off
setlocal EnableExtensions
title Signal - Churn Early Warning ^| setup and run
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

echo ============================================================
echo   Signal - Customer Health / Churn Early-Warning dashboard
echo   (all data is synthetic and generated locally)
echo ============================================================
echo.

rem ---------- 1. prerequisites ----------
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 3.10+ was not found on PATH.
  echo         Install it from https://www.python.org/downloads/  and tick "Add python.exe to PATH".
  goto :fail
)
where node >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js 18+ was not found on PATH.  Install the LTS release from https://nodejs.org/
  goto :fail
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH ^(it ships with Node.js^).
  goto :fail
)

rem ---------- 2. python virtual environment + packages ----------
if not exist ".venv\Scripts\python.exe" (
  echo [1/5] Creating Python virtual environment ...
  python -m venv .venv
  if errorlevel 1 ( echo [ERROR] Could not create the virtual environment. & goto :fail )
) else (
  echo [1/5] Virtual environment found.
)
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist ".venv\.deps_ok" (
  echo [2/5] Installing Python packages ^(first run only, a minute or two^) ...
  "%PY%" -m pip install --disable-pip-version-check -q --upgrade pip
  "%PY%" -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 ( echo [ERROR] pip install failed. & goto :fail )
  echo ok> ".venv\.deps_ok"
) else (
  echo [2/5] Python packages already installed.
)

rem ---------- 3. synthetic data + model + graph + narratives ----------
if not exist "data\.pipeline_ok" (
  echo [3/5] Building the synthetic dataset, training the models, graph and narrative index ...
  echo       ^(about 1-2 minutes, first run only^)
  "%PY%" src\run_pipeline.py
  if errorlevel 1 ( echo [ERROR] The data pipeline failed - see the messages above. & goto :fail )
  echo ok> "data\.pipeline_ok"
) else (
  echo [3/5] Data and model already built ^(run REBUILD_DATA.bat to regenerate^).
)

rem ---------- 4. frontend packages ----------
if not exist "frontend\node_modules\.bin\vite.cmd" (
  echo [4/5] Installing frontend packages with npm ^(first run only^) ...
  pushd frontend
  call npm install --no-audit --no-fund
  if errorlevel 1 ( popd & echo [ERROR] npm install failed. & goto :fail )
  popd
) else (
  echo [4/5] Frontend packages already installed.
)

rem ---------- 5. start API + UI ----------
echo [5/5] Starting the API ^(http://127.0.0.1:5050^) and the dashboard ^(http://localhost:5173^) ...
start "Signal API (close this window to stop)" /D "%~dp0src" cmd /k ""%PY%" api.py"
start "Signal UI (close this window to stop)" /D "%~dp0frontend" cmd /k "npm run dev"
echo.
echo Waiting for the servers to come up ...
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173"
echo.
echo   Dashboard : http://localhost:5173
echo   API       : http://127.0.0.1:5050   ^(/health to check^)
echo   To stop   : close the two console windows that just opened.
echo.
echo   Optional  : set ANTHROPIC_API_KEY before running to get generated chat answers.
echo.
pause
exit /b 0

:fail
echo.
echo Setup stopped.  Fix the problem above and run RUN_PROJECT.bat again.
pause
exit /b 1
