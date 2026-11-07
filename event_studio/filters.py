"""Explicit non-destructive event filters; all thresholds are recorded."""

from dataclasses import dataclass, asdict, replace
import math
import numpy as np


class CancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class FilterSettings:
    refractory_us: int = 0
    support_us: int = 0
    hot_pixel_events_per_ms: float = 0.0

    def validate(self):
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (self.refractory_us, self.support_us)
        ):
            raise ValueError(
                "Filter time thresholds must be nonnegative integer microseconds."
            )
        if (
            not math.isfinite(self.hot_pixel_events_per_ms)
            or self.hot_pixel_events_per_ms < 0
        ):
            raise ValueError("Hot-pixel threshold must be finite and nonnegative.")


def apply_filters(
    events, settings=None, cancelled=lambda: False, progress=lambda n, message: None
):
    config = FilterSettings(**(settings or {}))
    config.validate()
    if not any(asdict(config).values()):
        return events
    n = len(events.t)
    if not n:
        return events
    if not events.metadata.get("sorted", False) and np.any(
        events.t[1:] < events.t[:-1]
    ):
        raise ValueError("Temporal filters require nondecreasing source timestamps.")
    width = int(events.metadata.get("resolution", [int(events.x.max()) + 1])[0])
    packed = events.y.astype(np.int64) * width + events.x
    keep = np.ones(n, dtype=bool)
    if config.hot_pixel_events_per_ms:
        pixels, counts = np.unique(packed, return_counts=True)
        duration_ms = (int(events.t[-1]) - int(events.t[0]) + 1) / 1000
        hot = pixels[counts / duration_ms > config.hot_pixel_events_per_ms]
        keep &= ~np.isin(packed, hot)
    if config.refractory_us or config.support_us:
        retained, seen = {}, {}
        for i in range(n):
            if i % 16384 == 0:
                if cancelled():
                    raise CancelledError(
                        "Filtering cancelled; source data was not changed."
                    )
                progress(int(100 * i / max(1, n)), "Filtering original events")
            t, x, y, pixel = (
                int(events.t[i]),
                int(events.x[i]),
                int(events.y[i]),
                int(packed[i]),
            )
            supported = True
            if config.support_us:
                supported = any(
                    0 <= t - seen.get((x + dx, y + dy), -(10**30)) <= config.support_us
                    for dy in (-1, 0, 1)
                    for dx in (-1, 0, 1)
                    if (dx or dy) and x + dx >= 0 and y + dy >= 0
                )
                # Support uses prior raw events, including rejected ones; no look-ahead.
                seen[(x, y)] = t
            accepted = (
                bool(keep[i])
                and supported
                and (
                    not config.refractory_us
                    or t - retained.get(pixel, -(10**30)) >= config.refractory_us
                )
            )
            keep[i] = accepted
            if accepted:
                retained[pixel] = t
    if cancelled():
        raise CancelledError("Filtering cancelled.")
    batch = replace(
        events,
        t=events.t[keep],
        x=events.x[keep],
        y=events.y[keep],
        p=events.p[keep],
        metadata={
            **events.metadata,
            "filters": asdict(config),
            "raw_event_count": n,
            "retained_event_count": int(keep.sum()),
            "classification": "DERIVED",
            "filter_method": "hot-pixel whole-recording rate; refractory since last retained event; prior raw 3x3 neighbor support",
        },
    )
    for array in (batch.t, batch.x, batch.y, batch.p):
        array.flags.writeable = False
    return batch
