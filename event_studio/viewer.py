from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np


# If you have multiple WSL distros, set it (else leave None)
WSL_DISTRO: Optional[str] = None

# Where OpenEB bin lives in WSL
OPENEB_BIN_CANDIDATES = [
    "$HOME/openeb/build/bin",
    "$HOME/openeb/build/Release/bin",
    "$HOME/openeb/build-release/bin",
    "$HOME/openeb/build-relwithdebinfo/bin",
]


@dataclass
class EventBatch:
    t: np.ndarray  # int64 (microseconds)
    x: np.ndarray  # int32
    y: np.ndarray  # int32
    p: np.ndarray  # int8  (0/1 or -1/1 depending on exporter)


def _wsl_base_cmd() -> list[str]:
    cmd = ["wsl.exe"]
    if WSL_DISTRO:
        cmd += ["-d", WSL_DISTRO]
    return cmd


def _run_wsl(cmd: str) -> subprocess.CompletedProcess[str]:
    p = subprocess.run(
        _wsl_base_cmd() + ["bash", "-lc", cmd],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(
            f"WSL command failed ({p.returncode}).\n"
            f"CMD: {cmd}\n"
            f"STDOUT:\n{p.stdout}\n"
            f"STDERR:\n{p.stderr}"
        )
    return p


def _wslpath(win_path: Path) -> str:
    p = subprocess.run(
        _wsl_base_cmd() + ["wslpath", "-a", str(win_path)],
        capture_output=True,
        text=True,
    )
    if p.returncode != 0:
        raise RuntimeError(f"wslpath failed: {p.stderr}")
    return p.stdout.strip()


def _find_openeb_bin() -> str:
    # Fast path: common folders
    for b in OPENEB_BIN_CANDIDATES:
        try:
            _run_wsl(f'test -d "{b}"')
            _run_wsl(f'test -x "{b}/metavision_file_to_csv"')
            return b
        except Exception:
            pass

    # Fallback search
    p = _run_wsl(
        'find "$HOME/openeb" -path "*bin/metavision_file_to_csv" -type f 2>/dev/null | head -n 1'
    )
    found = p.stdout.strip()
    if found:
        return str(Path(found).parent).replace("\\", "/")

    raise RuntimeError("Could not locate OpenEB bin folder containing metavision_file_to_csv.")


def h5_to_csv_windows(
    h5_path: str | Path,
    out_csv: str | Path,
    max_events: int = 2_000_000,
) -> Path:
    """
    Uses OpenEB's metavision_file_to_csv inside WSL to export events to CSV.

    max_events:
      Limits how many events get exported (keeps your app fast and avoids huge CSVs).
      If your OpenEB build doesn't support --max-events, we automatically fallback.
    """
    h5_path = Path(h5_path).resolve()
    out_csv = Path(out_csv).resolve()

    if not h5_path.exists():
        raise FileNotFoundError(h5_path)

    out_csv.parent.mkdir(parents=True, exist_ok=True)

    wsl_h5 = _wslpath(h5_path)
    wsl_csv = _wslpath(out_csv)

    openeb_bin = _find_openeb_bin()
    tool = f"{openeb_bin}/metavision_file_to_csv"

    base_cmd = f'"{tool}" -i "{wsl_h5}" -o "{wsl_csv}"'

    # Try with max-events first
    try:
        _run_wsl(base_cmd + f" --max-events {int(max_events)}")
    except RuntimeError:
        # Fallback for older OpenEB versions (no --max-events)
        _run_wsl(base_cmd)

    return out_csv


def load_events_from_csv(csv_path: str | Path, max_events: int = 2_000_000) -> EventBatch:
    """
    Loads OpenEB CSV (columns typically: t,x,y,p or x,y,p,t depending on version).
    We'll detect by header. Reads up to max_events rows.
    """
    csv_path = Path(csv_path).resolve()
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    # Read header
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        header = f.readline().strip()

    # Load numeric data
    data = np.genfromtxt(
        csv_path,
        delimiter=",",
        skip_header=1,
        max_rows=int(max_events),
    )

    if data.size == 0:
        return EventBatch(
            t=np.array([], dtype=np.int64),
            x=np.array([], dtype=np.int32),
            y=np.array([], dtype=np.int32),
            p=np.array([], dtype=np.int8),
        )

    if data.ndim == 1:
        data = data.reshape(1, -1)

    # Detect column order
    h = header.lower().replace(" ", "")
    cols = [c.strip() for c in h.split(",")]

    if "t" in cols and "x" in cols and "y" in cols and "p" in cols:
        idx_t = cols.index("t")
        idx_x = cols.index("x")
        idx_y = cols.index("y")
        idx_p = cols.index("p")
    else:
        # fallback guess if no header
        # assume x,y,p,t
        idx_x, idx_y, idx_p, idx_t = 0, 1, 2, 3

    t = data[:, idx_t].astype(np.int64, copy=False)
    x = data[:, idx_x].astype(np.int32, copy=False)
    y = data[:, idx_y].astype(np.int32, copy=False)

    # p can come out as floats from genfromtxt -> cast safely
    p_raw = data[:, idx_p]
    p = p_raw.astype(np.int8, copy=False)

    return EventBatch(t=t, x=x, y=y, p=p)


def infer_hw(events: EventBatch) -> Tuple[int, int]:
    w = int(events.x.max()) + 1 if events.x.size else 0
    h = int(events.y.max()) + 1 if events.y.size else 0
    if w <= 0 or h <= 0:
        raise RuntimeError("Could not infer sensor size from CSV.")
    return (h, w)


def accumulate_frame(
    events: EventBatch,
    hw: Tuple[int, int],
    window_us: int = 50_000,
    polarity: str = "both",
    t_start_us: Optional[int] = None,
) -> np.ndarray:
    """
    Make a single accumulated grayscale frame from a time slice.

    - window_us: size of accumulation window
    - polarity: 'both' | 'pos' | 'neg'
    - t_start_us: if None, uses earliest t in events
    """
    h, w = hw
    img16 = np.zeros((h, w), dtype=np.uint16)

    if events.t.size == 0:
        return np.zeros((h, w), dtype=np.uint8)

    if t_start_us is None:
        t0 = int(events.t.min())
    else:
        t0 = int(t_start_us)

    t1 = t0 + int(window_us)
    mask = (events.t >= t0) & (events.t < t1)

    if polarity == "pos":
        mask &= (events.p > 0)
    elif polarity == "neg":
        mask &= (events.p <= 0)

    xs = events.x[mask]
    ys = events.y[mask]

    if xs.size and ys.size:
        np.add.at(img16, (ys, xs), 1)

    m = int(img16.max())
    if m > 0:
        img8 = (img16 / m * 255).astype(np.uint8)
    else:
        img8 = img16.astype(np.uint8)

    return np.ascontiguousarray(img8)


from dataclasses import dataclass

@dataclass
class RoiStats:
    n_events: int
    duration_us: int
    events_per_ms: float
    pos: int
    neg: int
    polarity_ratio: float  # pos / max(1, neg)
    active_pixels: int


def compute_roi_stats(events, hw, roi, t0_us: int, window_us: int) -> RoiStats:
    """
    Compute simple, honest ROI stats inside [t0_us, t0_us + window_us).
    roi is in IMAGE coords (x,y,w,h).
    """
    if events is None or events.t.size == 0:
        return RoiStats(0, window_us, 0.0, 0, 0, 0.0, 0)

    t1_us = t0_us + int(window_us)

    # time window mask
    m = (events.t >= t0_us) & (events.t < t1_us)

    # roi mask
    x0, y0 = int(roi.x), int(roi.y)
    x1, y1 = x0 + int(roi.w), y0 + int(roi.h)

    m &= (events.x >= x0) & (events.x < x1) & (events.y >= y0) & (events.y < y1)

    xs = events.x[m]
    ys = events.y[m]
    ps = events.p[m]

    n = int(xs.size)
    if n == 0:
        return RoiStats(0, window_us, 0.0, 0, 0, 0.0, 0)

    # polarity split (depends on your encoding; this matches your earlier logic)
    pos = int((ps > 0).sum())
    neg = int(n - pos)

    # active pixels: count unique (x,y)
    # pack to a single int for speed
    w = hw[1]
    packed = (ys.astype(np.int64) * w) + xs.astype(np.int64)
    active = int(np.unique(packed).size)

    events_per_ms = n / max(1e-9, (window_us / 1000.0))
    ratio = pos / max(1, neg)

    return RoiStats(
        n_events=n,
        duration_us=window_us,
        events_per_ms=float(events_per_ms),
        pos=pos,
        neg=neg,
        polarity_ratio=float(ratio),
        active_pixels=active,
    )
