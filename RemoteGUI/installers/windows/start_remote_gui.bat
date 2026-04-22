@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw installers\windows\setup_remote_gui.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_REMOTE_GUI_CONFIG=%ROOT_DIR%\config.json
python -m realtime_studio.remote_main
