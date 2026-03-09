@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw 1_INSTALUJ.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_REMOTE_GUI_CONFIG=%~dp0config.json
python -m realtime_studio.remote_main
