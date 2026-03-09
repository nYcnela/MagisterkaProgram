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

set "TORCH_CHANNEL=%REALTIME_STUDIO_TORCH_CHANNEL%"
if not defined TORCH_CHANNEL set "TORCH_CHANNEL=cu130"
set "TORCH_FALLBACK_CHANNEL=cu128"
set "TORCH_INDEX_URL=https://download.pytorch.org/whl/%TORCH_CHANNEL%"
set "TORCH_FALLBACK_INDEX_URL=https://download.pytorch.org/whl/%TORCH_FALLBACK_CHANNEL%"

REM --- Utwórz .venv ---
if exist ".venv\Scripts\python.exe" (
    echo [INFO] .venv juz istnieje, pomijam tworzenie.
) else (
    echo [1/6] Tworzenie srodowiska .venv ...
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
echo [2/6] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel >nul 2>&1
echo [OK] pip zaktualizowany.
echo.

REM --- Instaluj GPU PyTorch ---
echo [3/6] Instalacja GPU PyTorch z kanalu %TORCH_CHANNEL% ...
echo      Jesli ten kanal nie zadziala, setup sprobuje fallback do %TORCH_FALLBACK_CHANNEL%.
echo.

python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_INDEX_URL%
if errorlevel 1 (
    echo [WARN] Instalacja PyTorch z kanalu %TORCH_CHANNEL% nie powiodla sie.
    if /I "%TORCH_CHANNEL%"=="%TORCH_FALLBACK_CHANNEL%" (
        echo [BLAD] PyTorch GPU nie zainstalowal sie poprawnie.
        pause
        exit /b 1
    )

    echo [3/6] Fallback do %TORCH_FALLBACK_CHANNEL% ...
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_FALLBACK_INDEX_URL%
    if errorlevel 1 (
        echo [BLAD] Nie udalo sie zainstalowac GPU PyTorch ani z %TORCH_CHANNEL%, ani z %TORCH_FALLBACK_CHANNEL%.
        echo Ustaw recznie REALTIME_STUDIO_TORCH_CHANNEL przed uruchomieniem setupu, np. cu128 albo cu130.
        pause
        exit /b 1
    )
)

echo [4/6] Instalacja pakietow runtime z requirements.txt ...
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [BLAD] Instalacja pakietow runtime nie powiodla sie.
    echo Sprawdz logi powyzej.
    pause
    exit /b 1
)

echo.
echo [5/6] Instalacja bitsandbytes dla kwantyzacji 4-bit ...
echo.
python -m pip install "bitsandbytes>=0.48,<1"
if errorlevel 1 (
    echo.
    echo [BLAD] Nie udalo sie zainstalowac bitsandbytes.
    echo Ten projekt domyslnie uzywa kwantyzacji 4-bit, wiec setup zostaje przerwany.
    pause
    exit /b 1
)

echo.
echo [6/6] Weryfikacja GPU / CUDA ...
echo.
python -c "import sys, torch; ok = torch.cuda.is_available(); print('torch', torch.__version__); print('torch.cuda', torch.version.cuda); print('cuda?', ok); print('count', torch.cuda.device_count()); print(torch.cuda.get_device_name(0) if ok else 'no gpu'); sys.exit(0 if ok else 1)"
if errorlevel 1 (
    echo.
    echo [BLAD] Test CUDA nie udal sie.
    pause
    exit /b 1
)

echo.
echo ========================================
echo   GOTOWE!
echo.
echo   Uzyj start_realtime_studio.bat
echo   zeby uruchomic aplikacje.
echo   Jesli chcesz wymusic inny kanal PyTorch,
echo   ustaw REALTIME_STUDIO_TORCH_CHANNEL=cu128 lub cu130 przed setupem.
echo ========================================
echo.
pause
