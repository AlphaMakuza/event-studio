"""Enumerate compatible connected cameras without opening their streams.

Uses the local-source API documented in:
https://docs.prophesee.ai/stable/api/python/hal/bindings.html
"""

from dataclasses import dataclass
import importlib.util
from PySide6.QtCore import QThread, Signal


@dataclass(frozen=True)
class CameraInfo:
    serial: str
    label: str


@dataclass(frozen=True)
class DiscoveryResult:
    state: str  # ready (possibly zero cameras), unavailable, or error
    cameras: tuple = ()
    detail: str = ""


def sdk_available():
    try:
        return all(
            importlib.util.find_spec(name) is not None
            for name in ("metavision_core", "metavision_hal")
        )
    except (ImportError, ValueError, OSError):
        return False


def discover_cameras(discovery=None):
    if discovery is None:
        if not sdk_available():
            return DiscoveryResult(
                "unavailable",
                detail="Install the native Metavision SDK and a compatible camera driver to detect event cameras.",
            )
        try:
            from metavision_hal import DeviceDiscovery

            discovery = DeviceDiscovery
        except Exception as exc:
            return DiscoveryResult(
                "unavailable", detail=f"Camera support could not load: {exc}"
            )
    try:
        # Do not open every device to identify it: that can interrupt another
        # application or take ownership of a camera before the user selects it.
        serials = sorted(
            {str(serial) for serial in discovery.list_local() if str(serial)}
        )
        cameras = []
        for serial in serials:
            parts = serial.split(":")
            label = (
                f"{parts[-1]} ({' / '.join(parts[:-1])})"
                if len(parts) > 1
                else f"Event camera · {serial}"
            )
            cameras.append(CameraInfo(serial, label))
        return DiscoveryResult("ready", tuple(cameras))
    except Exception as exc:
        return DiscoveryResult("error", detail=f"Camera detection failed: {exc}")


class DiscoveryWorker(QThread):
    found = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        self.found.emit(discover_cameras())
