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
cd /d "%~dp0"

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
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw 1_INSTALUJ.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_STUDIO_BACKEND_ROOT=%~dp0backend_embedded
set REALTIME_COMPUTE_CONFIG=%~dp0config.json
python -m realtime_studio.node_manager
"""


def _compute_node_install_command() -> str:
    return """#!/bin/zsh
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
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${TORCH_INDEX_URL}" || \\
python -m pip install --upgrade --force-reinstall --no-cache-dir torch torchvision torchaudio --index-url "${TORCH_FALLBACK_INDEX_URL}"

echo "[4/5] Instalacja zaleznosci ComputeNode ..."
python -m pip install -r requirements.compute_node.txt

echo "[5/5] Instalacja bitsandbytes ..."
python -m pip install "bitsandbytes>=0.48,<1"

echo "GOTOWE"
read -k 1 "?Nacisnij dowolny klawisz, aby zamknac..."
"""


def _compute_node_start_command() -> str:
    return """#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "[BLAD] Brak .venv — uruchom najpierw 1_INSTALUJ.command"
  read -k 1 "?Nacisnij dowolny klawisz, aby zamknac..."
  exit 1
fi

source .venv/bin/activate
export REALTIME_STUDIO_BACKEND_ROOT="$PWD/backend_embedded"
export REALTIME_COMPUTE_CONFIG="$PWD/config.json"
python -m realtime_studio.node_manager
"""


def _remote_gui_install_bat() -> str:
    return r"""@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

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
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [BLAD] Brak .venv — uruchom najpierw 1_INSTALUJ.bat
    pause
    exit /b 1
)

call .venv\Scripts\activate.bat
set REALTIME_REMOTE_GUI_CONFIG=%~dp0config.json
python -m realtime_studio.remote_main
"""


def _remote_gui_install_command() -> str:
    return """#!/bin/zsh
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
"""


def _remote_gui_start_command() -> str:
    return """#!/bin/zsh
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
"""


def _write_open_config_bat(path: Path, config_name: str) -> None:
    _write_text(
        path,
        f"""@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
start "" notepad "{config_name}"
""",
    )


def _write_open_config_command(path: Path, config_name: str) -> None:
    _write_text(
        path,
        f"""#!/bin/zsh
set -e
cd "$(dirname "$0")"
open -a TextEdit "{config_name}"
""",
    )
    _mark_executable(path)


def _compute_node_dist() -> None:
    out = DIST_ROOT / COMPUTE_NODE_DIR
    _remove(out)
    out.mkdir(parents=True, exist_ok=True)

    _copy_file(PROJECT_ROOT / "README.md", out / "README.md")
    _copy_file(PROJECT_ROOT / "requirements.compute_node.txt", out / "requirements.compute_node.txt")
    _copy_tree(PROJECT_ROOT / "backend_embedded", out / "backend_embedded")
    _copy_tree(PROJECT_ROOT / "realtime_studio", out / "realtime_studio")

    _write_json(out / "config.json", asdict(ComputeNodeConfig()))
    _write_text(out / "1_INSTALUJ.bat", _compute_node_install_bat())
    _write_open_config_bat(out / "2_KONFIGURACJA.bat", "config.json")
    _write_text(out / "3_START.bat", _compute_node_start_bat())
    _write_text(out / "1_INSTALUJ.command", _compute_node_install_command())
    _mark_executable(out / "1_INSTALUJ.command")
    _write_open_config_command(out / "2_KONFIGURACJA.command", "config.json")
    _write_text(out / "3_START.command", _compute_node_start_command())
    _mark_executable(out / "3_START.command")


def _remote_gui_dist() -> None:
    out = DIST_ROOT / REMOTE_GUI_DIR
    _remove(out)
    out.mkdir(parents=True, exist_ok=True)

    _copy_file(PROJECT_ROOT / "README.md", out / "README.md")
    _copy_file(PROJECT_ROOT / "requirements.remote_gui.txt", out / "requirements.remote_gui.txt")
    _copy_tree(PROJECT_ROOT / "realtime_studio", out / "realtime_studio")

    _write_json(out / "config.json", asdict(RemoteGuiConfig()))
    _write_text(out / "1_INSTALUJ.bat", _remote_gui_install_bat())
    _write_open_config_bat(out / "2_KONFIGURACJA.bat", "config.json")
    _write_text(out / "3_START.bat", _remote_gui_start_bat())
    _write_text(out / "1_INSTALUJ.command", _remote_gui_install_command())
    _mark_executable(out / "1_INSTALUJ.command")
    _write_open_config_command(out / "2_KONFIGURACJA.command", "config.json")
    _write_text(out / "3_START.command", _remote_gui_start_command())
    _mark_executable(out / "3_START.command")


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
