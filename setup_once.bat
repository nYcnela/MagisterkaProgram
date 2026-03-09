@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ========================================
echo   Realtime Studio - Pierwsza instalacja
echo ========================================
echo.

REM --- Szukaj Pythona ---
where python >nul 2>&1
if errorlevel 1 (
    echo [BLAD] Nie znaleziono "python" w PATH.
    echo Zainstaluj Python 3.10+ ze strony https://python.org
    echo Pamietaj o zaznaczeniu "Add Python to PATH" przy instalacji.
    echo.
    pause
    exit /b 1
)

echo [INFO] Znaleziony Python:
python --version
echo.

REM --- Utwórz .venv ---
if exist ".venv\Scripts\python.exe" (
    echo [INFO] .venv juz istnieje, pomijam tworzenie.
) else (
    echo [1/3] Tworzenie srodowiska .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [BLAD] Nie udalo sie utworzyc .venv
        pause
        exit /b 1
    )
    echo [OK] .venv utworzone.
)
echo.

REM --- Aktywuj venv ---
call .venv\Scripts\activate.bat

REM --- Upgrade pip ---
echo [2/3] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel >nul 2>&1
echo [OK] pip zaktualizowany.
echo.

REM --- Instaluj zależności ---
echo [3/3] Instalacja zaleznosci z requirements.txt ...
echo      To moze zajac kilka minut (torch jest duzy) ...
echo.
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [BLAD] Instalacja zaleznosci nie powiodla sie.
    echo Sprawdz logi powyzej.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   GOTOWE!
echo.
echo   Uzyj start_realtime_studio.bat
echo   zeby uruchomic aplikacje.
echo ========================================
echo.
pause
