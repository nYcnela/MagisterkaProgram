#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/5] Tworzenie .venv ..."
  python3 -m venv .venv
fi

source .venv/bin/activate

TORCH_CHANNEL="${REALTIME_STUDIO_TORCH_CHANNEL:-cu130}"
TORCH_FALLBACK_CHANNEL="cu128"
TORCH_INDEX_URL="https://download.pytorch.org/whl/${TORCH_CHANNEL}"
TORCH_FALLBACK_INDEX_URL="https://download.pytorch.org/whl/${TORCH_FALLBACK_CHANNEL}"

echo "[2/5] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel

echo "[3/5] Instalacja GPU PyTorch ..."
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${TORCH_INDEX_URL}" || \
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${TORCH_FALLBACK_INDEX_URL}"

echo "[4/5] Instalacja zaleznosci ComputeNode ..."
python -m pip install -r requirements.compute_node.txt

echo "[5/5] Instalacja bitsandbytes ..."
python -m pip install "bitsandbytes>=0.48,<1"

echo "GOTOWE"
read -k 1 "?Nacisnij dowolny klawisz, aby zamknac..."
