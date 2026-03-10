#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "  RemoteGUI - Pierwsza instalacja"
echo "========================================"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[BLAD] Nie znaleziono python3."
    exit 1
fi

if [ -f ".venv/bin/python" ]; then
    echo "[INFO] .venv juz istnieje, pomijam tworzenie."
else
    echo "[1/3] Tworzenie srodowiska .venv ..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "[2/3] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel

echo "[3/3] Instalacja zaleznosci RemoteGUI ..."
python -m pip install -r requirements.remote_gui.txt

echo ""
echo "GOTOWE"
