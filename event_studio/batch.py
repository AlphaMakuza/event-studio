"""Repeatable CSV batch analysis with explicit errors and compatibility checks."""

from pathlib import Path
from dataclasses import asdict
from .api import Recording, Roi
from .activity import detect_bursts
from .filters import CancelledError, apply_filters
from .io_utils import export_table
from .project_utils import save_json
from .version import __version__


def analyze_batch(
    paths,
    output_dir,
    *,
    bin_us=1000,
    threshold=100.0,
    filters=None,
    rois=None,
    expected_hw=None,
    cancelled=lambda: False,
    progress=lambda n, message: None,
):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    for i, path in enumerate(paths):
        if cancelled():
            break
        progress(int(i * 100 / max(1, len(paths))), f"Analyzing {Path(path).name}")
        try:
            original = Recording.open(path)
            if rois:
                if expected_hw is None or original.resolution != tuple(expected_hw):
                    raise ValueError(
                        "ROI coordinate system is incompatible with this recording."
                    )
                if "inferred" in original.events.metadata.get(
                    "resolution_origin", "inferred"
                ):
                    raise ValueError(
                        "Cannot verify ROI compatibility from inferred sensor dimensions. Supply a sensor metadata sidecar."
                    )
            if cancelled():
                raise CancelledError("Batch cancelled after loading the recording.")
            recording = Recording(
                apply_filters(
                    original.events,
                    filters,
                    cancelled,
                    lambda value, message: progress(
                        int((i + value / 100) * 100 / max(1, len(paths))), message
                    ),
                )
            )
            if not len(original.events.t):
                raise ValueError("Empty recording")
            start, end = int(original.events.t[0]), int(original.events.t[-1]) + 1
            probes = rois or [{"name": "Full field", "roi": None}]
            for j, probe in enumerate(probes):
                if cancelled():
                    raise CancelledError("Batch cancelled")
                roi = Roi(**probe["roi"]) if probe.get("roi") else None
                series = recording.activity(start, end, bin_us, roi)
                bursts = detect_bursts(series, threshold)
                stats = recording.statistics(start, end, roi)
                destination = output / f"{i:04d}_{j:03d}_activity.csv"
                export_table(
                    destination,
                    [
                        "start_us",
                        "end_us_exclusive",
                        "total",
                        "positive",
                        "negative",
                        "events_per_ms",
                    ],
                    zip(
                        series.start_us,
                        series.end_us,
                        series.total,
                        series.positive,
                        series.negative,
                        series.rate,
                    ),
                    {**series.metadata, "probe": probe["name"], "bursts": bursts},
                )
                results.append(
                    {
                        "source": str(path),
                        "probe": probe["name"],
                        "status": "ok",
                        "events": stats.n_events,
                        "duration_us": stats.duration_us,
                        "events_per_ms": stats.events_per_ms,
                        "bursts": len(bursts),
                        "measurement_csv": destination.name,
                    }
                )
        except CancelledError:
            break
        except Exception as exc:
            results.append({"source": str(path), "status": "error", "error": str(exc)})
    report = {
        "software_version": __version__,
        "cancelled": bool(cancelled()),
        "parameters": {
            "bin_us": bin_us,
            "threshold_events_per_ms": threshold,
            "filters": filters or {},
            "rois": rois,
            "expected_hw": expected_hw,
        },
        "results": results,
    }
    save_json(output / "summary.json", report)
    export_table(
        output / "summary.csv",
        [
            "source",
            "probe",
            "status",
            "events",
            "duration_us",
            "events_per_ms",
            "bursts",
            "error",
        ],
        (
            [
                row.get(key, "")
                for key in (
                    "source",
                    "probe",
                    "status",
                    "events",
                    "duration_us",
                    "events_per_ms",
                    "bursts",
                    "error",
                )
            ]
            for row in results
        ),
        {
            "algorithm": "batch statistics summary",
            "parameters": report["parameters"],
            "cancelled": report["cancelled"],
        },
    )
    return report
