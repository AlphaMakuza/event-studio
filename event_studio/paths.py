"""Writable storage stays outside the installation directory in packaged builds."""
import os
from pathlib import Path
import sys


def storage_root() -> Path:
    override = os.environ.get("EVENT_STUDIO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        from PySide6.QtCore import QStandardPaths
        return Path(QStandardPaths.writableLocation(QStandardPaths.GenericDataLocation)) / "Event-Based Studio"
    return Path(__file__).resolve().parents[1]
