#!/usr/bin/env python3
"""Offline pipeline orchestrator used by CLI wrappers."""
from __future__ import annotations

import argparse
import copy
import glob
import json
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

DEFAULT_CONFIG = Path("offline_pipeline.config.json")
VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def discover_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_config(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if "stages" not in data:
        raise ValueError(f"Brak pola 'stages' w configu: {path}")
    return data


def resolve_path(path: Path, base_dir: Path) -> Path:
    return path if path.is_absolute() else (base_dir / path)


def parse_var_overrides(raw_items: Optional[List[str]]) -> Dict[str, str]:
    overrides: Dict[str, str] = {}
    for raw in raw_items or []:
        if "=" not in raw:
            raise ValueError(f"Niepoprawny format --var: '{raw}'. Użyj KEY=VALUE.")
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"Pusta nazwa zmiennej w --var: '{raw}'")
        overrides[key] = value
    return overrides


def candidate_root_overrides(root: Path) -> Dict[str, str]:
    root_str = str(root)
    return {
        "csv_calculated_root": f"{root_str}/csv/calculated",
        "csv_normalized_root": f"{root_str}/csv/normalized",
        "csv_downsampled_root": f"{root_str}/csv/downsampled",
        "plot_segment_bounds_root": f"{root_str}/plots/4segmentation_step_bounds",
        "json_segment_bounds_root": f"{root_str}/json/4_segmentation_bounds",
        "json_arms_root": f"{root_str}/json/7_arms_position",
        "json_patterns_root": f"{root_str}/json/8_patterns/patterns",
    }


def resolve_placeholders(value: Any, variables: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {k: resolve_placeholders(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_placeholders(v, variables) for v in value]
    if isinstance(value, str):

        def repl(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise KeyError(name)
            return str(variables[name])

        return VAR_PATTERN.sub(repl, value)
    return value


def arg_list_from_dict(args_dict: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for key, value in args_dict.items():
        flag = key if key.startswith("--") else f"--{key}"
        if isinstance(value, bool):
            if value:
                out.append(flag)
            continue
        if value is None:
            continue
        if isinstance(value, list):
            # [1, 2] -> --arg 1 2
            # [[1, 2], [3, 4]] -> --arg 1 2 --arg 3 4
            if value and all(isinstance(item, (list, tuple)) for item in value):
                for group in value:
                    out.append(flag)
                    out.extend(str(item) for item in group)
            else:
                out.append(flag)
                out.extend(str(item) for item in value)
            continue
        out.extend([flag, str(value)])
    return out


def get_git_head(project_root: Path) -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=project_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            return proc.stdout.strip()
    except Exception:
        pass
    return "unknown"


def collect_artifact_counts(project_root: Path, checks: Dict[str, str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for name, pattern in checks.items():
        pattern_str = str(pattern)
        if Path(pattern_str).is_absolute():
            result[name] = len(glob.glob(pattern_str, recursive=True))
        else:
            result[name] = len(list(project_root.glob(pattern_str)))
    return result


def collect_event_stats(project_root: Path, json_root: str) -> Dict[str, Any]:
    root = (project_root / json_root).resolve()
    stats: Dict[str, Any] = {"root": str(root), "file_count": 0, "event_count": 0, "labels": {}}
    if not root.exists():
        return stats

    labels = Counter()
    file_count = 0
    event_count = 0
    for path in root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        events = data.get("events", [])
        if not isinstance(events, list):
            continue
        file_count += 1
        for ev in events:
            if isinstance(ev, dict):
                label = ev.get("label")
                if label:
                    labels[label] += 1
                    event_count += 1

    stats["file_count"] = file_count
    stats["event_count"] = event_count
    stats["labels"] = dict(labels.most_common())
    return stats


def run_stage(
    project_root: Path,
    run_dir: Path,
    python_exec: str,
    stage_name: str,
    stage_cfg: Dict[str, Any],
    dry_run: bool,
) -> Dict[str, Any]:
    script = stage_cfg["script"]
    args = stage_cfg.get("args", {})
    cmd = [python_exec, str((project_root / script).resolve())] + arg_list_from_dict(args)

    started_at = utc_now_iso()
    t0 = time.time()
    stdout_path = run_dir / f"{stage_name}.stdout.log"
    stderr_path = run_dir / f"{stage_name}.stderr.log"

    if dry_run:
        return {
            "name": stage_name,
            "status": "dry_run",
            "script": script,
            "command": cmd,
            "started_at": started_at,
            "ended_at": utc_now_iso(),
            "duration_s": round(time.time() - t0, 4),
            "return_code": None,
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
        }

    proc = subprocess.run(
        cmd,
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    stdout_path.write_text(proc.stdout or "", encoding="utf-8")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8")

    return {
        "name": stage_name,
        "status": "ok" if proc.returncode == 0 else "failed",
        "script": script,
        "command": cmd,
        "started_at": started_at,
        "ended_at": utc_now_iso(),
        "duration_s": round(time.time() - t0, 4),
        "return_code": proc.returncode,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }


def selected_stages(order: Iterable[str], only: Optional[List[str]]) -> List[str]:
    if not only:
        return list(order)
    only_set = set(only)
    return [stage for stage in order if stage in only_set]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Uruchamia cały offline pipeline jedną komendą.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Ścieżka do configu JSON.")
    parser.add_argument("--only", nargs="*", default=None, help="Uruchom tylko wybrane etapy.")
    parser.add_argument("--dry-run", action="store_true", help="Pokaż komendy bez uruchamiania.")
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=None,
        help="Nadpisz katalog logów z configu.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Kontynuuj kolejne etapy nawet gdy jeden zakończy się błędem.",
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Nadpisz zmienną configu (można podać wielokrotnie).",
    )
    parser.add_argument(
        "--candidate-root",
        type=Path,
        default=None,
        help="Katalog roboczy dla artefaktów kandydata (nadpisuje kluczowe outputy pipeline).",
    )
    args = parser.parse_args(argv)

    project_root = discover_project_root()
    config_path = resolve_path(args.config, project_root).resolve()
    raw_cfg = load_config(config_path)

    try:
        cli_vars = parse_var_overrides(args.var)
    except ValueError as exc:
        print(f"[BŁĄD] {exc}")
        return 2

    cfg_vars = {str(k): str(v) for k, v in raw_cfg.get("variables", {}).items()}

    candidate_root: Optional[Path] = None
    candidate_vars: Dict[str, str] = {}
    if args.candidate_root is not None:
        candidate_root = resolve_path(args.candidate_root, project_root).resolve()
        candidate_vars = candidate_root_overrides(candidate_root)

    merged_vars: Dict[str, str] = {
        **cfg_vars,
        **candidate_vars,
        **cli_vars,
        "PROJECT_ROOT": str(project_root),
    }

    cfg = copy.deepcopy(raw_cfg)
    cfg["variables"] = merged_vars
    try:
        cfg = resolve_placeholders(cfg, merged_vars)
    except KeyError as exc:
        print(f"[BŁĄD] Brak wartości dla zmiennej configu: {exc}")
        return 2

    pipeline_order = cfg.get("pipeline_order", list(cfg["stages"].keys()))
    stages_to_run = selected_stages(pipeline_order, args.only)

    if args.only:
        unknown = sorted(set(args.only) - set(cfg["stages"].keys()))
        if unknown:
            print(f"[BŁĄD] Nieznane etapy: {', '.join(unknown)}")
            return 2

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.log_dir is not None:
        log_dir = resolve_path(args.log_dir, project_root).resolve()
    else:
        log_dir = resolve_path(Path(cfg.get("log_dir", "data/tmp/offline_runs")), project_root).resolve()
    run_dir = log_dir / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    python_exec = cfg.get("python_executable") or sys.executable
    continue_on_error = args.continue_on_error or bool(cfg.get("continue_on_error", False))

    run_summary: Dict[str, Any] = {
        "run_id": run_id,
        "started_at": utc_now_iso(),
        "ended_at": None,
        "project_root": str(project_root),
        "git_head": get_git_head(project_root),
        "config_path": str(config_path),
        "python_executable": python_exec,
        "dry_run": args.dry_run,
        "continue_on_error": continue_on_error,
        "candidate_root": str(candidate_root) if candidate_root else None,
        "variables": merged_vars,
        "stages_requested": stages_to_run,
        "stages": [],
        "status": "running",
    }

    (run_dir / "resolved_config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    failed = False
    for stage_name in stages_to_run:
        stage_cfg = cfg["stages"][stage_name]
        if not stage_cfg.get("enabled", True):
            run_summary["stages"].append(
                {
                    "name": stage_name,
                    "status": "skipped",
                    "reason": "disabled_in_config",
                    "script": stage_cfg.get("script"),
                }
            )
            print(f"[SKIP] {stage_name} (disabled)")
            continue

        print(f"[RUN ] {stage_name}")
        stage_result = run_stage(project_root, run_dir, python_exec, stage_name, stage_cfg, args.dry_run)
        run_summary["stages"].append(stage_result)
        print(f"[DONE] {stage_name} -> {stage_result['status']}")

        if stage_result["status"] == "failed":
            failed = True
            if not continue_on_error:
                print(f"[STOP] Zatrzymano po błędzie etapu: {stage_name}")
                break

    artifact_checks = cfg.get("artifact_checks", {})
    event_stats_roots = cfg.get("event_stats_roots", [])
    run_summary["artifact_counts"] = collect_artifact_counts(project_root, artifact_checks)
    run_summary["event_stats"] = [collect_event_stats(project_root, root) for root in event_stats_roots]

    run_summary["ended_at"] = utc_now_iso()
    run_summary["status"] = "failed" if failed else "ok"
    summary_path = run_dir / "run_summary.json"
    summary_path.write_text(json.dumps(run_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nRun status: {run_summary['status']}")
    print(f"Summary: {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

