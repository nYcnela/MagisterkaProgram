#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[BLAD] Brak .venv — uruchom najpierw 1_INSTALUJ.command"
  read -k 1 "?Nacisnij dowolny klawisz, aby zamknac..."
  exit 1
fi

source .venv/bin/activate
export REALTIME_REMOTE_GUI_CONFIG="$PWD/config.json"
python -m realtime_studio.remote_main
