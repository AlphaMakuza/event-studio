"""Live RAW inspection; the bounded display buffer is never a full recording."""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QFileDialog,
    QInputDialog,
)
from .acquisition import EventBuffer, CameraWorker, sdk_available
from .roi_label import ROILabel
from .rendering import raw
from .viewer import compute_roi_stats


class LiveWindow(QWidget):
    def __init__(self, owner):
        super().__init__(owner, Qt.Window)
        self.setWindowTitle("Live acquisition • RAW")
        self.resize(1000, 760)
        self.worker = None
        self.hw = None
        self.buffer = None
        self.probes = []
        self.candidate = None
        self.last_received = 0
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.serial = QLineEdit()
        self.serial.setPlaceholderText("Camera serial (blank = first camera)")
        row.addWidget(self.serial)
        self.capacity = QSpinBox()
        self.capacity.setRange(1000, 10_000_000)
        self.capacity.setValue(1_000_000)
        self.capacity.setSuffix(" buffered events")
        row.addWidget(self.capacity)
        self.window = QSpinBox()
        self.window.setRange(1, 60000)
        self.window.setValue(50)
        self.window.setSuffix(" ms")
        row.addWidget(self.window)
        self.start = QPushButton("Connect")
        self.start.clicked.connect(self.connect_camera)
        row.addWidget(self.start)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(self.stop_camera)
        row.addWidget(self.stop)
        self.record = QPushButton("Record CSV on next connection")
        self.record.clicked.connect(self.choose_recording)
        layout.addWidget(self.record)
        self.record_path = None
        self.status = QLabel(
            "Metavision Python SDK not installed in this Python environment."
            if not sdk_available()
            else "Ready. A compatible SDK, driver and camera are required."
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.start.setEnabled(sdk_available())
        self.view = ROILabel()
        self.view.setMinimumSize(400, 400)
        self.view.roiChanged.connect(self.candidate_changed)
        layout.addWidget(self.view, 1)
        add = QPushButton("Add live ROI from candidate")
        add.clicked.connect(self.add_roi)
        layout.addWidget(add)
        self.statistics = QLabel(
            "Display-buffer evictions and hardware losses are different. Hardware losses are unknown."
        )
        self.statistics.setWordWrap(True)
        layout.addWidget(self.statistics)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(33)
        self.window.valueChanged.connect(self.invalidate_view)

    def invalidate_view(self):
        self.last_received = -1

    def choose_recording(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "New live recording", "capture.csv", "CSV (*.csv)"
        )
        if path:
            self.record_path = path
            self.record.setText("Next capture: " + path)

    def connect_camera(self):
        if self.worker is not None:
            return
        self.buffer = EventBuffer(self.capacity.value())
        self.last_received = 0
        self.probes = []
        self.view.set_rois([])
        self.hw = None
        self.worker = CameraWorker(
            self.buffer, self.serial.text().strip(), self.record_path, parent=self
        )
        self.worker.geometry.connect(self.set_geometry)
        self.worker.status.connect(self.status.setText)
        self.worker.failed.connect(self.status.setText)
        self.worker.finished.connect(self.finished)
        self.start.setEnabled(False)
        self.record.setEnabled(False)
        self.serial.setEnabled(False)
        self.capacity.setEnabled(False)
        self.worker.start()

    def set_geometry(self, height, width):
        self.hw = (height, width)

    def stop_camera(self):
        if self.worker is not None:
            self.status.setText("Stopping at the next SDK delivery…")
            self.worker.requestInterruption()

    def finished(self):
        self.refresh()
        self.worker.deleteLater()
        self.worker = None
        self.start.setEnabled(sdk_available())
        self.record.setEnabled(True)
        self.serial.setEnabled(True)
        self.capacity.setEnabled(True)
        self.record_path = None
        self.record.setText("Record CSV on next connection")

    def candidate_changed(self, roi):
        self.candidate = roi

    def add_roi(self):
        if self.candidate is None:
            return
        name, ok = QInputDialog.getText(self, "Live ROI", "Probe name:")
        if ok:
            self.probes.append(
                (name.strip() or f"ROI {len(self.probes)+1}", self.candidate)
            )
            self.view.set_rois([(roi, "#64d2ff") for name, roi in self.probes])
            self.view.clear_roi()
            self.last_received = -1

    def refresh(self):
        if (
            self.hw is None
            or self.buffer is None
            or self.buffer.received == self.last_received
        ):
            return
        batch = self.buffer.snapshot(self.hw)
        if batch is None:
            return
        self.last_received = self.buffer.received
        end = int(batch.t[-1]) + 1
        start = max(int(batch.t[0]), end - self.window.value() * 1000)
        self.view.set_frame(raw(batch, self.hw, start, end))
        from .science import select

        count = len(select(batch, start, end).t)
        lines = [
            f"RAW • [{start}, {end}) µs | {count:,} events | {count*1000/max(1,end-start):.3f} ev/ms",
            f'Received: {batch.metadata["received_events"]:,} | Display-buffer evictions: {batch.metadata["display_buffer_evicted_events"]:,} | Hardware losses: UNKNOWN',
        ]
        for name, roi in self.probes:
            stats = compute_roi_stats(batch, self.hw, roi, start, end - start)
            lines.append(
                f"{name}: {stats.n_events:,} events | {stats.events_per_ms:.3f} ev/ms | + {stats.pos:,} / − {stats.neg:,}"
            )
        self.statistics.setText("\n".join(lines))

    def closeEvent(self, event):
        if self.worker is not None:
            self.stop_camera()
            event.ignore()
            return
        super().closeEvent(event)
