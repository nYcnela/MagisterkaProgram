from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


_APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = _APP_ROOT / "compute_node_config.json"


@dataclass
class ComputeNodeConfig:
    manager_host: str = "0.0.0.0"
    manager_port: int = 8010

    backend_root: str = ""
    python_exec: str = ""

    udp_host: str = "0.0.0.0"
    udp_data_port: int = 5005
    udp_control_port: int = 5006

    llm_host: str = "127.0.0.1"
    llm_port: int = 8000
    llm_enabled: bool = True
    llm_adapter_dir: str = "lora_adapters/danube_4b"
    llm_model_id: str = ""
    llm_use_4bit: bool = True
    auto_start_llm_with_backend: bool = True

    input_hz: float = 100.0
    window_seconds: float = 4.0
    stride_seconds: float = 3.0
    duration_seconds: float = 0.0
    max_windows: int = 0

    dance_id: str = "k_krok_podstawowy_polonez"
    sequence_name: str = "udp_sequence"
    gender: str = "female"
    step_type: str = "step"

    live_z_threshold: float = 1.7
    live_major_order_threshold: int = 60
    live_emit_minor_order_text: bool = False

    output_root: str = "../runtime/realtime_e2e"
    candidate_root: str = "../runtime/realtime_candidate"
    offline_runs_root: str = "../runtime/offline_runs"

    session_mode: bool = True
    auto_control_port: bool = True
    auto_detect_dance: bool = False

    vr_feedback_enabled: bool = False
    vr_feedback_host: str = "127.0.0.1"
    vr_feedback_port: int = 5007


def resolve_config_path(path: Path | None = None) -> Path:
    env_path = os.getenv("REALTIME_COMPUTE_CONFIG", "").strip()
    if path is not None:
        return path
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_PATH


def load_compute_config(path: Path | None = None) -> ComputeNodeConfig:
    resolved = resolve_config_path(path)
    if not resolved.exists():
        return ComputeNodeConfig()
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
    except Exception:
        return ComputeNodeConfig()

    cfg = ComputeNodeConfig()
    for key, value in raw.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def save_compute_config(cfg: ComputeNodeConfig, path: Path | None = None) -> Path:
    resolved = resolve_config_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    return resolved
