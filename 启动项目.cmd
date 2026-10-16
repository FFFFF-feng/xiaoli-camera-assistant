@echo off
setlocal
chcp 65001 >nul
if not exist "%~dp0scripts\launch_apps.py" (
    echo [ERROR] This CMD is not in the complete project folder.
    echo Create a desktop shortcut to the original CMD instead of copying it alone.
    echo See README.md for scripts\create_desktop_shortcut.ps1.
    pause
    exit /b 1
)
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "APP_LAUNCH_PYTHON="
set "APP_LAUNCH_ARGS="

if exist "%~dp0.venv\Scripts\python.exe" (
    set "APP_LAUNCH_PYTHON=%~dp0.venv\Scripts\python.exe"
    goto launch
)
if exist "%~dp0venv\Scripts\python.exe" (
    set "APP_LAUNCH_PYTHON=%~dp0venv\Scripts\python.exe"
    goto launch
)
where python >nul 2>nul
if not errorlevel 1 (
    set "APP_LAUNCH_PYTHON=python"
    goto launch
)
where py >nul 2>nul
if not errorlevel 1 (
    set "APP_LAUNCH_PYTHON=py"
    set "APP_LAUNCH_ARGS=-3"
    goto launch
)
echo [ERROR] Python was not found. Install Python 3.11 or newer first.
pause
exit /b 1

:launch
echo Starting the current local web app. No server deployment.
"%APP_LAUNCH_PYTHON%" %APP_LAUNCH_ARGS% -u "%~dp0scripts\launch_apps.py" --web %*
if errorlevel 1 (
    echo.
    echo [ERROR] Startup failed. Please read the message above.
    pause
    exit /b 1
)
endlocal
exit /b 0
