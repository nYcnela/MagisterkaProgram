from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from realtime_studio.compute_settings import ComputeNodeConfig
from realtime_studio.remote_settings import RemoteGuiConfig


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_ROOT = PROJECT_ROOT / "deploy"
FULL_APP_DIR = "FullApp"
COMPUTE_NODE_DIR = "ComputeNode"
REMOTE_GUI_DIR = "RemoteGUI"
LEGACY_DIRS = ("ComputeNode_K1", "RemoteGUI_K2")
WINDOWS_DIR = "installers/windows"
MAC_DIR = "installers/mac"


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _copy_tree(src: Path, dst: Path) -> None:
    ignore = shutil.ignore_patterns(".git", ".venv", "__pycache__", "*.pyc", "deploy", "data/tmp")
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True)


def _copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | 0o111)


def _write_executable_text(path: Path, content: str) -> None:
    _write_text(path, content)
    _mark_executable(path)


def _full_app_dist() -> None:
    out = DIST_ROOT / FULL_APP_DIR
    _remove(out)
    out.mkdir(parents=True, exist_ok=True)

    for name in [
        "README.md",
        "requirements.txt",
        "setup_once.bat",
        "setup_once.sh",
        "start_realtime_studio.bat",
        "start_realtime_studio.sh",
    ]:
        _copy_file(PROJECT_ROOT / name, out / name)

    _copy_tree(PROJECT_ROOT / "backend_embedded", out / "backend_embedded")
    _copy_tree(PROJECT_ROOT / "realtime_studio", out / "realtime_studio")
    _copy_tree(PROJECT_ROOT / "tools", out / "tools")


def _compute_node_install_bat() -> str:
    return r"""@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

set "TORCH_CHANNEL=%REALTIME_STUDIO_TORCH_CHANNEL%"
if not defined TORCH_CHANNEL set "TORCH_CHANNEL=cu130"
set "TORCH_FALLBACK_CHANNEL=cu128"
set "TORCH_INDEX_URL=https://download.pytorch.org/whl/%TORCH_CHANNEL%"
set "TORCH_FALLBACK_INDEX_URL=https://download.pytorch.org/whl/%TORCH_FALLBACK_CHANNEL%"

if not exist ".venv\Scripts\python.exe" (
    echo [1/5] Tworzenie .venv ...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/5] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel

echo [3/5] Instalacja GPU PyTorch ...
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_INDEX_URL%
if errorlevel 1 (
    echo [WARN] Fallback do %TORCH_FALLBACK_CHANNEL% ...
    python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url %TORCH_FALLBACK_INDEX_URL%
    if errorlevel 1 (
        echo [BLAD] Nie udalo sie zainstalowac GPU PyTorch.
        pause
        exit /b 1
    )
)

echo [4/5] Instalacja zaleznosci ComputeNode ...
python -m pip install -r requirements.compute_node.txt
if errorlevel 1 (
    echo [BLAD] Nie udalo sie zainstalowac requirements.compute_node.txt
    pause
    exit /b 1
)

echo [5/5] Instalacja bitsandbytes ...
python -m pip install "bitsandbytes>=0.48,<1"
if errorlevel 1 (
    echo [BLAD] bitsandbytes nie zainstalowal sie poprawnie.
    pause
    exit /b 1
)

echo GOTOWE
pause
"""


def _compute_node_start_bat() -> str:
    return r"""@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw installers\windows\setup_compute_node.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_STUDIO_BACKEND_ROOT=%ROOT_DIR%\backend_embedded
set REALTIME_COMPUTE_CONFIG=%ROOT_DIR%\config.json
python -m realtime_studio.node_manager
"""


def _compute_node_setup_sh() -> str:
    return """#!/bin/bash
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
"""


def _compute_node_start_sh() -> str:
    return """#!/bin/bash
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
"""


def _remote_gui_install_bat() -> str:
    return r"""@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Tworzenie .venv ...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo [2/3] Aktualizacja pip ...
python -m pip install -U pip setuptools wheel

echo [3/3] Instalacja zaleznosci RemoteGUI ...
python -m pip install -r requirements.remote_gui.txt
if errorlevel 1 (
    echo [BLAD] Nie udalo sie zainstalowac requirements.remote_gui.txt
    pause
    exit /b 1
)

echo GOTOWE
pause
"""


def _remote_gui_start_bat() -> str:
    return r"""@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "ROOT_DIR=%%~fI"
cd /d "%ROOT_DIR%"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw installers\windows\setup_remote_gui.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_REMOTE_GUI_CONFIG=%ROOT_DIR%\config.json
python -m realtime_studio.remote_main
"""


def _remote_gui_setup_sh() -> str:
    return """#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
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
"""


def _remote_gui_start_sh() -> str:
    return """#!/bin/bash
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
"""


def _write_open_config_bat(path: Path, config_name: str) -> None:
    _write_text(
        path,
        f"""@echo off
chcp 65001 >nul 2>&1
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\\..") do set "ROOT_DIR=%%~fI"
start "" notepad "%ROOT_DIR%\\{config_name}"
""",
    )


def _write_open_config_sh(path: Path, config_name: str) -> None:
    _write_executable_text(
        path,
        f"""#!/bin/bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
open -a TextEdit "$ROOT_DIR/{config_name}"
""",
    )


def _compute_node_dist() -> None:
    out = DIST_ROOT / COMPUTE_NODE_DIR
    _remove(out)
    out.mkdir(parents=True, exist_ok=True)
    windows_dir = out / WINDOWS_DIR
    mac_dir = out / MAC_DIR

    _copy_file(PROJECT_ROOT / "README.md", out / "README.md")
    _copy_file(PROJECT_ROOT / "requirements.compute_node.txt", out / "requirements.compute_node.txt")
    _copy_tree(PROJECT_ROOT / "backend_embedded", out / "backend_embedded")
    _copy_tree(PROJECT_ROOT / "realtime_studio", out / "realtime_studio")

    _write_json(out / "config.json", asdict(ComputeNodeConfig()))
    _write_text(windows_dir / "setup_compute_node.bat", _compute_node_install_bat())
    _write_open_config_bat(windows_dir / "configure_compute_node.bat", "config.json")
    _write_text(windows_dir / "start_compute_node.bat", _compute_node_start_bat())
    _write_executable_text(mac_dir / "setup_compute_node.sh", _compute_node_setup_sh())
    _write_open_config_sh(mac_dir / "configure_compute_node.sh", "config.json")
    _write_executable_text(mac_dir / "start_compute_node.sh", _compute_node_start_sh())


def _remote_gui_dist() -> None:
    out = DIST_ROOT / REMOTE_GUI_DIR
    _remove(out)
    out.mkdir(parents=True, exist_ok=True)
    windows_dir = out / WINDOWS_DIR
    mac_dir = out / MAC_DIR

    _copy_file(PROJECT_ROOT / "README.md", out / "README.md")
    _copy_file(PROJECT_ROOT / "requirements.remote_gui.txt", out / "requirements.remote_gui.txt")
    _copy_tree(PROJECT_ROOT / "realtime_studio", out / "realtime_studio")

    _write_json(out / "config.json", asdict(RemoteGuiConfig()))
    _write_text(windows_dir / "setup_remote_gui.bat", _remote_gui_install_bat())
    _write_open_config_bat(windows_dir / "configure_remote_gui.bat", "config.json")
    _write_text(windows_dir / "start_remote_gui.bat", _remote_gui_start_bat())
    _write_executable_text(mac_dir / "setup_remote_gui.sh", _remote_gui_setup_sh())
    _write_open_config_sh(mac_dir / "configure_remote_gui.sh", "config.json")
    _write_executable_text(mac_dir / "start_remote_gui.sh", _remote_gui_start_sh())


def main() -> int:
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    for legacy_name in LEGACY_DIRS:
        _remove(DIST_ROOT / legacy_name)
    _full_app_dist()
    _compute_node_dist()
    _remote_gui_dist()
    print(f"Distributions built in: {DIST_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
