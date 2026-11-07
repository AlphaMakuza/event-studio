"""Raw CSV capture lifecycle, independent of the selected live visualization."""

from pathlib import Path
import csv
from .project_utils import save_json
from .science import fingerprint
from .version import __version__


class CaptureRecording:
    def __init__(self, path, serial, hw, received_at_start):
        self.path = Path(path)
        if self.path.suffix.lower() != ".csv":
            raise ValueError("Choose a .csv filename for the recording.")
        if self.path.with_suffix(".json").exists():
            raise FileExistsError(
                "Recording metadata already exists. Choose a new filename."
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open("x", encoding="utf-8", newline="")
        self.writer = csv.writer(self.stream)
        self.writer.writerow(("t", "x", "y", "p"))
        self.serial, self.hw = serial, hw
        self.received_at_start = received_at_start
        self.written = 0
        self.first_t = self.last_t = None

    def write(self, batch):
        self.writer.writerows(zip(batch["t"], batch["x"], batch["y"], batch["p"]))
        self.written += len(batch)
        if len(batch):
            if self.first_t is None:
                self.first_t = int(batch["t"][0])
            self.last_t = int(batch["t"][-1])

    def close(self, status, buffer, error=None):
        self.stream.close()
        save_json(
            self.path.with_suffix(".json"),
            {
                "software_version": __version__,
                "acquisition": {
                    "adapter": "Metavision EventsIterator",
                    "serial": self.serial,
                    "timestamp_unit": "us",
                    "timestamps_rebased": False,
                    "received_events": buffer.received,
                    "received_events_at_recording_start": self.received_at_start,
                    "recorded_rows_lower_bound": self.written,
                    "first_timestamp_us": self.first_t,
                    "last_timestamp_us": self.last_t,
                    "hardware_dropped_events": None,
                    "display_buffer_evicted_events": buffer.evicted,
                    "status": status,
                    "error": error,
                    "loss_claim": "No claim of zero acquisition loss; SDK/hardware losses are not measured.",
                },
                "sensor_resolution": {
                    "width": self.hw[1],
                    "height": self.hw[0],
                    "origin": "camera SDK",
                },
                "csv_sha256": fingerprint(self.path),
            },
        )
