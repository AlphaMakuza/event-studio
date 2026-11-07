"""Small public offline analysis API. All time bounds are integer microseconds."""

from dataclasses import dataclass
from pathlib import Path
from .science import load_csv, select, export_csv
from .viewer import infer_hw, compute_roi_stats
from .roi_label import Roi
from .activity import activity_series, detect_bursts, frequency_spectrum
from .filters import apply_filters
from .motion import track_motion
from .version import __version__


@dataclass(frozen=True)
class Recording:
    events: object

    @classmethod
    def open(cls, path):
        return cls(load_csv(Path(path)))

    @property
    def resolution(self):
        """(height, width), with provenance in events.metadata."""
        return infer_hw(self.events)

    def query(self, start_us=None, end_us=None, roi=None, polarity="both"):
        return select(self.events, start_us, end_us, roi, polarity)

    def statistics(self, start_us, end_us, roi=None, polarity="both"):
        if end_us <= start_us:
            raise ValueError("Statistics require a nonempty half-open interval.")
        h, w = self.resolution
        return compute_roi_stats(
            self.query(start_us, end_us, polarity=polarity),
            self.resolution,
            roi or Roi(0, 0, w, h),
            start_us,
            end_us - start_us,
        )

    def activity(self, start_us, end_us, bin_us=1000, roi=None, polarity="both"):
        return activity_series(self.events, start_us, end_us, bin_us, roi, polarity)

    def filtered(self, **parameters):
        return Recording(apply_filters(self.events, parameters))

    def motion(self, start_us, end_us, **parameters):
        return track_motion(
            self.events, self.resolution, start_us, end_us, **parameters
        )

    def export(self, path, **selection):
        return export_csv(path, self.events, self.resolution, **selection)


__all__ = [
    "Recording",
    "Roi",
    "activity_series",
    "detect_bursts",
    "frequency_spectrum",
    "__version__",
]
