"""Optional Metavision acquisition, isolated from GUI rendering and raw recordings.

Adapter contract: https://docs.prophesee.ai/stable/api/python/core/event_io.html
The SDK is not bundled. Hardware drop counts are unknown unless an SDK exposes
them; buffer evictions below are only application display-buffer measurements.
"""

from collections import deque
from threading import Lock
from pathlib import Path
import csv
import importlib.util
import numpy as np
from PySide6.QtCore import QThread, Signal
from .viewer import EventBatch
from .project_utils import save_json
from .science import fingerprint
from .version import __version__


def sdk_available():
    return importlib.util.find_spec("metavision_core") is not None


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

    def snapshot(self, hw):
        with self.lock:
            batches = list(self.batches)
            evicted, received = self.evicted, self.received
        if not batches:
            return None
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
            },
        )


class CameraWorker(QThread):
    geometry = Signal(int, int)
    status = Signal(str)
    failed = Signal(str)

    def __init__(
        self, buffer, serial="", record_path=None, iterator_factory=None, parent=None
    ):
        super().__init__(parent)
        self.buffer = buffer
        self.serial = serial
        self.record_path = Path(record_path) if record_path else None
        self.iterator_factory = iterator_factory

    def run(self):
        stream = None
        written = 0
        hw = None
        failure = None
        iterator = None
        try:
            if self.record_path:
                if self.record_path.suffix.lower() != ".csv":
                    raise ValueError("Live recording requires a .csv filename.")
                if self.record_path.with_suffix(".json").exists():
                    raise FileExistsError("Recording metadata already exists.")
                self.record_path.parent.mkdir(parents=True, exist_ok=True)
                stream = self.record_path.open("x", encoding="utf-8", newline="")
                writer = csv.writer(stream)
                writer.writerow(("t", "x", "y", "p"))
            if self.iterator_factory:
                iterator = self.iterator_factory()
            else:
                from metavision_core.event_io import EventsIterator

                iterator = EventsIterator(
                    input_path=self.serial, delta_t=10000, relative_timestamps=False
                )
            hw = iterator.get_size()
            if (
                not all(isinstance(value, int) and value > 0 for value in hw)
                or hw[0] * hw[1] > 16_777_216
            ):
                raise ValueError("Camera did not report supported sensor dimensions.")
            self.geometry.emit(*hw)
            self.status.emit("Acquiring • hardware drop count unknown")
            for batch in iterator:
                if self.isInterruptionRequested():
                    break
                if not len(batch):
                    continue
                if np.any(batch["x"] >= hw[1]) or np.any(batch["y"] >= hw[0]):
                    raise ValueError(
                        "Camera event coordinates exceed its sensor dimensions."
                    )
                self.buffer.push(batch)
                if stream:
                    writer.writerows(
                        zip(batch["t"], batch["x"], batch["y"], batch["p"])
                    )
                    written += len(batch)
            self.status.emit(
                "Stopped"
                if self.isInterruptionRequested()
                else "Source ended / disconnected"
            )
        except Exception as exc:
            failure = str(exc)
            self.failed.emit(failure)
        finally:
            # Release the SDK/device in the acquisition thread, not the GUI.
            if iterator is not None:
                del iterator
            if stream:
                stream.close()
                try:
                    save_json(
                        self.record_path.with_suffix(".json"),
                        {
                            "software_version": __version__,
                            "acquisition": {
                                "adapter": "Metavision EventsIterator",
                                "serial": self.serial,
                                "timestamp_unit": "us",
                                "timestamps_rebased": False,
                                "received_events": self.buffer.received,
                                "recorded_rows_lower_bound": written,
                                "hardware_dropped_events": None,
                                "display_buffer_evicted_events": self.buffer.evicted,
                                "status": (
                                    "failed"
                                    if failure
                                    else (
                                        "stopped"
                                        if self.isInterruptionRequested()
                                        else "source ended"
                                    )
                                ),
                                "error": failure,
                                "loss_claim": "No claim of zero acquisition loss; SDK/hardware losses are not measured.",
                            },
                            "sensor_resolution": (
                                {
                                    "width": hw[1],
                                    "height": hw[0],
                                    "origin": "camera SDK",
                                }
                                if hw
                                else {}
                            ),
                            "csv_sha256": fingerprint(self.record_path),
                        },
                    )
                except Exception as exc:
                    self.failed.emit(f"Recording metadata failed: {exc}")
