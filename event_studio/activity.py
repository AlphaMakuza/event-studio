"""Deterministic binned event activity. All intervals are [start, end)."""

from dataclasses import dataclass
import math
import numpy as np
from .science import select


@dataclass
class Activity:
    start_us: np.ndarray
    end_us: np.ndarray
    total: np.ndarray
    positive: np.ndarray
    negative: np.ndarray
    bin_us: int
    metadata: dict

    @property
    def rate(self):
        return self.total * 1000.0 / (self.end_us - self.start_us)

    @property
    def cumulative(self):
        return np.cumsum(self.total)


def activity_series(events, t0, t1, bin_us=1000, roi=None, polarity="both"):
    if any(
        isinstance(v, bool) or not isinstance(v, (int, np.integer))
        for v in (t0, t1, bin_us)
    ):
        raise ValueError("Time bounds and bin width must be integer microseconds.")
    if t0 < 0 or t1 <= t0 or t1 > np.iinfo(np.int64).max or bin_us <= 0:
        raise ValueError("Use a positive bin width and nonempty supported interval.")
    n = (t1 - t0 + bin_us - 1) // bin_us
    if n > 1_000_000:
        raise ValueError("More than one million bins: increase the temporal bin width.")
    starts = t0 + np.arange(n, dtype=np.int64) * bin_us
    ends = starts + np.minimum(bin_us, t1 - starts)
    batch = select(events, t0, t1, roi, polarity)
    indices = (batch.t - t0) // bin_us
    total = np.bincount(indices, minlength=n).astype(np.int64)
    positive = np.bincount(indices[batch.p > 0], minlength=n).astype(np.int64)
    metadata = {
        "algorithm": "half-open integer event histogram",
        "source": events.metadata,
        "start_us": int(t0),
        "end_us_exclusive": int(t1),
        "bin_us": int(bin_us),
        "roi": vars(roi).copy() if roi is not None else None,
        "polarity": polarity,
        "rate_unit": "events/ms",
        "partial_final_bin": bool((t1 - t0) % bin_us),
    }
    return Activity(
        starts, ends, total, positive, total - positive, int(bin_us), metadata
    )


def detect_bursts(series, threshold, min_duration_us=1):
    if not math.isfinite(threshold) or threshold < 0 or min_duration_us <= 0:
        raise ValueError(
            "Use a finite nonnegative rate threshold and positive minimum duration."
        )
    # Strictly above threshold: a zero threshold never detects empty bins.
    active = series.rate > threshold
    edges = np.diff(np.r_[False, active, False].astype(np.int8))
    results = []
    for left, right in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        start, end = int(series.start_us[left]), int(series.end_us[right - 1])
        if end - start >= min_duration_us:
            results.append(
                {
                    "t0": start,
                    "t1": end,
                    "duration_us": end - start,
                    "peak_events_per_ms": float(series.rate[left:right].max()),
                    "event_count": int(series.total[left:right].sum()),
                    "threshold_events_per_ms": threshold,
                    "bin_us": series.bin_us,
                    "minimum_duration_us": min_duration_us,
                }
            )
    return results


def frequency_spectrum(series):
    """DC-removed Hann-window amplitude FFT of uniform event-rate samples."""
    uniform = (series.end_us - series.start_us) == series.bin_us
    samples = series.rate[uniform]
    if len(samples) < 8:
        raise ValueError("Frequency analysis needs at least eight complete bins.")
    window = np.hanning(len(samples))
    centered = samples - samples.mean()
    amplitude = 2 * np.abs(np.fft.rfft(centered * window)) / window.sum()
    amplitude[0] *= 0.5
    if len(samples) % 2 == 0:
        amplitude[-1] *= 0.5
    frequencies = np.fft.rfftfreq(len(samples), series.bin_us / 1e6)
    peaks = (
        np.flatnonzero(
            (amplitude[1:-1] > amplitude[:-2]) & (amplitude[1:-1] >= amplitude[2:])
        )
        + 1
    )
    peaks = sorted(peaks, key=lambda i: (-amplitude[i], frequencies[i]))[:5]
    return {
        "frequency_hz": frequencies,
        "amplitude_events_per_ms": amplitude,
        "peaks": [
            {"hz": float(frequencies[i]), "amplitude": float(amplitude[i])}
            for i in peaks
            if amplitude[i] > 1e-12
        ],
        "metadata": {
            **series.metadata,
            "algorithm": "DC removed, Hann-window real FFT",
            "complete_bins_used": len(samples),
            "partial_final_bin_discarded": bool(not uniform.all()),
            "sampling_hz": 1e6 / series.bin_us,
            "nyquist_hz": 0.5e6 / series.bin_us,
            "frequency_spacing_hz": 1e6 / series.bin_us / len(samples),
            "interpretation": "Event-rate periodicity; not a measurement of physical vibration.",
        },
    }
