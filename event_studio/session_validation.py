"""Validate settings before a session can replace an open analysis."""

import math


def validate_settings(session):
    if not isinstance(session, dict):
        raise ValueError("Session must be a JSON object.")
    if session.get("format_version") not in (1, 2, 3, 4, 5, 6, 7, 8):
        raise ValueError("Unsupported session format version.")
    from .filters import FilterSettings

    FilterSettings(**session.get("filters", {})).validate()
    view = session.get("view", {})
    if not isinstance(view, dict):
        raise ValueError("Session view must be an object.")
    for key in (
        "position_us",
        "duration_us",
        "zoom_start",
        "zoom_end",
        "step_us",
        "timeline_value",
        "active_roi_index",
        "selected_slice_index",
        "loop_slice_index",
        "arrow_grid",
        "arrow_min_events",
    ):
        value = view.get(key)
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            raise ValueError(f"Session {key} must be an integer.")
    for key in ("duration_us", "step_us"):
        if key in view and view[key] <= 0:
            raise ValueError(f"Session {key} must be positive.")
    limits = {
        "window_ms": (0.001, 1e12),
        "persistence_ms": (0.001, 60000),
        "glow_intensity": (0, 3),
        "arrow_scale": (0.2, 10),
        "arrow_silhouette": (0, 1),
    }
    for key, (lower, upper) in limits.items():
        if key in view:
            value = view[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, (float, int))
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"Session {key} is outside its supported range.")
    if view.get("heat_scale", "Log relative") not in (
        "Log relative",
        "Linear relative",
        "Absolute (100 events/pixel)",
    ):
        raise ValueError("Unknown heatmap normalization.")
    for key in ("rois", "slices", "annotations", "detections"):
        if not isinstance(session.get(key, []), list) or not all(
            isinstance(item, dict) for item in session.get(key, [])
        ):
            raise ValueError(f"Session {key} must be a list of objects.")
    for item in session.get("slices", []):
        FilterSettings(**item.get("filters", {})).validate()
    analysis = session.get("analysis_settings", {})
    if not isinstance(analysis, dict):
        raise ValueError("Analysis settings must be an object.")
    numeric_limits = {
        "bin_us": (1, 1_000_000_000),
        "threshold": (0, 1e9),
        "min_burst_us": (1, 1_000_000_000),
        "max_shift": (1, 1024),
        "minimum_events": (1, 1_000_000),
        "minimum_quality": (0, 1),
        "units_per_pixel": (0, 1e9),
        "amplification": (0.1, 1000),
    }
    for key, (lower, upper) in numeric_limits.items():
        if key in analysis:
            value = analysis[key]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or not lower <= value <= upper
            ):
                raise ValueError(f"Invalid analysis setting: {key}")
    for key in ("bin_us", "min_burst_us", "max_shift", "minimum_events"):
        if key in analysis and not isinstance(analysis[key], int):
            raise ValueError(f"Analysis {key} must be an integer.")
    if analysis.get("scope", "Whole field") not in (
        "Whole field",
        "Active ROI",
        "All ROIs",
    ):
        raise ValueError("Unknown analysis scope.")
    for key in ("normalize", "compute_motion"):
        if key in analysis and not isinstance(analysis[key], bool):
            raise ValueError(f"Analysis {key} must be a boolean.")
    for note in session.get("annotations", []):
        if not isinstance(note.get("name"), str) or not isinstance(
            note.get("text", ""), str
        ):
            raise ValueError("Annotations require a name and text strings.")
        if not isinstance(note.get("labels", []), list) or not all(
            isinstance(label, str) for label in note.get("labels", [])
        ):
            raise ValueError("Annotation labels must be a list of strings.")
    for note in session.get("annotations", []) + session.get("detections", []):
        if (
            not isinstance(note.get("t0"), int)
            or not isinstance(note.get("t1"), int)
            or note["t1"] < note["t0"]
        ):
            raise ValueError("Invalid annotation interval.")
