@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

set "TORCH_CHANNEL=%REALTIME_STUDIO_TORCH_CHANNEL%"
if not defined TORCH_CHANNEL set "TORCH_CHANNEL=cu130"
set "TORCH_FALLBACK_CHANNEL=cu128"
set "TORCH_INDEX_URL=https://download.pytorch.org/whl/%TORCH_CHANNEL%"
set "TORCH_FALLBACK_INDEX_URL=https://download.pytorch.org/whl/%TORCH_FALLBACK_CHANNEL%"

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Tworzenie .venv ...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/5] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel

echo [3/5] Instalacja GPU PyTorch ...
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_INDEX_URL%
if errorlevel 1 (
    echo [WARN] Fallback do %TORCH_FALLBACK_CHANNEL% ...
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_FALLBACK_INDEX_URL%
    if errorlevel 1 (
        echo [BLAD] Nie udalo sie zainstalowac GPU PyTorch.
        pause
        exit /b 1
    )
)

echo [4/5] Instalacja zaleznosci ComputeNode ...
python -m pip install -r requirements.compute_node.txt
if errorlevel 1 (
    echo [BLAD] Nie udalo sie zainstalowac requirements.compute_node.txt
    pause
    exit /b 1
)

echo [5/5] Instalacja bitsandbytes ...
python -m pip install "bitsandbytes>=0.48,<1"
if errorlevel 1 (
    echo [BLAD] bitsandbytes nie zainstalowal sie poprawnie.
    pause
    exit /b 1
)

echo GOTOWE
pause
