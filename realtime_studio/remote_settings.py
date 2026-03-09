from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


_APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = _APP_ROOT / "remote_gui_config.json"


@dataclass
class RemoteGuiConfig:
    node_host: str = "100.90.0.102"
    node_port: int = 8010
    auto_connect: bool = True

    dance_id: str = "k_krok_podstawowy_polonez"
    sequence_name: str = "udp_sequence"
    gender: str = "female"
    step_type: str = "step"

    auto_start_llm: bool = True


def resolve_config_path(path: Path | None = None) -> Path:
    env_path = os.getenv("REALTIME_REMOTE_GUI_CONFIG", "").strip()
    if path is not None:
        return path
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_PATH


def load_remote_gui_config(path: Path | None = None) -> RemoteGuiConfig:
    resolved = resolve_config_path(path)
    if not resolved.exists():
        return RemoteGuiConfig()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return RemoteGuiConfig()

    cfg = RemoteGuiConfig()
    for key, value in raw.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def save_remote_gui_config(cfg: RemoteGuiConfig, path: Path | None = None) -> Path:
    resolved = resolve_config_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    return resolved
