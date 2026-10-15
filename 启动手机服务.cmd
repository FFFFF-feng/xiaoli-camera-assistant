@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found.
  pause
  exit /b 1
)
python "%~dp0scripts\start_mobile_api.py" --host 0.0.0.0 %*
if errorlevel 1 pause
