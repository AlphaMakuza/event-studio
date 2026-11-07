"""Bounded latest-request preview rendering; no Qt widget access in this thread."""

from dataclasses import dataclass
from threading import Condition
import time
from PySide6.QtCore import QThread, Signal
from .rendering import render_frame, raw
from .science import select
from .viewer import compute_roi_stats

LIVE_MODES = (
    "RAW",
    "HEATMAP",
    "PERSISTENCE TRAILS",
    "POLARITY GLOW",
    "TRAIL",
    "MOTION ARROWS",
)


@dataclass(frozen=True)
class PreviewRequest:
    epoch: int
    revision: int
    buffer: object
    hw: tuple
    mode: str
    window_us: int
    parameters: dict
    probes: tuple = ()  # (name, Roi, color)
    compare: bool = False
    live: bool = True


def render_preview(request, now=None):
    started = time.monotonic()
    if request.mode not in LIVE_MODES or request.window_us < 1:
        raise ValueError("Unsupported live view or accumulation window.")
    history_us = max(
        request.window_us,
        (
            request.parameters.get("persistence_us", 100000)
            if request.mode == "PERSISTENCE TRAILS"
            else request.window_us
        ),
    )
    batch = request.buffer.snapshot(request.hw, lookback_us=history_us)
    if batch is None:
        return None
    device_end = batch.metadata["buffer_end_us"]
    elapsed = (
        max(
            0,
            (time.monotonic() if now is None else now)
            - batch.metadata["last_delivery_monotonic"],
        )
        if request.live
        else 0
    )
    # Presentation time only: during quiet periods host elapsed time lets
    # events expire/fade. Original event and recording timestamps never change.
    end = device_end + int(elapsed * 1e6)
    start = max(batch.metadata["buffer_start_us"], end - request.window_us)
    image = render_frame(
        batch, request.hw, start, end - start, request.mode, request.parameters
    )
    comparison = raw(batch, request.hw, start, end) if request.compare else None
    selected = select(
        batch, start, end, polarity=request.parameters.get("polarity", "both")
    )
    positive = int((selected.p > 0).sum())
    rates = []
    for name, roi, color in request.probes:
        stats = compute_roi_stats(selected, request.hw, roi, start, end - start)
        rates.append(
            f"{name}: {stats.n_events:,} events | {stats.events_per_ms:.3f} ev/ms | + {stats.pos:,} / − {stats.neg:,}"
        )
    return {
        "epoch": request.epoch,
        "revision": request.revision,
        "image": image,
        "comparison": comparison,
        "start_us": start,
        "end_us": end,
        "latest_event_us": device_end - 1,
        "received": batch.metadata["received_events"],
        "evicted": batch.metadata["display_buffer_evicted_events"],
        "events": len(selected.t),
        "positive": positive,
        "rate": len(selected.t) * 1000 / max(1, end - start),
        "probes": rates,
        "mode": request.mode,
        "history_limited": batch.metadata["display_buffer_evicted_events"] > 0
        and end - history_us < batch.metadata["buffer_start_us"],
        "render_ms": (time.monotonic() - started) * 1000,
        "host_elapsed_us": int(elapsed * 1e6),
    }


class PreviewWorker(QThread):
    rendered = Signal(object)
    failed = Signal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.condition = Condition()
        self.pending = None
        self.stopping = False
        self.coalesced = 0

    def submit(self, request):
        with self.condition:
            if self.stopping:
                return
            if self.pending is not None:
                self.coalesced += 1
            self.pending = request
            self.condition.notify()

    def stop(self):
        with self.condition:
            self.stopping = True
            self.pending = None
            self.condition.notify()

    def run(self):
        while True:
            with self.condition:
                while self.pending is None and not self.stopping:
                    self.condition.wait()
                if self.stopping:
                    return
                request, self.pending = self.pending, None
            try:
                result = render_preview(request)
                if result is not None and not self.stopping:
                    self.rendered.emit(result)
            except Exception as exc:
                if not self.stopping:
                    self.failed.emit(request.epoch, request.revision, str(exc))
