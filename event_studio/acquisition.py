"""Optional Metavision acquisition, isolated from GUI rendering and raw recordings.

Adapter contract: https://docs.prophesee.ai/stable/api/python/core/event_io.html
The SDK is not bundled. Hardware drop counts are unknown unless an SDK exposes
them; buffer evictions below are only application display-buffer measurements.
"""

from collections import deque
from threading import Lock
from pathlib import Path
from queue import Queue, Empty
import time
import numpy as np
from PySide6.QtCore import QThread, Signal
from .viewer import EventBatch
from .camera_discovery import sdk_available
from .capture_recording import CaptureRecording


class EventBuffer:
    def __init__(self, capacity=1_000_000):
        if capacity < 1:
            raise ValueError("Buffer capacity must be positive.")
        self.capacity = capacity
        self.batches = deque()
        self.size = 0
        self.evicted = 0
        self.received = 0
        self.last_t = None
        self.last_delivery = None
        self.lock = Lock()

    def push(self, structured):
        fields = [
            np.array(structured[key], dtype=dtype, copy=True)
            for key, dtype in (
                ("t", np.int64),
                ("x", np.int32),
                ("y", np.int32),
                ("p", np.int8),
            )
        ]
        if not len(fields[0]):
            return
        t, x, y, p = fields
        if (
            np.any(t[1:] < t[:-1])
            or t[0] < 0
            or np.any(x < 0)
            or np.any(y < 0)
            or not np.isin(p, [-1, 0, 1]).all()
        ):
            raise ValueError(
                "Camera delivered invalid events or decreasing timestamps."
            )
        for field in fields:
            field.flags.writeable = False
        batch = EventBatch(*fields)
        with self.lock:
            if self.last_t is not None and int(t[0]) < self.last_t:
                raise ValueError(
                    "Camera timestamp reset; capture stopped without rewriting timestamps."
                )
            self.last_t = int(t[-1])
            self.last_delivery = time.monotonic()
            self.received += len(t)
            self.batches.append(batch)
            self.size += len(t)
            while self.size > self.capacity:
                first = self.batches.popleft()
                excess = min(self.size - self.capacity, len(first.t))
                self.size -= excess
                self.evicted += excess
                if excess < len(first.t):
                    # Own only the retained suffix; a NumPy view would keep a
                    # potentially oversized SDK batch alive behind the buffer.
                    retained = [
                        getattr(first, key)[excess:].copy()
                        for key in ("t", "x", "y", "p")
                    ]
                    for array in retained:
                        array.flags.writeable = False
                    self.batches.appendleft(EventBatch(*retained))

    def snapshot(self, hw, lookback_us=None):
        with self.lock:
            batches = list(self.batches)
            evicted, received = self.evicted, self.received
            history_start = int(batches[0].t[0]) if batches else None
            history_end = self.last_t + 1 if self.last_t is not None else None
            last_delivery = self.last_delivery
        if not batches:
            return None
        if lookback_us is not None:
            if lookback_us < 1:
                raise ValueError("Preview history must be positive.")
            cutoff = history_end - lookback_us
            batches = [
                EventBatch(
                    *(
                        getattr(batch, key)[int(np.searchsorted(batch.t, cutoff)) :]
                        for key in ("t", "x", "y", "p")
                    )
                )
                for batch in batches
                if int(batch.t[-1]) >= cutoff
            ]
        arrays = [
            np.concatenate([getattr(batch, key) for batch in batches])
            for key in ("t", "x", "y", "p")
        ]
        for array in arrays:
            array.flags.writeable = False
        return EventBatch(
            *arrays,
            {
                "live": True,
                "complete": False,
                "sorted": True,
                "resolution": [hw[1], hw[0]],
                "resolution_origin": "camera SDK",
                "display_buffer_evicted_events": evicted,
                "received_events": received,
                "hardware_dropped_events": None,
                "buffer_start_us": history_start,
                "buffer_end_us": history_end,
                "last_delivery_monotonic": last_delivery,
            },
        )


class CameraWorker(QThread):
    geometry = Signal(int, int)
    status = Signal(str)
    failed = Signal(str)
    recording_changed = Signal(bool, str)
    recording_failed = Signal(str)

    def __init__(
        self, buffer, serial="", record_path=None, iterator_factory=None, parent=None
    ):
        super().__init__(parent)
        self.buffer = buffer
        self.serial = serial
        self.record_path = Path(record_path) if record_path else None
        self.iterator_factory = iterator_factory
        self.commands = Queue()
        self.error_message = None

    def request_recording(self, path=None):
        """Queue a recording start, or None to stop. File I/O stays in this thread."""
        self.commands.put(Path(path) if path else None)

    def run(self):
        recorder = None
        iterator = None
        hw = None
        failure = None

        def finish_recording(reason, error=None):
            nonlocal recorder
            if recorder is None:
                return
            current, recorder = recorder, None
            try:
                current.close(reason, self.buffer, error)
            except Exception as exc:
                self.recording_failed.emit(f"Recording could not be finalized: {exc}")
            finally:
                self.recording_changed.emit(False, str(current.path))

        def begin_recording(path):
            nonlocal recorder
            if recorder is not None:
                self.recording_failed.emit("A recording is already running.")
                return
            try:
                recorder = CaptureRecording(path, self.serial, hw, self.buffer.received)
                self.recording_changed.emit(True, str(recorder.path))
            except Exception as exc:
                self.recording_failed.emit(f"Recording could not start: {exc}")
                self.recording_changed.emit(False, str(path))

        try:
            if self.iterator_factory:
                iterator = self.iterator_factory()
            else:
                from metavision_core.event_io import EventsIterator

                iterator = EventsIterator(
                    input_path=self.serial, delta_t=10000, relative_timestamps=False
                )
            hw = iterator.get_size()
            if (
                not all(
                    isinstance(value, (int, np.integer)) and value > 0 for value in hw
                )
                or hw[0] * hw[1] > 16_777_216
            ):
                raise ValueError("Camera did not report supported sensor dimensions.")
            hw = tuple(map(int, hw))
            self.geometry.emit(*hw)
            if self.record_path:
                begin_recording(self.record_path)
            self.status.emit("Acquiring")
            for batch in iterator:
                if self.isInterruptionRequested():
                    break
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except Empty:
                        break
                    if command is None:
                        finish_recording("recording stopped")
                    else:
                        begin_recording(command)
                if not len(batch):
                    continue
                if np.any(batch["x"] >= hw[1]) or np.any(batch["y"] >= hw[0]):
                    raise ValueError(
                        "Camera event coordinates exceed its sensor dimensions."
                    )
                self.buffer.push(batch)
                if recorder is not None:
                    try:
                        recorder.write(batch)
                    except Exception as exc:
                        self.recording_failed.emit(f"Recording write failed: {exc}")
                        finish_recording("failed", str(exc))
            self.status.emit(
                "Stopped"
                if self.isInterruptionRequested()
                else "Camera stream ended or disconnected"
            )
        except Exception as exc:
            failure = self.error_message = str(exc)
            self.failed.emit(failure)
        finally:
            if iterator is not None:
                del iterator
            finish_recording(
                (
                    "failed"
                    if failure
                    else "stopped" if self.isInterruptionRequested() else "source ended"
                ),
                failure,
            )
