"""Transparent, descriptive diagnostics; no automatic data removal or noise claims."""

import numpy as np
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QLabel, QDoubleSpinBox,
                               QSpinBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QFileDialog, QMessageBox)
from .filters import apply_filters, CancelledError
from .project_utils import save_json


def recording_quality(events, hw, *, hot_rate=10.0, gap_us=10000, support_us=1000,
                      cancelled=lambda: False, progress=lambda n, message: None):
    if not np.isfinite(hot_rate) or hot_rate <= 0 or gap_us < 1 or support_us < 1:
        raise ValueError("Use positive diagnostic thresholds.")
    n = len(events.t)
    if not n:
        raise ValueError("The recording is empty.")
    if np.any(events.t[1:] < events.t[:-1]):
        raise ValueError("Diagnostics require sorted timestamps.")
    progress(0, "Counting pixel activity")
    duration_us = int(events.t[-1]) - int(events.t[0]) + 1
    pixels, counts = np.unique(events.y.astype(np.int64) * hw[1] + events.x, return_counts=True)
    rates = counts * 1000.0 / duration_us
    hot = np.flatnonzero(rates > hot_rate)
    hot = hot[np.argsort(-rates[hot], kind="stable")]
    gaps = np.diff(events.t)
    indices = np.flatnonzero(gaps >= gap_us)
    indices = indices[np.argsort(-gaps[indices], kind="stable")]
    if cancelled():
        raise CancelledError("Diagnostics cancelled")
    supported = apply_filters(events, {"support_us": support_us}, cancelled, progress)
    positive = int(np.count_nonzero(events.p > 0))
    unsupported = n - len(supported.t)
    return {
        "source": dict(events.metadata), "events": n, "duration_us": duration_us,
        "resolution_hw": [int(v) for v in hw], "active_pixels": len(pixels),
        "positive_events": positive, "negative_events": n - positive,
        "positive_fraction": positive / n, "events_per_ms": n * 1000.0 / duration_us,
        "same_timestamp_pairs": int(np.count_nonzero(gaps == 0)),
        "thresholds": {"hot_pixel_events_per_ms_gt": hot_rate, "gap_us_gte": gap_us,
                       "prior_neighbor_support_us": support_us},
        "hot_pixel_count": len(hot), "gap_count": len(indices),
        "unsupported_events": unsupported, "unsupported_fraction": unsupported / n,
        "interpretation": "High-rate pixels and event-free gaps are observations, not proof of sensor faults. Unsupported means no earlier event at a different 3x3 neighboring pixel within the support interval; this causal proxy includes startup and isolated real activity. It is not a calibrated noise measurement. Timestamps describe loaded, sorted events; source reordering may not be detectable.",
        "hot_pixels": [{"x": int(pixels[i] % hw[1]), "y": int(pixels[i] // hw[1]),
                        "events": int(counts[i]), "events_per_ms": float(rates[i])} for i in hot[:100]],
        "largest_gaps": [{"last_event_us": int(events.t[i]), "next_event_us": int(events.t[i + 1]),
                          "gap_us": int(gaps[i])} for i in indices[:100]],
        "table_limit": 100,
    }


class QualityDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner, Qt.Window)
        from .theme import appearance_controller
        appearance_controller().watch_window(self)
        self.owner = owner
        self.report = None
        self.setWindowTitle("Recording quality diagnostics")
        self.resize(760, 650)
        layout = QVBoxLayout(self)
        self.summary = QLabel("Diagnostics use the original loaded recording, independent of display filters.")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.summary)
        form = QFormLayout()
        self.hot = QDoubleSpinBox()
        self.hot.setRange(0.001, 1e9)
        self.hot.setDecimals(3)
        self.hot.setValue(10)
        self.gap = QSpinBox()
        self.gap.setRange(1, 1_000_000_000)
        self.gap.setValue(10000)
        self.support = QSpinBox()
        self.support.setRange(1, 1_000_000_000)
        self.support.setValue(1000)
        self.support.setToolTip(
            "Spatiotemporal support: checks whether any of the 8 surrounding pixels "
            "had a previously processed event within this time interval. "
            "1,000 µs = 1 ms. Events without this support can be real activity or noise; "
            "this check does not measure how much of the recording is noise."
        )
        form.addRow("High-rate pixel threshold (events/ms, >)", self.hot)
        form.addRow("Event-free gap threshold (us, >=)", self.gap)
        support_label = QLabel("Nearby activity look-back time (µs)")
        support_label.setToolTip(self.support.toolTip())
        form.addRow(support_label, self.support)
        layout.addLayout(form)
        run = QPushButton("Run diagnostics")
        run.clicked.connect(self.run)
        layout.addWidget(run)
        self.hot_table = QTableWidget(0, 4)
        self.hot_table.setHorizontalHeaderLabels(["Pixel x", "Pixel y", "Events", "Events/ms"])
        self.hot_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.hot_table)
        self.gap_table = QTableWidget(0, 3)
        self.gap_table.setHorizontalHeaderLabels(["Last event us", "Next event us", "Gap us"])
        self.gap_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.gap_table.cellDoubleClicked.connect(self.navigate_gap)
        layout.addWidget(self.gap_table)
        self.export_button = QPushButton("Export diagnostic report JSON")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export)
        layout.addWidget(self.export_button)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        from .window_chrome import install_window_header
        install_window_header(self)

    def run(self):
        if self.owner.events is None or self.owner._task is not None:
            return
        events, hw = self.owner.events, self.owner.hw
        self.report = None
        self.export_button.setEnabled(False)
        options = dict(hot_rate=self.hot.value(), gap_us=self.gap.value(), support_us=self.support.value())
        self.setEnabled(False)
        self.owner._run_task(
            lambda cancel, progress: recording_quality(events, hw, cancelled=cancel, progress=progress, **options),
            self.show_report, "Inspecting original recording", cooperative=True)
        self.owner._task.finished.connect(lambda: self.setEnabled(True))

    def show_report(self, report):
        self.report = report
        self.export_button.setEnabled(True)
        self.summary.setText(
            f"Original events: {report['events']:,}; active pixels: {report['active_pixels']:,}\n"
            f"Positive: {report['positive_fraction']:.1%}; negative: {1-report['positive_fraction']:.1%}\n"
            f"High-rate pixels: {report['hot_pixel_count']:,}; event-free gaps: {report['gap_count']:,}\n"
            f"Events without recent nearby activity: {report['unsupported_fraction']:.1%}. This does not mean they are noise.\n"
            "Tables show at most 100 entries. Double-click a gap to inspect it."
        )
        self.summary.setToolTip(self.support.toolTip() + "\n\n" + report["interpretation"])
        for table, rows, fields in ((self.hot_table, report["hot_pixels"], ("x", "y", "events", "events_per_ms")),
                                    (self.gap_table, report["largest_gaps"], ("last_event_us", "next_event_us", "gap_us"))):
            table.setRowCount(len(rows))
            for row, values in enumerate(rows):
                for col, field in enumerate(fields):
                    table.setItem(row, col, QTableWidgetItem(str(values[field])))
            table.resizeColumnsToContents()

    def navigate_gap(self, row, column):
        if self.report and row < len(self.report["largest_gaps"]):
            if self.owner.events is None or self.report["source"].get("sha256") != self.owner.events.metadata.get("sha256"):
                QMessageBox.information(self, "Source changed", "Run diagnostics again for the current recording.")
                return
            gap = self.report["largest_gaps"][row]
            self.owner.duration_us = gap["gap_us"] + 1
            self.owner._seek(gap["last_event_us"])

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export diagnostics", "recording_quality.json", "JSON (*.json)")
        if path and self.report:
            try:
                target = Path(path)
                if not target.suffix:
                    target = target.with_suffix(".json")
                if target.suffix.lower() != ".json":
                    raise ValueError("Diagnostic reports must use a .json filename.")
                if target.resolve() == Path(self.owner.loaded_csv_path).resolve():
                    raise ValueError("A source recording cannot be overwritten by a diagnostic report.")
                save_json(target, self.report)
            except (OSError, ValueError) as exc:
                QMessageBox.critical(self, "Export failed", str(exc))
