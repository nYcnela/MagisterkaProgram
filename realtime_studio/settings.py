from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import sys


_APP_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = _APP_ROOT
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass
class StudioConfig:
    # Optional override. Empty means auto-discover backend root.
    backend_root: str = ""
    python_exec: str = sys.executable

    udp_host: str = "0.0.0.0"
    udp_data_port: int = 5005
    udp_control_port: int = 5006
    llm_enabled: bool = True
    llm_host: str = "127.0.0.1"
    llm_port: int = 8000

    llm_adapter_dir: str = "outputs/manual/danube_4b/model_danube_supervised/lora_adapter"
    llm_model_id: str = ""
    llm_use_4bit: bool = True
    auto_start_llm: bool = True

    input_hz: float = 100.0
    window_seconds: float = 4.0
    stride_seconds: float = 3.0
    duration_seconds: float = 0.0
    max_windows: int = 0

    dance_id: str = "k_krok_podstawowy_polonez"
    pattern_file: str = ""
    sequence_name: str = "udp_sequence"
    gender: str = "female"
    step_type: str = "step"

    live_z_threshold: float = 1.7
    live_major_order_threshold: int = 60
    live_emit_minor_order_text: bool = False

    output_root: str = "data/tmp/realtime_e2e"
    candidate_root: str = "data/tmp/realtime_candidate"
    offline_runs_root: str = "data/tmp/offline_runs"

    auto_control_port: bool = True
    auto_detect_dance: bool = True
    session_mode: bool = True

    def resolved_pattern_file(self) -> str:
        if self.pattern_file.strip():
            return self.pattern_file.strip()
        return f"data/json/manual/pipeline/8_patterns/enriched/{self.dance_id}_pattern.json"


def load_config(path: Path = SETTINGS_PATH) -> StudioConfig:
    if not path.exists():
        return StudioConfig()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return StudioConfig()

    cfg = StudioConfig()
    for key, value in raw.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def save_config(cfg: StudioConfig, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
