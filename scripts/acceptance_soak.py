"""Run sustained simulated acquisition through the actual Qt live window.

python -m scripts.acceptance_soak --seconds 120 --output artifacts/acceptance/soak.json
This measures application behavior; it cannot certify a physical camera/driver.
"""

import argparse
from collections import Counter
import ctypes
import faulthandler
import json
import os
from pathlib import Path
import statistics
import tempfile
import time
from unittest.mock import patch
import numpy as np


def private_bytes():
    if os.name != "nt":
        return None
    size = ctypes.c_size_t

    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, size)
            for name in (
                "peak_working",
                "working",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "pagefile",
                "peak_pagefile",
                "private",
            )
        ]

    value = Counters()
    value.cb = ctypes.sizeof(value)
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    function = ctypes.windll.psapi.GetProcessMemoryInfo
    function.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    if function(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb):
        return int(value.private)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=120)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/acceptance/soak.json")
    )
    parser.add_argument(
        "--native",
        action="store_true",
        help="Use the Windows Qt platform instead of offscreen.",
    )
    args = parser.parse_args()
    if args.seconds < 5:
        parser.error("Run at least five seconds.")
    os.environ.setdefault("QT_QPA_PLATFORM", "windows" if args.native else "offscreen")
    from PySide6.QtCore import QEventLoop, QThread, QTimer
    from PySide6.QtWidgets import QApplication
    from event_studio.acquisition import CameraWorker
    from event_studio.camera_discovery import CameraInfo, DiscoveryResult
    from event_studio.live_preview import LIVE_MODES
    from event_studio.live_window import LiveWindow
    from event_studio.theme import configure_application
    from event_studio.viewer import load_events_from_csv
    from event_studio.version import __version__

    args.output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    result = {
        "software_version": __version__,
        "kind": "simulated capture; not hardware validation",
        "requested_seconds": args.seconds,
        "qt_platform": app.platformName(),
        "errors": [],
    }
    frames = Counter()
    render_times = []
    heartbeats = []
    samples = []
    max_buffer = 0
    max_pending = 0
    history_limited = False
    with tempfile.TemporaryDirectory(
        prefix="soak-data-", dir=args.output.parent
    ) as directory:
        recording = Path(directory) / "capture.csv"

        class Source:
            def get_size(self):
                return (240, 320)

            def __iter__(self):
                for index in range(10_000_000):
                    QThread.msleep(10)
                    values = np.arange(2048)
                    batch = np.zeros(
                        2048, dtype=[("t", "i8"), ("x", "i4"), ("y", "i4"), ("p", "i1")]
                    )
                    batch["t"] = index * 10000 + values * 4
                    batch["x"] = (values + index * 3) % 320
                    batch["y"] = (values // 320 + index // 3) % 240
                    batch["p"] = values % 2
                    yield batch

        class Window(LiveWindow):
            def apply_preview(self, payload):
                nonlocal history_limited
                super().apply_preview(payload)
                if self._last_result is payload:
                    frames[payload["mode"]] += 1
                    render_times.append(payload["render_ms"])
                    history_limited |= payload["history_limited"]

        window = Window(None)
        window.capacity.setValue(100000)
        window.persistence.setValue(750)
        camera_result = DiscoveryResult(
            "ready", (CameraInfo("simulation", "SIMULATED ACCEPTANCE SOURCE"),)
        )

        def worker(buffer, serial, parent):
            return CameraWorker(
                buffer,
                serial,
                record_path=recording,
                iterator_factory=Source,
                parent=parent,
            )

        loop = QEventLoop()
        window.closed.connect(loop.quit)
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: heartbeats.append(time.monotonic()))
        elapsed_timer = QTimer()
        elapsed_timer.setInterval(100)
        started = time.monotonic()
        record_stop_sent = False
        last_mode = None
        last_print = -1
        last_sample = -1

        def tick():
            nonlocal max_buffer, max_pending, record_stop_sent, last_mode, last_print, last_sample
            elapsed = time.monotonic() - started
            try:
                if window.buffer is not None:
                    max_buffer = max(max_buffer, window.buffer.size)
                if window.preview_worker is not None:
                    max_pending = max(
                        max_pending, int(window.preview_worker.pending is not None)
                    )
                if int(elapsed) != last_sample:
                    samples.append(
                        {"seconds": round(elapsed, 2), "private_bytes": private_bytes()}
                    )
                    last_sample = int(elapsed)
                if int(elapsed) // 15 != last_print:
                    print(
                        f"Soak: {elapsed:.1f}s, received={window.buffer.received if window.buffer else 0:,}, preview_frames={sum(frames.values()):,}",
                        flush=True,
                    )
                    last_print = int(elapsed) // 15
                if (
                    elapsed >= min(10, args.seconds / 3)
                    and not record_stop_sent
                    and window.worker is not None
                ):
                    window.worker.request_recording()
                    record_stop_sent = True
                mode = LIVE_MODES[
                    int(elapsed / max(1, args.seconds / 12)) % len(LIVE_MODES)
                ]
                if mode != last_mode:
                    window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
                    last_mode = mode
                if elapsed >= args.seconds:
                    elapsed_timer.stop()
                    window.close()
            except Exception as exc:
                result["errors"].append(str(exc))
                elapsed_timer.stop()
                window.close()

        elapsed_timer.timeout.connect(tick)
        faulthandler.dump_traceback_later(int(args.seconds + 45), exit=True)
        with patch(
            "event_studio.camera_discovery.discover_cameras", return_value=camera_result
        ), patch("event_studio.live_window.CameraWorker", side_effect=worker):
            heartbeat.start()
            elapsed_timer.start()
            window.show()
            loop.exec()
            heartbeat.stop()
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            faulthandler.cancel_dump_traceback_later()
            if (
                window.worker is not None
                or window.discovery_worker is not None
                or window.preview_worker is not None
            ):
                raise RuntimeError("Live window closed with unfinished worker threads.")
            result["received_events"] = window.buffer.received if window.buffer else 0
            result["display_evictions"] = window.buffer.evicted if window.buffer else 0
            result["preview_frames_by_mode"] = dict(frames)
            result["maximum_retained_events"] = max_buffer
            result["buffer_capacity"] = 100000
            result["maximum_pending_previews"] = max_pending
            result["history_limit_warning_exercised"] = history_limited
            result["maximum_heartbeat_gap_ms"] = (
                round(max(np.diff(heartbeats)) * 1000, 3)
                if len(heartbeats) > 1
                else None
            )
            result["render_ms_percentiles"] = (
                {
                    str(p): round(float(np.percentile(render_times, p)), 3)
                    for p in (50, 95, 100)
                }
                if render_times
                else {}
            )
            result["memory_samples"] = samples
            steady = [
                s["private_bytes"]
                for s in samples
                if s["seconds"] >= min(15, args.seconds / 3)
                and s["private_bytes"] is not None
            ]
            if steady:
                window_size = min(10, max(1, len(steady) // 3))
                result["steady_memory_growth_mib"] = round(
                    (
                        statistics.median(steady[-window_size:])
                        - statistics.median(steady[:window_size])
                    )
                    / 1024**2,
                    3,
                )
            captured = load_events_from_csv(recording)
            expected = np.concatenate(
                [
                    i * 10000 + np.arange(2048) * 4
                    for i in range(len(captured.t) // 2048)
                ]
            )
            result["recorded_events"] = len(captured.t)
            result["recorded_timestamps_exact"] = bool(
                np.array_equal(captured.t, expected)
            )
            result["recorded_polarity_preserved"] = set(np.unique(captured.p)) == {0, 1}
            result["hardware_dropped_events"] = captured.metadata["acquisition"][
                "hardware_dropped_events"
            ]
            result["checks"] = {
                "bounded_event_buffer": max_buffer <= 100000,
                "bounded_preview_queue": max_pending <= 1,
                "all_views_exercised": all(frames[mode] > 0 for mode in LIVE_MODES),
                "recording_integrity": result["recorded_timestamps_exact"]
                and result["recorded_polarity_preserved"],
                "workers_closed_cleanly": True,
                "steady_memory_below_128_mib_growth": result.get(
                    "steady_memory_growth_mib", 0
                )
                < 128,
                "no_operation_errors": not result["errors"],
            }
    result["passed"] = all(result["checks"].values())
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "memory_samples"},
            indent=2,
        ),
        flush=True,
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
