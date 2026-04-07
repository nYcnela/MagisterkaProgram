@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Tworzenie .venv ...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/3] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel

echo [3/3] Instalacja zaleznosci RemoteGUI ...
python -m pip install -r requirements.remote_gui.txt
if errorlevel 1 (
    echo [BLAD] Nie udalo sie zainstalowac requirements.remote_gui.txt
    pause
    exit /b 1
)

echo GOTOWE
pause
