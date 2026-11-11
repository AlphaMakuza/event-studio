"""Device-first live preview with shared scientific/Studio renderers."""

from dataclasses import replace
from pathlib import Path
import time
import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QScrollArea,
    QFileDialog,
    QInputDialog,
    QListWidget,
    QApplication,
)
from .acquisition import EventBuffer, CameraWorker
from .camera_discovery import DiscoveryWorker, DiscoveryResult
from .live_preview import PreviewWorker, PreviewRequest
from .roi_label import ROILabel

MODE_CHOICES = (
    ("RAW - event polarity", "RAW"),
    ("Density heatmap", "HEATMAP"),
    ("Persistence trails", "PERSISTENCE TRAILS"),
    ("Polarity glow", "POLARITY GLOW"),
    ("Time-colored trail", "TRAIL"),
    ("Motion arrows", "MOTION ARROWS"),
)
MODE_DESCRIPTIONS = {
    "RAW": "RAW - positive orange, negative blue, mixed white; actual event presence.",
    "HEATMAP": "DERIVED - event density in the accumulation window; black is zero. Relative scales map the window peak to white; absolute white is 100 events/pixel.",
    "PERSISTENCE TRAILS": "DERIVED - latest actual event per pixel/polarity fades linearly over the persistence duration.",
    "POLARITY GLOW": "STYLIZED - polarity presence plus an adjustable 5x5 halo; halo pixels are styling, not events.",
    "TRAIL": "DERIVED - time-colored accumulated events; logarithmic scaling and relative normalization.",
    "MOTION ARROWS": "DERIVED - local pattern matches between half-windows. Ambiguous, stationary and inconsistent matches are omitted. This is an estimate, not calibrated optical flow.",
}


def show_live_camera():
    """One independent live window, shared by the browser and project editors."""
    app = QApplication.instance()
    window = getattr(app, "_event_studio_live_window", None)
    if window is None:
        window = LiveWindow(None)
        app._event_studio_live_window = window
    window.show()
    window.raise_()
    window.activateWindow()
    return window


class LiveWindow(QWidget):
    closed = Signal()

    def __init__(self, owner):
        super().__init__(owner, Qt.Window)
        from .theme import appearance_controller
        appearance_controller().watch_window(self)
        self.setWindowTitle("Event-Based Studio - Live Camera")
        self.resize(1320, 850)
        self.worker = self.discovery_worker = self.preview_worker = None
        self.hw = self.buffer = None
        self.probes = []
        self.candidate = None
        self._epoch = self._revision = 0
        self._active_serial = None
        self._pending_serial = None
        self._entries = ()
        self._discovery_state = "scanning"
        self._blocked_serials = set()
        self._preview_requested = True
        self._closing = False
        self._closed_emitted = False
        self._recording = False
        self._recording_pending = False
        self._recording_error_detail = None
        self._last_request = None
        self._last_result = None
        layout = QVBoxLayout(self)
        devices = QHBoxLayout()
        layout.addLayout(devices)
        devices.addWidget(QLabel("Camera"))
        self.camera_combo = QComboBox()
        self.camera_combo.setMinimumWidth(300)
        self.camera_combo.addItem("Looking for event cameras...", None)
        self.camera_combo.currentIndexChanged.connect(self.camera_changed)
        devices.addWidget(self.camera_combo, 1)
        self.refresh_button = QPushButton("Refresh cameras")
        self.refresh_button.clicked.connect(self.manual_scan)
        devices.addWidget(self.refresh_button)
        self.start = QPushButton("Connect")
        self.start.clicked.connect(self.connect_camera)
        devices.addWidget(self.start)
        self.stop = QPushButton("Stop")
        self.stop.clicked.connect(self.stop_camera)
        devices.addWidget(self.stop)
        self.record = QPushButton("Record...")
        self.record.clicked.connect(self.choose_recording)
        devices.addWidget(self.record)
        self.status = QLabel("Looking for connected event cameras...")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.status.setTextFormat(Qt.PlainText)
        self.recording_status = QLabel("")
        self.recording_status.setWordWrap(True)
        self.recording_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.recording_status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.recording_status)
        controls = QHBoxLayout()
        layout.addLayout(controls)
        controls.addWidget(QLabel("View"))
        self.mode_combo = QComboBox()
        for label, mode in MODE_CHOICES:
            self.mode_combo.addItem(label, mode)
        self.mode_combo.currentIndexChanged.connect(self.view_changed)
        controls.addWidget(self.mode_combo)
        self.polarity = QComboBox()
        for label, value in (
            ("Both polarities", "both"),
            ("Positive only", "pos"),
            ("Negative only", "neg"),
        ):
            self.polarity.addItem(label, value)
        self.polarity.currentIndexChanged.connect(self.invalidate_view)
        controls.addWidget(self.polarity)
        controls.addWidget(QLabel("Accumulation"))
        self.window = QSpinBox()
        self.window.setRange(1, 60000)
        self.window.setValue(50)
        self.window.setSuffix(" ms")
        self.window.valueChanged.connect(self.invalidate_view)
        controls.addWidget(self.window)
        self.compare_check = QCheckBox("Compare with unfiltered RAW")
        self.compare_check.toggled.connect(self.toggle_comparison)
        controls.addWidget(self.compare_check)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        body = QHBoxLayout()
        layout.addLayout(body, 1)
        self.compare_box = QGroupBox("RAW - unfiltered reference")
        compare_layout = QVBoxLayout(self.compare_box)
        self.compare_view = ROILabel()
        self.compare_view.setMinimumSize(300, 300)
        compare_layout.addWidget(self.compare_view)
        self.compare_box.hide()
        body.addWidget(self.compare_box, 3)
        self.view_box = QGroupBox("RAW - live preview")
        view_layout = QVBoxLayout(self.view_box)
        self.view = ROILabel()
        self.view.setMinimumSize(400, 350)
        view_layout.addWidget(self.view)
        body.addWidget(self.view_box, 3)
        for viewer in (self.view, self.compare_view):
            viewer.roiChanged.connect(self.candidate_changed)
            viewer.roiMoved.connect(self.roi_moved)
        sidebar = QWidget()
        side = QVBoxLayout(sidebar)
        self.mode_settings = QGroupBox("View controls")
        mode_form = QFormLayout(self.mode_settings)
        self._mode_rows = []
        self.persistence = self.number(1, 60000, 100)
        self.persistence.setSuffix(" ms")
        self.mode_row(
            mode_form, "Persistence", self.persistence, ("PERSISTENCE TRAILS",)
        )
        self.glow = self.number(0, 3, 0.7)
        self.mode_row(mode_form, "Glow intensity", self.glow, ("POLARITY GLOW",))
        self.heat_scale = QComboBox()
        self.heat_scale.addItems(
            ["Log relative", "Linear relative", "Absolute (100 events/pixel)"]
        )
        self.mode_row(mode_form, "Normalization", self.heat_scale, ("HEATMAP",))
        self.spacing = QSpinBox()
        self.spacing.setRange(8, 128)
        self.spacing.setValue(24)
        self.mode_row(mode_form, "Arrow spacing px", self.spacing, ("MOTION ARROWS",))
        self.arrow_scale = self.number(0.2, 10, 1)
        self.mode_row(
            mode_form, "Display multiplier", self.arrow_scale, ("MOTION ARROWS",)
        )
        self.arrow_quality = self.number(0, 1, 0.65)
        self.mode_row(
            mode_form, "Match quality", self.arrow_quality, ("MOTION ARROWS",)
        )
        self.minimum = QSpinBox()
        self.minimum.setRange(1, 500)
        self.minimum.setValue(10)
        self.mode_row(mode_form, "Minimum events", self.minimum, ("MOTION ARROWS",))
        self.silhouette = self.number(0, 1, 0.4)
        self.mode_row(
            mode_form, "Backdrop intensity", self.silhouette, ("MOTION ARROWS",)
        )
        for widget in (
            self.persistence,
            self.glow,
            self.spacing,
            self.arrow_scale,
            self.arrow_quality,
            self.minimum,
            self.silhouette,
        ):
            widget.valueChanged.connect(self.invalidate_view)
        self.heat_scale.currentIndexChanged.connect(self.invalidate_view)
        side.addWidget(self.mode_settings)
        roi_box = QGroupBox("Live ROI probes")
        roi_layout = QVBoxLayout(roi_box)
        help_text = QLabel(
            "Drag a rectangle on either image, then add a named probe. Select a probe to move or resize it."
        )
        help_text.setWordWrap(True)
        roi_layout.addWidget(help_text)
        self.roi_list = QListWidget()
        self.roi_list.setMaximumHeight(160)
        self.roi_list.currentRowChanged.connect(self.push_rois)
        roi_layout.addWidget(self.roi_list)
        add = QPushButton("Add probe")
        add.clicked.connect(self.add_roi)
        roi_layout.addWidget(add)
        remove = QPushButton("Remove selected probe")
        remove.clicked.connect(self.remove_roi)
        roi_layout.addWidget(remove)
        side.addWidget(roi_box)
        self.statistics = QLabel("Waiting for a camera.")
        self.statistics.setWordWrap(True)
        self.statistics.setTextInteractionFlags(Qt.TextSelectableByMouse)
        side.addWidget(self.statistics)
        advanced = QGroupBox("Advanced capture options")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        advanced_layout = QVBoxLayout(advanced)
        advanced_body = QWidget()
        advanced_form = QFormLayout(advanced_body)
        self.capacity = QSpinBox()
        self.capacity.setRange(1000, 10_000_000)
        self.capacity.setValue(1_000_000)
        self.capacity.setToolTip(
            "Recent events retained for preview. Applied on the next connection; independent of recording."
        )
        advanced_form.addRow("Preview event capacity", self.capacity)
        self.auto_preview = QCheckBox("Auto preview when opened or camera selected")
        self.auto_preview.setChecked(True)
        advanced_form.addRow(self.auto_preview)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        advanced_form.addRow(self.diagnostics)
        clock_note = QLabel(
            "During quiet periods, host elapsed time advances the preview window so events expire and trails fade. Recorded timestamps remain the original camera timestamps. Preview evictions are not hardware loss measurements."
        )
        clock_note.setWordWrap(True)
        advanced_form.addRow(clock_note)
        advanced_layout.addWidget(advanced_body)
        advanced_body.hide()
        advanced.toggled.connect(advanced_body.setVisible)
        side.addWidget(advanced)
        side.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(sidebar)
        scroll.setMinimumWidth(310)
        body.addWidget(scroll, 2)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.setInterval(33)
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.scan_cameras)
        self.scan_timer.setInterval(2000)
        self.view_changed()
        self.empty_view("Looking for connected event cameras...")
        self.update_buttons()
        from .window_chrome import install_window_header
        install_window_header(self)

    @staticmethod
    def number(low, high, value):
        widget = QDoubleSpinBox()
        widget.setRange(low, high)
        widget.setSingleStep(0.05)
        widget.setValue(value)
        return widget

    def mode_row(self, form, label, widget, modes):
        label_widget = QLabel(label)
        form.addRow(label_widget, widget)
        self._mode_rows.append((label_widget, widget, modes))

    def showEvent(self, event):
        super().showEvent(event)
        self._closing = False
        self._closed_emitted = False
        self._blocked_serials.clear()
        self._preview_requested = self.auto_preview.isChecked()
        self.timer.start()
        self.scan_timer.start()
        self.scan_cameras()

    def is_busy(self):
        return any(
            thread is not None
            for thread in (self.worker, self.discovery_worker, self.preview_worker)
        )

    def scan_cameras(self):
        if self._closing or self.discovery_worker is not None:
            return
        self.discovery_worker = DiscoveryWorker(self)
        self.discovery_worker.found.connect(self.apply_discovery)
        self.discovery_worker.finished.connect(self.discovery_finished)
        self.refresh_button.setEnabled(False)
        self.discovery_worker.start()

    def manual_scan(self):
        self._blocked_serials.clear()
        if self._discovery_state in ("error", "unavailable"):
            self._preview_requested = self.auto_preview.isChecked()
        self.scan_cameras()

    def discovery_finished(self):
        self.discovery_worker.deleteLater()
        self.discovery_worker = None
        self.refresh_button.setEnabled(True)
        self.maybe_finish_close()

    def apply_discovery(self, result):
        if self._closing:
            return
        self._discovery_state = result.state
        cameras = list(result.cameras)
        if (
            self.worker is not None
            and self._active_serial
            and all(c.serial != self._active_serial for c in cameras)
        ):
            from .camera_discovery import CameraInfo

            cameras.insert(
                0, CameraInfo(self._active_serial, "Streaming - " + self._active_serial)
            )
        entries = tuple((camera.serial, camera.label) for camera in cameras)
        previous = self.camera_combo.currentData()
        if entries != self._entries or not entries:
            self.camera_combo.blockSignals(True)
            self.camera_combo.clear()
            for serial, label in entries:
                self.camera_combo.addItem(label, serial)
            if not entries:
                placeholder = (
                    "No event cameras detected"
                    if result.state == "ready"
                    else (
                        "Camera support unavailable"
                        if result.state == "unavailable"
                        else "Camera detection failed"
                    )
                )
                self.camera_combo.addItem(placeholder, None)
            index = self.camera_combo.findData(previous)
            self.camera_combo.setCurrentIndex(index if index >= 0 else 0)
            self.camera_combo.blockSignals(False)
            self._entries = entries
        self.camera_combo.setEnabled(bool(entries))
        available = {serial for serial, label in entries}
        self._blocked_serials.intersection_update(available)
        if self.worker is None:
            if not entries:
                self._epoch += 1
                self.hw = None
                self.buffer = None
                self._last_request = None
                self._last_result = None
                self.probes = []
                self.roi_list.clear()
                self.candidate_changed(None)
                if self.preview_worker is not None:
                    self.preview_worker.stop()
                message = (
                    "No event cameras detected. Plug in a supported camera; this list refreshes automatically."
                    if result.state == "ready"
                    else result.detail
                )
                self.status.setText(message)
                self.empty_view(
                    "No event cameras detected"
                    if result.state == "ready"
                    else (
                        "Camera support unavailable"
                        if result.state == "unavailable"
                        else "Camera detection failed"
                    )
                )
            elif self.camera_combo.currentData() not in self._blocked_serials:
                self.status.setText("Ready - " + self.camera_combo.currentText())
            if (
                entries
                and self._preview_requested
                and self.auto_preview.isChecked()
                and self.camera_combo.currentData() not in self._blocked_serials
            ):
                self.connect_camera()
        self.update_buttons()

    def camera_changed(self):
        serial = self.camera_combo.currentData()
        if not serial or self._closing:
            return
        self._blocked_serials.discard(serial)
        self._preview_requested = self.auto_preview.isChecked()
        if self.worker is not None and serial != self._active_serial:
            self._epoch += 1
            self.hw = None
            self._last_request = None
            self._last_result = None
            self.empty_view("Switching cameras...")
            self._pending_serial = serial if self._preview_requested else None
            self.status.setText("Switching cameras...")
            self.worker.requestInterruption()
        elif self.worker is None and self._preview_requested:
            self.connect_camera()
        self.update_buttons()

    def connect_camera(self):
        serial = self.camera_combo.currentData()
        if self.worker is not None or self._closing or not serial:
            return
        self._blocked_serials.discard(serial)
        self._preview_requested = True
        self._pending_serial = None
        self._active_serial = serial
        self._epoch += 1
        self._last_request = None
        self._last_result = None
        self.buffer = EventBuffer(self.capacity.value())
        self.hw = None
        self.probes = []
        self.candidate = None
        self.roi_list.clear()
        self.candidate_changed(None)
        self.push_rois()
        self.empty_view("Connecting to " + self.camera_combo.currentText() + "...")
        self.status.setText("Connecting to " + self.camera_combo.currentText() + "...")
        self.worker = CameraWorker(self.buffer, serial, parent=self)
        epoch = self._epoch
        self.worker.geometry.connect(
            lambda h, w: self.set_geometry(h, w) if epoch == self._epoch else None
        )
        self.worker.status.connect(
            lambda message: (
                self.capture_status(message) if epoch == self._epoch else None
            )
        )
        self.worker.failed.connect(self.capture_error)
        self.worker.finished.connect(self.finished)
        self.worker.recording_changed.connect(self.recording_changed)
        self.worker.recording_failed.connect(self.recording_error)
        self.update_buttons()
        self.worker.start()

    def set_geometry(self, height, width):
        self.hw = (height, width)
        self.empty_view("Camera connected. Waiting for events...")
        self.update_buttons()

    def capture_status(self, message):
        if message == "Acquiring":
            self.status.setText("Live - " + self.camera_combo.currentText())
        else:
            self.status.setText(message)
        self.update_buttons()

    def capture_error(self, message):
        if self._active_serial:
            self._blocked_serials.add(self._active_serial)
        self.status.setText("Could not stream from this camera: " + message)

    def stop_camera(self):
        self._preview_requested = False
        self._pending_serial = None
        if self.worker is not None:
            self.status.setText("Stopping camera...")
            self.worker.requestInterruption()
        self.update_buttons()

    def finished(self):
        current = self.worker
        serial = self._active_serial
        if serial and not current.isInterruptionRequested():
            self._blocked_serials.add(serial)
        current.deleteLater()
        self.worker = None
        self._active_serial = None
        self._recording = False
        self._recording_pending = False
        self.record.setText("Record...")
        pending = self._pending_serial
        self._pending_serial = None
        self.update_buttons()
        if pending and not self._closing and self.camera_combo.currentData() == pending:
            self.connect_camera()
        elif not self._closing:
            self.invalidate_view()
        self.maybe_finish_close()

    def update_buttons(self):
        active = self.worker is not None
        stopping = active and self.worker.isInterruptionRequested()
        self.start.setEnabled(
            not active
            and self._discovery_state == "ready"
            and bool(self.camera_combo.currentData())
            and not self._closing
        )
        self.stop.setEnabled(active and not stopping and not self._closing)
        self.record.setEnabled(
            active
            and self.hw is not None
            and not stopping
            and not self._recording_pending
            and not self._closing
        )
        self.capacity.setEnabled(not active)

    def choose_recording(self):
        if self.worker is None:
            return
        camera = self.worker
        if self._recording:
            self.worker.request_recording()
            self.record.setText("Stopping recording...")
        else:
            path, _ = QFileDialog.getSaveFileName(
                self, "Record original camera events", "capture.csv", "CSV (*.csv)"
            )
            if not path:
                return
            if self.worker is not camera or camera.isInterruptionRequested():
                self.status.setText(
                    "Camera changed or stopped before recording could start. Select the camera and try again."
                )
                return
            if not Path(path).suffix:
                path += ".csv"
            self._recording_error_detail = None
            self.worker.request_recording(path)
            self.record.setText("Starting recording...")
        self._recording_pending = True
        self.update_buttons()

    def recording_changed(self, active, path):
        previously_recording = self._recording
        self._recording = active
        self._recording_pending = False
        self.record.setText("Stop recording" if active else "Record...")
        self.record.setStyleSheet(
            "QPushButton { background: #a03035; color: white; }" if active else ""
        )
        self.record.setToolTip(
            ("Recording original events to " if active else "Last recording: ") + path
        )
        if active:
            self._recording_error_detail = None
            self.recording_status.setText("Recording original events: " + path)
        elif self._recording_error_detail:
            self.recording_status.setText(self._recording_error_detail)
        elif previously_recording:
            self.recording_status.setText("Recording saved: " + path)
        self.update_buttons()

    def recording_error(self, message):
        self._recording_error_detail = message
        self.status.setText(message)
        self.recording_status.setText(message)
        self._recording_pending = False
        self.update_buttons()

    def parameters(self):
        return {
            "polarity": self.polarity.currentData(),
            "persistence_us": int(round(self.persistence.value() * 1000)),
            "glow": self.glow.value(),
            "heat_scale": self.heat_scale.currentText(),
            "grid": self.spacing.value(),
            "scale": self.arrow_scale.value(),
            "arrow_quality": self.arrow_quality.value(),
            "minimum": self.minimum.value(),
            "silhouette": self.silhouette.value(),
            "arrow_algorithm": "local-ncc-v1",
        }

    def view_changed(self):
        mode = self.mode_combo.currentData()
        self.description.setText(MODE_DESCRIPTIONS[mode])
        classification = (
            "RAW"
            if mode == "RAW"
            else "STYLIZED" if mode == "POLARITY GLOW" else "DERIVED"
        )
        self.view_box.setTitle(classification + " - " + self.mode_combo.currentText())
        for label, widget, modes in self._mode_rows:
            label.setVisible(mode in modes)
            widget.setVisible(mode in modes)
        self.mode_settings.setVisible(
            any(mode in modes for label, widget, modes in self._mode_rows)
        )
        self.invalidate_view()

    def toggle_comparison(self, checked):
        self.compare_box.setVisible(checked)
        self.invalidate_view()

    def invalidate_view(self):
        self._revision += 1
        self._last_request = None

    def refresh(self):
        if (
            self._closing
            or self.hw is None
            or self.buffer is None
            or not self.buffer.received
        ):
            return
        live = self.worker is not None and not self.worker.isInterruptionRequested()
        key = (
            self._epoch,
            self._revision,
            self.buffer.received,
            int(time.monotonic() * 30) if live else 0,
        )
        if key == self._last_request:
            return
        if self.preview_worker is None:
            self.preview_worker = PreviewWorker(self)
            self.preview_worker.rendered.connect(self.apply_preview)
            self.preview_worker.failed.connect(self.preview_error)
            self.preview_worker.finished.connect(self.preview_finished)
            self.preview_worker.start()
        self._last_request = key
        probes = tuple((name, replace(roi), color) for name, roi, color in self.probes)
        self.preview_worker.submit(
            PreviewRequest(
                self._epoch,
                self._revision,
                self.buffer,
                self.hw,
                self.mode_combo.currentData(),
                self.window.value() * 1000,
                self.parameters(),
                probes,
                self.compare_check.isChecked(),
                live,
            )
        )

    def apply_preview(self, result):
        if self._closing or (result["epoch"], result["revision"]) != (
            self._epoch,
            self._revision,
        ):
            return
        self._last_result = result
        self.view.set_frame(result["image"])
        if result["comparison"] is not None:
            self.compare_view.set_frame(result["comparison"])
        text = f"{result['events']:,} events | {result['rate']:.3f} ev/ms | + {result['positive']:,} / - {result['events']-result['positive']:,}"
        if result["probes"]:
            text += "\n" + "\n".join(result["probes"])
        if result["history_limited"]:
            text += "\nPreview history is limited by buffer capacity. Shorten the window or increase capacity before reconnecting."
        self.statistics.setText(text)
        skipped = (
            self.preview_worker.coalesced if self.preview_worker is not None else 0
        )
        self.diagnostics.setText(
            f"Received: {result['received']:,}\nDisplay-buffer evictions: {result['evicted']:,}\nHardware losses: UNKNOWN\nPreview requests coalesced: {skipped:,}\nRender time: {result['render_ms']:.1f} ms\nLatest actual event: {result['latest_event_us']} us\nPreview interval: [{result['start_us']}, {result['end_us']}) us"
        )

    def preview_error(self, epoch, revision, message):
        if not self._closing and (epoch, revision) == (self._epoch, self._revision):
            self.description.setText(
                "Preview could not render: "
                + message
                + ". Try another view or a shorter window."
            )

    def preview_finished(self):
        self.preview_worker.deleteLater()
        self.preview_worker = None
        self.maybe_finish_close()

    def empty_view(self, message):
        for viewer in (self.view, self.compare_view):
            viewer.set_help_text(message)
            viewer.set_frame(np.array([], dtype=np.uint8))
        self.statistics.setText(message)
        self.diagnostics.setText("")

    def candidate_changed(self, roi):
        if self.hw is None:
            roi = None
        self.candidate = roi
        for viewer in (self.view, self.compare_view):
            viewer.set_candidate_roi(roi)

    def add_roi(self):
        if self.candidate is None:
            return
        candidate = replace(self.candidate)
        epoch = self._epoch
        name, ok = QInputDialog.getText(self, "Live ROI", "Probe name:")
        if ok and epoch == self._epoch and self.hw is not None:
            colors = ("#64d2ff", "#ff9500", "#34c759", "#ff3b30")
            self.probes.append(
                (
                    name.strip() or f"ROI {len(self.probes)+1}",
                    candidate,
                    colors[len(self.probes) % len(colors)],
                )
            )
            self.roi_list.addItem(self.probes[-1][0])
            self.roi_list.setCurrentRow(len(self.probes) - 1)
            self.candidate_changed(None)
            self.push_rois()
            self.invalidate_view()

    def remove_roi(self):
        row = self.roi_list.currentRow()
        if 0 <= row < len(self.probes):
            del self.probes[row]
            self.roi_list.takeItem(row)
            self.push_rois()
            self.invalidate_view()

    def push_rois(self):
        active = self.roi_list.currentRow()
        for viewer in (self.view, self.compare_view):
            viewer.set_rois(
                [(roi, color) for name, roi, color in self.probes],
                active if active >= 0 else None,
            )

    def roi_moved(self, roi):
        row = self.roi_list.currentRow()
        if 0 <= row < len(self.probes):
            name, old, color = self.probes[row]
            self.probes[row] = (name, replace(roi), color)
            self.push_rois()
            self.invalidate_view()

    def maybe_finish_close(self):
        if self._closing and not self.is_busy():
            self.close()

    def closeEvent(self, event):
        self._closing = True
        self.timer.stop()
        self.scan_timer.stop()
        self.stop_camera()
        if self.preview_worker is not None:
            self.preview_worker.stop()
        if self.is_busy():
            self.status.setText("Closing live camera...")
            event.ignore()
            return
        if not self._closed_emitted:
            self._closed_emitted = True
            self.closed.emit()
        super().closeEvent(event)
