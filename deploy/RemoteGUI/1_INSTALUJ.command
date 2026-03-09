#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/3] Tworzenie .venv ..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "[2/3] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel

echo "[3/3] Instalacja zaleznosci RemoteGUI ..."
python -m pip install -r requirements.remote_gui.txt

echo "GOTOWE"
read -k 1 "?Nacisnij dowolny klawisz, aby zamknac..."
