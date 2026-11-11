"""A consistent Phosphor icon family for studio controls."""
from functools import lru_cache
import qtawesome as qta
from PySide6.QtWidgets import QPushButton


@lru_cache(maxsize=128)
def icon(name, color="#dceaf3"):
    return qta.icon(f"ph.{name}", color=color, color_disabled="#596779")


class StudioButton(QPushButton):
    """Keep stateful controls such as Play/Pause in sync with their icon."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from .theme import appearance_controller
        appearance_controller().decorate(self)

    def setText(self, text):
        super().setText(text)
        from .theme import appearance_controller
        appearance_controller().decorate(self)


def control_icon(text):
    text = text.replace("&", "").strip().lower()
    exact = {
        "play": "play", "pause": "pause", "stop": "stop",
        "step back": "skip-back", "step forward": "skip-forward",
        "local projects": "folders", "+  new project": "plus",
        "new project": "plus", "...": "dots-three", "…": "dots-three",
        "undo": "arrow-counter-clockwise", "redo": "arrow-clockwise",
        "full timeline": "arrows-left-right", "apply interval": "check",
        "zoom to interval": "magnifying-glass-plus", "reset view": "arrows-out",
        "connect": "link-simple", "close": "x", "hide": "eye-slash",
        "raw spatial": "dots-nine", "time-colored": "palette",
        "open roi analysis": "chart-line", "hide roi analysis": "eye-slash",
        "open activity plot": "chart-line", "open spatial plot": "dots-nine",
    }
    if text in exact:
        return exact[text]
    for prefix, name in (
        ("refresh", "arrows-clockwise"), ("live camera", "video-camera"),
        ("import", "download-simple"), ("open", "folder-open"),
        ("export", "upload-simple"), ("save", "floppy-disk"),
        ("load", "folder-open"), ("rename", "pencil-simple"),
        ("delete", "trash"), ("remove", "minus"), ("clear", "eraser"),
        ("add", "plus"), ("new", "plus"), ("set color", "palette"),
        ("set sensor", "bounding-box"), ("advanced analysis", "chart-line"),
        ("compare", "columns"), ("recording quality", "heartbeat"),
        ("run diagnostics", "heartbeat"), ("batch", "stack"),
        ("record", "record"), ("jump", "arrow-line-right"),
        ("loop", "repeat"), ("use current", "selection"),
        ("use exact", "selection"), ("show roi", "bounding-box"),
        ("convert", "arrows-left-right"),
    ):
        if text.startswith(prefix):
            return name
    return None
