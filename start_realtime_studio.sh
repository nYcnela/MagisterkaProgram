#!/bin/bash

cd "$(dirname "$0")"

# --- Sprawdź czy .venv istnieje ---
if [ ! -f ".venv/bin/python" ]; then
    echo "[BLAD] Brak .venv — uruchom najpierw setup_once.sh"
    exit 1
fi

# --- Aktywuj venv ---
source .venv/bin/activate

# --- Ustaw backend root ---
export REALTIME_STUDIO_BACKEND_ROOT="$(pwd)/backend_embedded"

echo "[INFO] Uruchamianie Realtime Studio ..."
python -m realtime_studio
