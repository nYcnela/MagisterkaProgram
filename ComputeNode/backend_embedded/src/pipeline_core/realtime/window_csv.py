from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .contracts import FrameWindow
from .udp_protocol import DEFAULT_MARKER_NAMES


def _fmt_float(v: float | None) -> str:
    if v is None:
        return ""
    return f"{float(v):.6f}"


def write_window_as_vicon_csv(
    window: FrameWindow,
    out_path: Path,
    *,
    sample_rate_hz: float,
    marker_order: Sequence[str] = DEFAULT_MARKER_NAMES,
) -> Path:
    """
    Write a single realtime window to a minimal Vicon-like CSV with Trajectories section.

    compatible with scripts/0calculate_angles_v3.py::load_trajectories.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fps = int(round(sample_rate_hz))

    marker_line_cells = ["", ""]
    header_cells = ["Frame", "Sub Frame"]
    units_cells = ["", ""]
    for marker_name in marker_order:
        marker_line_cells.extend([marker_name, "", ""])
        header_cells.extend(["X", "Y", "Z"])
        units_cells.extend(["mm", "mm", "mm"])

    lines: list[str] = [
        "Trajectories",
        str(fps),
        ";".join(marker_line_cells),
        ";".join(header_cells),
        ";".join(units_cells),
    ]

    for frame in window.frames:
        row_cells: list[str] = [str(frame.frame_number), "0"]
        for marker_name in marker_order:
            sample = frame.markers.get(marker_name)
            if sample is None:
                row_cells.extend(["", "", ""])
            else:
                row_cells.extend(
                    [
                        _fmt_float(sample.x),
                        _fmt_float(sample.y),
                        _fmt_float(sample.z),
                    ]
                )
        lines.append(";".join(row_cells))

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path

