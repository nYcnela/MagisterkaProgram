from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
import unicodedata


_APP_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = _APP_ROOT
SETTINGS_PATH = APP_DIR / "settings.json"


@dataclass
class StudioConfig:
    # Dancer profile
    dancer_first_name: str = ""
    dancer_last_name: str = ""

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


def _sanitize_dirname(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    ascii_text = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-zA-Z0-9_-]", "_", ascii_text).strip("_") or "nieznany"


def _dancer_subdir(cfg: StudioConfig) -> str:
    parts = [cfg.dancer_first_name.strip(), cfg.dancer_last_name.strip()]
    joined = "_".join(part for part in parts if part)
    if not joined:
        return ""
    return _sanitize_dirname(joined)


def _strip_repeated_suffix(path_like: str, suffix: str) -> str:
    if not path_like or not suffix:
        return path_like

    path = Path(path_like)
    normalized = path
    while normalized.name == suffix:
        normalized = normalized.parent
    return str(normalized)


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

    dancer_dir = _dancer_subdir(cfg)
    if dancer_dir:
        cfg.output_root = _strip_repeated_suffix(cfg.output_root, dancer_dir)
        cfg.candidate_root = _strip_repeated_suffix(cfg.candidate_root, dancer_dir)
        cfg.offline_runs_root = _strip_repeated_suffix(cfg.offline_runs_root, dancer_dir)
    return cfg


def save_config(cfg: StudioConfig, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
