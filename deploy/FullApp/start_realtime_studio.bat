@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

REM --- Sprawdź czy .venv istnieje ---
if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw setup_once.bat
    pause
    exit /b 1
)

REM --- Aktywuj venv ---
call .venv\Scripts\activate.bat

REM --- Ustaw backend root na embedded ---
set REALTIME_STUDIO_BACKEND_ROOT=%~dp0backend_embedded

REM --- Uruchom aplikację ---
echo [INFO] Uruchamianie Realtime Studio ...
python -m realtime_studio

REM --- Jeśli aplikacja się zamknęła z błędem ---
if errorlevel 1 (
    echo.
    echo [INFO] Aplikacja zakonczyla sie z bledem.
    pause
)
