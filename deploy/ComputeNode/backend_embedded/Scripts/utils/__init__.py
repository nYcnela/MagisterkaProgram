"""Narzędzia wspólne dla skryptów przetwarzania danych Vicon."""
from .vicon_parser import (
    # Dataclasses
    SectionMeta,
    AnglesData,
    TrajData,
    MotionData,
    
    # Parsowanie
    detect_delimiter,
    find_section_indices,
    parse_markers,
    
    # Ładowanie danych
    load_angles_fast,
    load_trajectories_fast,
    load_trajs_fast,
    
    # Helpery
    detect_gender_from_filename,
    detect_step_from_filename,
    interpolate_nans,
)

__all__ = [
    "SectionMeta", "AnglesData", "TrajData", "MotionData",
    "detect_delimiter", "find_section_indices", "parse_markers",
    "load_angles_fast", "load_trajectories_fast", "load_trajs_fast",
    "detect_gender_from_filename", "detect_step_from_filename",
    "interpolate_nans",
]
