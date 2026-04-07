from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys

from .settings import StudioConfig


def _looks_like_backend_root(root: Path) -> bool:
    return (
        (root / "bin/run_udp_e2e_test.py").exists()
        and (root / "bin/llm_server.py").exists()
    )


def _app_anchor_dir() -> Path:
    if getattr(sys, "frozen", False):  # type: ignore[attr-defined]
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _read_backend_hint(anchor: Path) -> Path | None:
    hint_names = (".realtime_studio_backend_root", "realtime_studio.backend_root")
    search_dirs = (anchor, anchor.parent)
    for directory in search_dirs:
        for name in hint_names:
            hint = directory / name
            if not hint.exists():
                continue
            try:
                raw = hint.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if not raw:
                continue
            path = Path(os.path.expandvars(raw)).expanduser()
            if not path.is_absolute():
                path = (hint.parent / path).resolve()
            return path
    return None


def _embedded_backend_candidates(anchor: Path) -> list[Path]:
    return [
        anchor / "backend_embedded",
        anchor / "backend_runtime",
        anchor / "backend_runtime" / "Magisterka",
        anchor.parent / "backend_embedded",
        anchor.parent / "backend_runtime",
        anchor.parent / "backend_runtime" / "Magisterka",
    ]


def discover_backend_root(explicit_root: str = "") -> Path:
    candidates: list[Path] = []
    seen: set[str] = set()
    anchor = _app_anchor_dir()

    def add(path: Path | str | None, *, base: Path | None = None) -> None:
        if not path:
            return
        resolved = Path(os.path.expandvars(str(path))).expanduser()
        if not resolved.is_absolute() and base is not None:
            resolved = (base / resolved).resolve()
        key = str(resolved)
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    explicit_clean = explicit_root.strip()
    if explicit_clean:
        add(explicit_clean)
        add(explicit_clean, base=anchor)

    env_root = os.getenv("REALTIME_STUDIO_BACKEND_ROOT", "").strip()
    if env_root:
        add(env_root)
        add(env_root, base=anchor)

    hint_root = _read_backend_hint(anchor)
    if hint_root is not None:
        add(hint_root)

    for candidate in _embedded_backend_candidates(anchor):
        add(candidate)

    cwd = Path.cwd()
    add(cwd)
    for parent in cwd.parents:
        add(parent)

    here = Path(__file__).resolve()
    add(here.parent)
    for parent in here.parents:
        add(parent)

    add(anchor)
    add(anchor.parent)
    add(anchor / "Magisterka")
    add(anchor.parent / "Magisterka")
    add(anchor.parent.parent if anchor.parent != anchor.parent.parent else None)
    add(anchor.parent.parent / "Magisterka")

    home = Path.home()
    add(home / "PycharmProjects" / "Magisterka")
    add(home / "Nextcloud" / "Studia" / "Magisterka")

    expanded: list[Path] = []
    for candidate in candidates:
        expanded.append(candidate)
        expanded.append(candidate / "Magisterka")

    for candidate in expanded:
        root = candidate.resolve()
        if _looks_like_backend_root(root):
            return root

    raise FileNotFoundError(
        "Could not auto-detect backend root. "
        "Set REALTIME_STUDIO_BACKEND_ROOT, or create .realtime_studio_backend_root "
        "next to app with a relative path like ../Magisterka."
    )


def resolve_under_root(path_like: str, root: Path) -> Path:
    path = Path(path_like)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def extract_feedback_text(line: str) -> str | None:
    marker = "[FEEDBACK]"
    if marker not in line:
        return None
    return line.split(marker, 1)[1].strip()


def build_backend_command(cfg: StudioConfig, run_id: str | None = None) -> tuple[str, list[str], str, Path]:
    resolved_run_id = run_id or datetime.now().strftime("studio_%Y%m%d_%H%M%S")

    backend_root = discover_backend_root(cfg.backend_root)

    output_root = resolve_under_root(cfg.output_root, backend_root)

    if cfg.session_mode:
        script = backend_root / "bin/run_udp_controlled_session.py"
        if not script.exists():
            raise FileNotFoundError(f"Missing session script: {script}")

        args: list[str] = [
            str(script),
            "--control-host",
            str(cfg.udp_host),
            "--control-port",
            str(cfg.udp_control_port),
            "--udp-host",
            str(cfg.udp_host),
            "--udp-port",
            str(cfg.udp_data_port),
            "--input-hz",
            str(cfg.input_hz),
            "--window-seconds",
            str(cfg.window_seconds),
            "--stride-seconds",
            str(cfg.stride_seconds),
            "--duration-seconds",
            str(cfg.duration_seconds),
            "--max-windows",
            str(cfg.max_windows),
            "--gender",
            str(cfg.gender),
            "--step-type",
            str(cfg.step_type),
            "--sequence-name",
            str(cfg.sequence_name),
            "--output-root",
            str(output_root),
            "--live-z-threshold",
            str(cfg.live_z_threshold),
            "--live-major-order-threshold",
            str(cfg.live_major_order_threshold),
        ]
        if cfg.live_emit_minor_order_text:
            args.append("--live-emit-minor-order-text")
        if cfg.llm_enabled:
            args.extend(["--llm-url", f"http://{cfg.llm_host}:{cfg.llm_port}"])
    else:
        script = backend_root / "bin/run_udp_e2e_test.py"
        if not script.exists():
            raise FileNotFoundError(f"Missing receiver script: {script}")

        pattern_file = resolve_under_root(cfg.resolved_pattern_file(), backend_root)
        if not pattern_file.exists():
            raise FileNotFoundError(f"Missing pattern file: {pattern_file}")

        args = [
            str(script),
            "--udp-host",
            str(cfg.udp_host),
            "--udp-port",
            str(cfg.udp_data_port),
            "--input-hz",
            str(cfg.input_hz),
            "--window-seconds",
            str(cfg.window_seconds),
            "--stride-seconds",
            str(cfg.stride_seconds),
            "--duration-seconds",
            str(cfg.duration_seconds),
            "--max-windows",
            str(cfg.max_windows),
            "--sequence-name",
            str(cfg.sequence_name),
            "--gender",
            str(cfg.gender),
            "--step-type",
            str(cfg.step_type),
            "--pattern-file",
            str(pattern_file),
            "--model-inputs-only",
            "--output-root",
            str(output_root),
            "--run-id",
            resolved_run_id,
            "--live-z-threshold",
            str(cfg.live_z_threshold),
            "--live-major-order-threshold",
            str(cfg.live_major_order_threshold),
        ]
        if cfg.live_emit_minor_order_text:
            args.append("--live-emit-minor-order-text")
        if cfg.llm_enabled:
            args.extend(["--llm-url", f"http://{cfg.llm_host}:{cfg.llm_port}"])

    program = cfg.python_exec.strip() or sys.executable
    args.insert(0, "-u")
    return program, args, resolved_run_id, backend_root


def build_llm_command(cfg: StudioConfig) -> tuple[str, list[str], Path]:
    backend_root = discover_backend_root(cfg.backend_root)
    script = backend_root / "bin/llm_server.py"
    if not script.exists():
        raise FileNotFoundError(f"Missing LLM server script: {script}")

    adapter_dir = resolve_under_root(cfg.llm_adapter_dir, backend_root)
    if not adapter_dir.exists():
        raise FileNotFoundError(f"Missing adapter dir: {adapter_dir}")

    args = [
        "-u",
        str(script),
        "--adapter-dir",
        str(adapter_dir),
        "--host",
        str(cfg.llm_host),
        "--port",
        str(cfg.llm_port),
    ]
    if cfg.llm_model_id.strip():
        args.extend(["--model-id", cfg.llm_model_id.strip()])
    if not cfg.llm_use_4bit:
        args.append("--no-4bit")

    program = cfg.python_exec.strip() or sys.executable
    return program, args, backend_root

