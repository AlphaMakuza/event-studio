"""Shared, non-destructive event queries and reproducible CSV I/O."""
from __future__ import annotations

import csv
import io
import hashlib
import json
import os
import re
import tempfile
from dataclasses import replace
from pathlib import Path

import numpy as np


def fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def polarity_ratio(positive, negative):
    """Positive/negative count ratio; zero for empty, infinity for positive-only."""
    return positive / negative if negative else (float("inf") if positive else 0.)


def dat_resolution(path):
    """Read optional Prophesee DAT comment metadata without decoding events."""
    dimensions = {}
    with Path(path).open("rb") as stream:
        for _ in range(128):
            line = stream.readline(4096)
            if not line.startswith(b"%"):
                break
            match = re.search(rb"%\s*(width|height)\s*[:=]?\s*(\d+)", line, re.I)
            if match:
                dimensions[match[1].decode().lower()] = int(match[2])
    return dimensions


def load_csv(path, max_events=None, *, cancel=None, progress=None):
    from .viewer import EventBatch

    path = Path(path).resolve()
    if max_events is not None and max_events < 1:
        raise ValueError("Event limit must be positive, or None for the full recording.")
    # Parse ordinary numeric CSV in NumPy, retaining exact integer timestamps.
    # Compact each block immediately instead of retaining four int64 columns.
    blocks, lines, count, complete = [], [], 0, True
    order = (3, 0, 1, 2)
    size = max(1, path.stat().st_size)
    numeric = re.compile(r"(?:[ \t]*[+-]?[0-9]+[ \t]*,){3}[ \t]*[+-]?[0-9]+[ \t]*(?:\r?\n|$)")
    last_t = None

    def check_cancel():
        if cancel and cancel():
            from .filters import CancelledError
            raise CancelledError("Recording import cancelled.")

    def flush(position):
        nonlocal last_t
        if not lines:
            return
        check_cancel()
        text = ''.join(lines)
        try:
            if len(names) == 4 and numeric.sub('', text) == '':
                data = np.loadtxt(io.StringIO(text), dtype=np.int64, delimiter=',', ndmin=2)[:, order]
            else:
                data = np.array([tuple(int(row[i].strip()) for i in order)
                                 for row in csv.reader(lines)], dtype=np.int64)
        except (ValueError, IndexError, OverflowError) as exc:
            raise ValueError(f"Invalid integer event near CSV event {count:,}: {exc}") from exc
        if np.any(data[:, 0] < 0) or np.any(data[:, 0] == np.iinfo(np.int64).max):
            raise ValueError("Timestamp outside supported nonnegative int64 range")
        if np.any(data[:, 1:3] < 0) or np.any(data[:, 1:3] >= 32768):
            raise ValueError("Pixel coordinates must be between 0 and 32767")
        if np.any((data[:, 3] < -1) | (data[:, 3] > 1)):
            raise ValueError("Polarity must be -1, 0 or 1")
        if (last_t is not None and data[0, 0] < last_t) or np.any(data[1:, 0] < data[:-1, 0]):
            raise ValueError("Timestamps must be nondecreasing; source order was not changed.")
        last_t = int(data[-1, 0])
        blocks.append([data[:, i].astype(dtype) for i, dtype in enumerate((np.int64, np.int32, np.int32, np.int8))])
        lines.clear()
        if progress:
            progress(min(90, int(position * 90 / size)), f"Reading events: {count:,} ({position / 1048576:.0f} / {size / 1048576:.0f} MB)")

    with path.open(encoding="utf-8-sig", newline="") as stream:
        while True:
            first = stream.readline()
            if not first:
                raise ValueError("Recording contains no events.")
            if first.strip() and not first.lstrip().startswith('%'):
                break
        names = [c.strip().lower() for c in next(csv.reader([first]))]
        header_present = all(c in names for c in ("t", "x", "y", "p"))
        if header_present:
            order = tuple(names.index(c) for c in ("t", "x", "y", "p"))
        else:
            lines.append(first if first.endswith('\n') else first + '\n')
            count = 1
        while True:
            line = stream.readline()
            if not line:
                break
            if not line.strip() or line.lstrip().startswith('%'):
                continue
            if max_events is not None and count == max_events:
                complete = False
                break
            lines.append(line if line.endswith('\n') else line + '\n')
            count += 1
            if len(lines) >= 131072:
                flush(stream.tell())
        flush(stream.tell())
    if not blocks:
        raise ValueError("Recording contains no events.")
    check_cancel()
    if progress:
        progress(91, "Preparing event arrays...")
    columns = []
    for i in range(4):
        check_cancel()
        columns.append(np.concatenate([block[i] for block in blocks]) if len(blocks) > 1 else blocks[0][i])
        for block in blocks:
            block[i] = None  # Release temporary columns as each final array is ready.
    del blocks
    timestamps, xs, ys, polarities = columns
    if progress:
        progress(94, "Verifying recording checksum...")
    metadata = {
        "csv_path": str(path), "sha256": fingerprint(path),
        "complete": complete, "loaded_events": count, "load_limit": max_events,
        "timestamp_unit": "us", "sorted": True,
        "header_present": header_present,
        "resolution_origin": "inferred from observed coordinates",
        "resolution": [int(xs.max()) + 1, int(ys.max()) + 1],
    }
    sidecar = path.with_suffix(".json")
    if sidecar.exists():
        try:
            saved = json.loads(sidecar.read_text(encoding="utf-8"))
            if saved.get('csv_sha256') and saved['csv_sha256']!=metadata['sha256']:
                raise ValueError('CSV content does not match its metadata sidecar hash.')
            if saved.get('partial_recording'):
                metadata['complete'] = False
                metadata['preview'] = True
                metadata['input_path'] = saved.get('original_path', str(path))
                metadata['input_sha256'] = saved.get('original_sha256')
            if saved.get('acquisition'):
                metadata['acquisition']=saved['acquisition']
            if saved.get('selection'):
                metadata['source_selection']=saved['selection']
            upstream=saved.get('source',{})
            if any(upstream.get('filters',{}).values()) or upstream.get('classification')=='DERIVED':
                metadata['classification']='DERIVED'
                metadata['inherited_processing']={'source':upstream,'selection':saved.get('selection')}
            resolution = saved.get("sensor_resolution", {})
            width, height = int(resolution["width"]), int(resolution["height"])
            if width < metadata["resolution"][0] or height < metadata["resolution"][1]:
                raise ValueError("Sidecar sensor resolution is smaller than observed coordinates.")
            metadata["resolution"] = [width, height]
            metadata["resolution_origin"] = resolution.get("origin", "metadata sidecar")
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    width, height = metadata["resolution"]
    if width <= 0 or height <= 0 or width * height > 16_777_216:
        raise ValueError("Sensor resolution exceeds the supported 16-megapixel image size.")
    events = EventBatch(timestamps, xs, ys, polarities, metadata)
    for arr in (events.t, events.x, events.y, events.p):
        arr.flags.writeable = False
    check_cancel()
    if progress:
        progress(100, f"Loaded {count:,} events")
    return events


def select(events, t0=None, t1=None, roi=None, polarity="both"):
    """Half-open time and spatial bounds. Time-only queries return array views."""
    if events.metadata.get("sorted", False):
        left = 0 if t0 is None else int(np.searchsorted(events.t, t0, side="left"))
        right = len(events.t) if t1 is None else int(np.searchsorted(events.t, t1, side="left"))
        batch = replace(events, t=events.t[left:right], x=events.x[left:right],
                        y=events.y[left:right], p=events.p[left:right])
        mask = np.ones(len(batch.t), dtype=bool)
    else:
        batch = events
        mask = np.ones(len(events.t), dtype=bool)
        if t0 is not None:
            mask &= batch.t >= t0
        if t1 is not None:
            mask &= batch.t < t1
    if roi is not None:
        mask &= ((batch.x >= roi.x) & (batch.x < roi.x + roi.w) &
                 (batch.y >= roi.y) & (batch.y < roi.y + roi.h))
    if polarity == "pos":
        mask &= batch.p > 0
    elif polarity == "neg":
        mask &= batch.p <= 0
    elif polarity != "both":
        raise ValueError(f"Unknown polarity: {polarity}")
    if mask.all():
        return batch
    return replace(batch, t=batch.t[mask], x=batch.x[mask], y=batch.y[mask], p=batch.p[mask])


def export_csv(path, events, hw, *, t0=None, t1=None, roi=None, polarity="both", extra=None, filter_spec=None):
    """Export exactly the selected original event tuples, with provenance."""
    if not events.metadata.get("complete", False):
        raise ValueError("This dataset is a limited preview. Reload the full recording before exporting.")
    if filter_spec:
        from .filters import apply_filters
        events = apply_filters(events, filter_spec)
    batch = select(events, t0, t1, roi, polarity)
    path = Path(path)
    if path.suffix.lower() != ".csv":
        raise ValueError("CSV export filenames must end in .csv so metadata uses a separate .json file.")
    if path.resolve() == Path(events.metadata.get("csv_path", "")).resolve():
        raise ValueError("Choose a different export path; the source recording must remain unchanged.")
    path.parent.mkdir(parents=True, exist_ok=True)
    from .project_utils import save_json
    from .io_utils import commit_pair
    from .version import __version__
    with tempfile.TemporaryDirectory(prefix="export-", dir=path.parent) as folder:
        staged = Path(folder) / path.name
        with staged.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("t", "x", "y", "p"))
            writer.writerows(zip(batch.t, batch.x, batch.y, batch.p))
        payload = {
            "format_version": 2, "software_version": __version__, "source": events.metadata,
            "sensor_resolution": {"width": hw[1], "height": hw[0],
                                  "origin": events.metadata.get("resolution_origin", "unknown")},
            "selection": {"start_us": t0, "end_us_exclusive": t1, "polarity": polarity,
                          "roi": None if roi is None else vars(roi)},
            "exported_event_count": len(batch.t), "timestamp_unit": "us",
            "csv_sha256": fingerprint(staged), "details": extra or {},
        }
        save_json(staged.with_suffix(".json"), payload)
        commit_pair(staged, staged.with_suffix(".json"), path, path.with_suffix(".json"))
    return len(batch.t)
