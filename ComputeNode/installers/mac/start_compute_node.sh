#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f ".venv/bin/python" ]; then
  echo "[BLAD] Brak .venv — uruchom najpierw installers/mac/setup_compute_node.sh"
  exit 1
fi

source .venv/bin/activate
export REALTIME_STUDIO_BACKEND_ROOT="$ROOT_DIR/backend_embedded"
export REALTIME_COMPUTE_CONFIG="$ROOT_DIR/config.json"
echo "[INFO] Uruchamianie ComputeNode ..."
python -m realtime_studio.node_manager
