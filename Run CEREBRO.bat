@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" main.py
) else if exist ".venv\Scripts\py.exe" (
  ".venv\Scripts\py.exe" -3 main.py
) else (
  py -3 main.py
)

if errorlevel 1 (
  echo.
  echo CEREBRO failed to start. Check the error output above.
)
pause
