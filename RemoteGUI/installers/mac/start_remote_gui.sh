#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".venv/bin/python" ]; then
  echo "[BLAD] Brak .venv — uruchom najpierw installers/mac/setup_remote_gui.sh"
  exit 1
fi

source .venv/bin/activate
export REALTIME_REMOTE_GUI_CONFIG="$ROOT_DIR/config.json"
echo "[INFO] Uruchamianie RemoteGUI ..."
python -m realtime_studio.remote_main
