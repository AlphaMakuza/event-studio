"""Run blocking import work outside Qt's GUI thread."""
from PySide6.QtCore import QThread, Signal


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)
    cancelled = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:
            from .filters import CancelledError
            if isinstance(exc,CancelledError):
                self.cancelled.emit(str(exc))
            else:
                self.failed.emit(str(exc))
