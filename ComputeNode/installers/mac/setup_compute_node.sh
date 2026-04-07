#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

echo "========================================"
echo "  ComputeNode - Pierwsza instalacja"
echo "========================================"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
    echo "[BLAD] Nie znaleziono python3."
    exit 1
fi

TORCH_CHANNEL="${REALTIME_STUDIO_TORCH_CHANNEL:-}"
if [ -z "$TORCH_CHANNEL" ]; then
    case "$(uname -s)" in
        Darwin)
            TORCH_CHANNEL="default"
            ;;
        *)
            TORCH_CHANNEL="cu130"
            ;;
    esac
fi
TORCH_FALLBACK_CHANNEL="cu128"

if [ -f ".venv/bin/python" ]; then
    echo "[INFO] .venv juz istnieje, pomijam tworzenie."
else
    echo "[1/5] Tworzenie srodowiska .venv ..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "[2/5] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel

install_torch_channel() {
    local channel="$1"
    local index_url="https://download.pytorch.org/whl/${channel}"
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${index_url}"
}

echo "[3/5] Instalacja PyTorch ..."
if [ "$TORCH_CHANNEL" = "default" ]; then
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio
else
    if ! install_torch_channel "$TORCH_CHANNEL"; then
        if [ "$TORCH_CHANNEL" = "$TORCH_FALLBACK_CHANNEL" ]; then
            echo "[BLAD] Instalacja PyTorch z kanalu ${TORCH_CHANNEL} nie powiodla sie."
            exit 1
        fi
        echo "[WARN] Fallback do ${TORCH_FALLBACK_CHANNEL} ..."
        install_torch_channel "$TORCH_FALLBACK_CHANNEL"
    fi
fi

echo "[4/5] Instalacja zaleznosci ComputeNode ..."
python -m pip install -r requirements.compute_node.txt

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[5/5] Instalacja bitsandbytes ..."
    python -m pip install "bitsandbytes>=0.48,<1"
else
    echo "[5/5] bitsandbytes pomijam na macOS."
fi

echo ""
echo "GOTOWE"
