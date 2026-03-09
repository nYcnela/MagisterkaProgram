#!/bin/bash

echo "========================================"
echo "  Realtime Studio - Pierwsza instalacja"
echo "========================================"
echo ""

cd "$(dirname "$0")"

# --- Sprawdź czy Python istnieje ---
if ! command -v python3 &> /dev/null
then
    echo "[BLAD] Nie znaleziono python3."
    echo "Zainstaluj Python 3.10+ z python.org lub przez brew."
    exit 1
fi

echo "[INFO] Znaleziony Python:"
python3 --version
echo ""

# --- Utwórz venv ---
if [ -f ".venv/bin/python" ]; then
    echo "[INFO] .venv juz istnieje, pomijam tworzenie."
else
    echo "[1/3] Tworzenie srodowiska .venv ..."
    python3 -m venv .venv
    if [ $? -ne 0 ]; then
        echo "[BLAD] Nie udalo sie utworzyc .venv"
        exit 1
    fi
    echo "[OK] .venv utworzone."
fi

echo ""

# --- Aktywuj venv ---
source .venv/bin/activate

# --- Upgrade pip ---
echo "[2/3] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel
echo "[OK] pip zaktualizowany."
echo ""

# --- Instaluj zależności ---
echo "[3/3] Instalacja zaleznosci z requirements.txt ..."
echo "     To moze zajac kilka minut (torch jest duzy)..."
echo ""

pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo ""
    echo "[BLAD] Instalacja zaleznosci nie powiodla sie."
    exit 1
fi

echo ""
echo "========================================"
echo "  GOTOWE!"
echo ""
echo "  Uzyj start_realtime_studio.sh"
echo "  zeby uruchomic aplikacje."
echo "========================================"
