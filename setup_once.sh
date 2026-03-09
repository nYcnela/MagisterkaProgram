#!/bin/bash

set -euo pipefail

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

# --- Utwórz venv ---
if [ -f ".venv/bin/python" ]; then
    echo "[INFO] .venv juz istnieje, pomijam tworzenie."
else
    echo "[1/6] Tworzenie srodowiska .venv ..."
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
echo "[2/6] Aktualizacja pip ..."
python -m pip install -U pip setuptools wheel
echo "[OK] pip zaktualizowany."
echo ""

install_torch_channel() {
    local channel="$1"
    local index_url="https://download.pytorch.org/whl/${channel}"
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${index_url}"
}

echo "[3/6] Instalacja PyTorch ..."
if [ "$TORCH_CHANNEL" = "default" ]; then
    echo "     Uzywam domyslnego kanalu pip (np. macOS / MPS)."
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio
else
    echo "     Kanal podstawowy: ${TORCH_CHANNEL}"
    if ! install_torch_channel "$TORCH_CHANNEL"; then
        if [ "$TORCH_CHANNEL" = "$TORCH_FALLBACK_CHANNEL" ]; then
            echo ""
            echo "[BLAD] Instalacja PyTorch z kanalu ${TORCH_CHANNEL} nie powiodla sie."
            exit 1
        fi
        echo "     Fallback do ${TORCH_FALLBACK_CHANNEL} ..."
        install_torch_channel "$TORCH_FALLBACK_CHANNEL"
    fi
fi
echo ""

echo "[4/6] Instalacja pakietow runtime z requirements.txt ..."
python -m pip install -r requirements.txt
echo ""

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[5/6] Instalacja bitsandbytes dla kwantyzacji 4-bit ..."
    python -m pip install "bitsandbytes>=0.48,<1"
else
    echo "[5/6] bitsandbytes pomijam na macOS."
fi
echo ""

echo "[6/6] Weryfikacja GPU / runtime ..."
python - <<'PY'
import sys
import torch

ok = torch.cuda.is_available() or (
    getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
)
print("torch", torch.__version__)
print("torch.cuda", torch.version.cuda)
print("cuda?", torch.cuda.is_available())
print("mps?", bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()))
print("count", torch.cuda.device_count())
print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else "no cuda gpu")
sys.exit(0 if ok else 1)
PY

echo ""
echo "========================================"
echo "  GOTOWE!"
echo ""
echo "  Uzyj start_realtime_studio.sh"
echo "  zeby uruchomic aplikacje."
echo "  REALTIME_STUDIO_TORCH_CHANNEL pozwala wymusic kanal,"
echo "  np. cu128, cu130 albo default."
echo "========================================"
