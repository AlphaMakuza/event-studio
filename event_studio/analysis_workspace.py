"""V2 analysis workspace; numerical operations live in independent modules."""

from __future__ import annotations
from pathlib import Path
from uuid import uuid4
import csv
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QComboBox,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QPlainTextEdit,
    QListWidget,
    QFileDialog,
    QMessageBox,
    QScrollArea,
    QHeaderView,
)
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from .activity import activity_series, detect_bursts, frequency_spectrum
from .motion import track_motion
from .filters import CancelledError
from .io_utils import export_table
from .roi_label import Roi

TAB_HELP = {
    'Activity': 'Shows how many brightness-change events occur over time. The top graph shows activity; the bottom graph adds up the events. More activity can mean motion, flicker, or noise.',
    'Bursts': 'Finds periods when activity stays above your chosen threshold. A burst is a busy period, not proof that a particular action happened.',
    'Frequency': 'Looks for repeating patterns in activity. Frequency in hertz (Hz) means repeats per second; a peak may come from motion or lighting flicker.',
    'Motion / micro-motion': 'Estimates how event patterns shift between time steps. Enable Calculate movement, then run analysis. Results are image movement estimates, not guaranteed object tracking.',
    'Annotations': 'Browse all notes and their timeframes. Select a note to read it or go to its time. Add and edit comments below the main timeline.',
    'Filters': 'Reduce isolated events, rapid repeats, or overactive pixels. The original recording stays unchanged; compare the filtered view with the original before trusting it.',
    'Visual export / batch': 'Save images or videos of the view, or repeat the same measurements across several recordings. Display styling does not change the measured data.',
}


class AnalysisWorkspace(QWidget):
    def __init__(self, owner):
        super().__init__(owner, Qt.Window)
        from .theme import appearance_controller
        appearance_controller().watch_window(self)
        self.owner = owner
        self.results = None
        self.selectors = []
        self.setWindowTitle("Event-Based Studio • Advanced Analysis")
        self.resize(1280, 880)
        outer = QVBoxLayout(self)
        self.description = QLabel(
            "Choose a tab, then Run analysis. Measurements use the selected time range; the original recording stays unchanged."
        )
        self.description.setWordWrap(True)
        outer.addWidget(self.description)
        content = QHBoxLayout()
        outer.addLayout(content, 1)
        settings = QWidget()
        form = QFormLayout(settings)
        self.start = QLineEdit()
        self.end = QLineEdit()
        form.addRow("Start µs", self.start)
        form.addRow("End µs (exclusive)", self.end)
        self.button(form, "Use current view interval", self.use_current_interval)
        self.button(form, "Use full recording", self.use_full_interval)
        self.scope = QComboBox()
        self.scope.addItems(["Whole field", "Active ROI", "All ROIs"])
        self.scope.setToolTip("Whole field means the whole image. ROI means a rectangle you drew in the viewer: Active ROI uses the selected rectangle; All ROIs compares every rectangle.")
        form.addRow("Area to analyze", self.scope)
        self.bin_us = self.integer(1, 1_000_000_000, 1000)
        form.addRow("Time step (µs)", self.bin_us)
        self.bin_us.setToolTip("Duration of each measurement step. 1,000 µs = 1 ms. Smaller steps show finer timing; larger steps smooth activity and reduce work.")
        self.threshold = self.number(0, 1e9, 100)
        self.threshold.setToolTip("A time step is busy when its event rate exceeds this value. Events/ms means brightness changes per millisecond; it is not an object count.")
        form.addRow("Busy above (events/ms)", self.threshold)
        self.min_burst = self.integer(1, 1_000_000_000, 1000)
        self.min_burst.setToolTip("How long activity must remain above the threshold to count as a burst. 1,000 µs = 1 ms.")
        form.addRow("Minimum busy time (µs)", self.min_burst)
        self.normalize = QCheckBox("Compare rates per pixel")
        self.normalize.setToolTip("Divides activity by area so large and small rectangles can be compared fairly.")
        form.addRow(self.normalize)
        self.compute_motion = QCheckBox("Calculate movement (first selected area)")
        self.compute_motion.setToolTip("Compares event patterns between time steps to estimate horizontal and vertical movement. Enable this before running analysis to fill the Motion graphs. It takes extra processing time.")
        form.addRow(self.compute_motion)
        self.shift = self.integer(1, 1024, 8)
        form.addRow("Movement search limit (px)", self.shift)
        self.shift.setToolTip("Largest movement to search for between time steps, in image pixels. Increase it for larger shifts; a larger search is slower and can produce ambiguous matches.")
        self.min_events = self.integer(1, 1_000_000, 10)
        self.min_events.setToolTip("Require this many events in both time steps before estimating movement. Higher values reject sparse estimates.")
        form.addRow("Events needed per step", self.min_events)
        self.quality = self.number(0, 1, 0.05, 3)
        form.addRow("Match strictness (0–1)", self.quality)
        self.quality.setToolTip("How strongly the best match stands out in the movement search. Higher values reject weaker estimates. This score is not a probability of correctness.")
        self.calibration = self.number(0, 1e9, 0, 6)
        form.addRow("Real distance per pixel", self.calibration)
        self.calibration.setToolTip("Only enter a value if you have calibrated the image scale. Leave 0 to measure in image pixels instead of real-world distance.")
        self.unit = QLineEdit("µm")
        form.addRow("Calibration unit", self.unit)
        self.amplification = self.number(0.1, 1000, 1)
        form.addRow("Movement display scale ×", self.amplification)
        self.amplification.setToolTip("Enlarges the displayed movement plot to make small changes easier to see. Exported measurements keep their original scale.")
        self.run_button = self.button(form, "Run analysis", self.run_analysis)
        self.button(form, "Export measurements CSV + JSON", self.export_measurements)
        self.button(form, "Export frequency CSV + JSON", self.export_frequency)
        self.button(form, "Export motion CSV + JSON", self.export_motion)
        self.button(form, "Export current graph PNG", self.export_graph)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings)
        scroll.setMinimumWidth(330)
        content.addWidget(scroll, 1)
        self.tabs = QTabWidget()
        content.addWidget(self.tabs, 3)
        self.tab_help = QLabel()
        self.tab_help.setWordWrap(True)
        outer.insertWidget(1, self.tab_help)
        self.activity_figure, self.activity_canvas = self.plot_tab("Activity")
        from .plot_navigation import PlotNavigation
        self.activity_navigation = PlotNavigation(
            self.activity_canvas, self.owner._seek_from_plot, self.save_plot_interval,
            lambda: self.results["config"]["start_us"] if self.results else 0,
        )
        self.activity_canvas.setToolTip("Click to seek playback. Drag across time to save a slice.")
        self.burst_table = QTableWidget(0, 6)
        self.burst_table.setHorizontalHeaderLabels(
            ["Area", "Start µs", "End µs", "Duration µs", "Peak events/ms", "Events"]
        )
        self.burst_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.burst_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        burst_page = QWidget()
        burst_layout = QVBoxLayout(burst_page)
        burst_layout.addWidget(self.burst_table)
        self.burst_table.itemSelectionChanged.connect(self.navigate_burst)
        for label, handler in (
            ("Convert selected burst to saved slice", self.burst_to_slice),
            ("Export bursts CSV + JSON", self.export_bursts),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            burst_layout.addWidget(button)
        self.tabs.addTab(burst_page, "Bursts")
        self.frequency_figure, self.frequency_canvas = self.plot_tab("Frequency")
        self.motion_figure, self.motion_canvas = self.plot_tab("Motion / micro-motion")
        self.build_annotations()
        self.build_filters()
        self.build_exports()
        self.tabs.currentChanged.connect(self.update_tab_help)
        self.update_tab_help()
        self.restore_settings()
        from .window_chrome import install_window_header
        install_window_header(self)

    def update_tab_help(self, *_):
        title = self.tabs.tabText(self.tabs.currentIndex())
        self.tab_help.setText(TAB_HELP.get(title, 'Choose settings, then Run analysis to calculate results.'))

    @staticmethod
    def integer(low, high, value):
        widget = QSpinBox()
        widget.setRange(low, high)
        widget.setValue(value)
        return widget

    @staticmethod
    def number(low, high, value, decimals=2):
        widget = QDoubleSpinBox()
        widget.setDecimals(decimals)
        widget.setRange(low, high)
        widget.setValue(value)
        return widget

    @staticmethod
    def button(layout, label, handler):
        button = QPushButton(label)
        button.clicked.connect(handler)
        layout.addRow(button)
        return button

    def plot_tab(self, title):
        figure = Figure(figsize=(7, 5), tight_layout=True)
        canvas = FigureCanvasQTAgg(figure)
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(canvas)
        self.tabs.addTab(page, title)
        return figure, canvas

    def use_current_interval(self):
        if self.owner.events is None:
            return
        start, end = self.owner._current_window()
        self.start.setText(str(start))
        self.end.setText(str(min(end, self.owner.t_max + 1)))
        self.refresh_annotations()

    def use_full_interval(self):
        self.start.setText(str(self.owner.t_min))
        self.end.setText(str(self.owner.t_max + 1))
        duration = self.owner.t_max + 1 - self.owner.t_min
        limit = 2000 if self.compute_motion.isChecked() else 100000
        self.bin_us.setValue(max(self.bin_us.value(), (duration + limit - 1) // limit))

    def configuration(self):
        t0, t1 = int(self.start.text()), int(self.end.text())
        if not self.owner.t_min <= t0 < t1 <= self.owner.t_max + 1:
            raise ValueError("Analysis interval must be inside the recording.")
        config = {
            "start_us": t0,
            "end_us": t1,
            "bin_us": self.bin_us.value(),
            "threshold": self.threshold.value(),
            "min_burst_us": self.min_burst.value(),
            "scope": self.scope.currentText(),
            "normalize": self.normalize.isChecked(),
            "compute_motion": self.compute_motion.isChecked(),
            "max_shift": self.shift.value(),
            "minimum_events": self.min_events.value(),
            "minimum_quality": self.quality.value(),
            "units_per_pixel": self.calibration.value(),
            "unit": self.unit.text(),
            "amplification": self.amplification.value(),
            "polarity": self.owner.polarity_combo.currentText(),
        }
        if (t1 - t0 + config["bin_us"] - 1) // config["bin_us"] > 100_000:
            raise ValueError(
                "Workspace limit is 100,000 bins. Increase bin width for this interval."
            )
        return config

    def restore_settings(self):
        saved = self.owner.analysis_settings
        pairs = {
            "bin_us": self.bin_us,
            "threshold": self.threshold,
            "min_burst_us": self.min_burst,
            "max_shift": self.shift,
            "minimum_events": self.min_events,
            "minimum_quality": self.quality,
            "units_per_pixel": self.calibration,
            "amplification": self.amplification,
        }
        for key, widget in pairs.items():
            if key in saved:
                widget.setValue(saved[key])
        self.scope.setCurrentText(saved.get("scope", "Whole field"))
        self.normalize.setChecked(saved.get("normalize", False))
        self.compute_motion.setChecked(saved.get("compute_motion", False))
        self.unit.setText(saved.get("unit", "µm"))
        self.use_full_interval()
        self.refresh_annotations()

    def probes(self):
        owner = self.owner
        scope = self.scope.currentText()
        items = (
            owner.rois
            if scope == "All ROIs"
            else (
                [owner.rois[owner.active_roi_index]]
                if scope == "Active ROI" and owner.active_roi_index is not None
                else []
            )
        )
        if scope != "Whole field" and not items:
            raise ValueError("Select or create at least one ROI for this scope.")
        if len(items) > 64:
            raise ValueError("Compare at most 64 probes per workspace analysis.")
        return [
            {
                "id": item.id,
                "name": item.name,
                "roi": vars(item.roi).copy(),
                "color": item.color,
            }
            for item in items
        ] or [{"id": None, "name": "Full field", "roi": None, "color": "#64d2ff"}]

    def run_analysis(self):
        if self.owner._task is not None:
            return
        try:
            config = self.configuration()
            probes = self.probes()
        except (ValueError, IndexError) as exc:
            QMessageBox.warning(self, "Analysis settings", str(exc))
            return
        self.owner.analysis_settings = config.copy()
        events, hw = self.owner._display_events(), self.owner.hw
        filters = self.owner.filter_settings.copy()

        def calculate(cancel, progress):
            results = {
                "resolution_hw": list(hw),
                "config": config,
                "probes": probes,
                "series": [],
                "bursts": [],
                "spectrum": None,
                "motion": None,
                "source": events.metadata,
                "filters": filters,
            }
            for index, probe in enumerate(probes):
                if cancel():
                    raise CancelledError("Analysis cancelled.")
                progress(
                    int(60 * index / len(probes)), "Calculating exact activity bins"
                )
                roi = Roi(**probe["roi"]) if probe["roi"] else None
                series = activity_series(
                    events,
                    config["start_us"],
                    config["end_us"],
                    config["bin_us"],
                    roi,
                    config["polarity"],
                )
                results["series"].append(series)
                for burst in detect_bursts(
                    series, config["threshold"], config["min_burst_us"]
                ):
                    results["bursts"].append(
                        {
                            **burst,
                            "probe": probe,
                            "filters": filters,
                            "polarity": config["polarity"],
                            "source_sha256": events.metadata.get("sha256"),
                        }
                    )
                if len(results["bursts"]) > 10000:
                    raise ValueError(
                        "More than 10,000 bursts. Increase threshold, bin width or minimum duration for the workspace."
                    )
            try:
                results["spectrum"] = frequency_spectrum(results["series"][0])
            except ValueError as exc:
                results["frequency_note"] = str(exc)
            if cancel():
                raise CancelledError("Analysis cancelled.")
            if config["compute_motion"]:
                roi = Roi(**probes[0]["roi"]) if probes[0]["roi"] else None
                results["motion"] = track_motion(
                    events,
                    hw,
                    config["start_us"],
                    config["end_us"],
                    config["bin_us"],
                    roi,
                    config["polarity"],
                    config["max_shift"],
                    config["minimum_events"],
                    config["minimum_quality"],
                    config["units_per_pixel"],
                    config["unit"],
                    cancel,
                    progress,
                )
            if cancel():
                raise CancelledError("Analysis cancelled.")
            return results

        self.owner._run_task(
            calculate, self.show_results, "Analyzing recorded events…", cooperative=True
        )

    def show_results(self, result):
        self.results = result
        config = result["config"]
        origin = config["start_us"]
        self.owner.detections = [
            {**burst, "name": f"Burst {i+1}"}
            for i, burst in enumerate(result["bursts"])
        ]
        self.owner._update_timeline_slice_regions()
        self.description.setText(
            f"Results for {len(result['series'])} area(s), measured every {config['bin_us'] / 1000:g} ms. "
            "Original recording unchanged. Click a graph to move playback; drag to save a slice."
        )
        self.activity_figure.clear()
        rate = self.activity_figure.add_subplot(211)
        cumulative = self.activity_figure.add_subplot(212, sharex=rate)
        for probe, series in zip(result["probes"], result["series"]):
            relative = (series.start_us - origin) / 1000
            area = (
                probe["roi"]["w"] * probe["roi"]["h"]
                if probe["roi"]
                else self.owner.hw[0] * self.owner.hw[1]
            )
            denominator = area if config["normalize"] else 1
            boundaries = np.r_[relative, (series.end_us[-1] - origin) / 1000]
            rate.stairs(series.rate / denominator, boundaries, label=probe["name"], color=probe["color"])
            cumulative.step(
                np.r_[0, (series.end_us - origin) / 1000],
                np.r_[0, series.cumulative],
                where="post",
                label=probe["name"],
                color=probe["color"],
            )
        first = result["series"][0]
        relative = (first.start_us - origin) / 1000
        duration_ms = (first.end_us - first.start_us) / 1000
        # Polarity detail uses the first probe, with the same optional area normalization.
        first_probe = result["probes"][0]
        area = (
            first_probe["roi"]["w"] * first_probe["roi"]["h"]
            if first_probe["roi"]
            else self.owner.hw[0] * self.owner.hw[1]
        )
        divisor = area if config["normalize"] else 1
        boundaries = np.r_[relative, (first.end_us[-1] - origin) / 1000]
        rate.stairs(
            first.positive / duration_ms / divisor,
            boundaries,
            alpha=0.5,
            label="First area: brightness increases",
        )
        rate.stairs(
            first.negative / duration_ms / divisor,
            boundaries,
            alpha=0.5,
            label="First area: brightness decreases",
        )
        rate.set_ylabel("events/ms/pixel" if config["normalize"] else "events/ms")
        rate.legend(fontsize=8)
        rate.grid(alpha=0.2)
        cumulative.set_ylabel("Cumulative events")
        cumulative.set_xlabel("Time since interval start (ms)")
        cumulative.grid(alpha=0.2)
        self.selectors = []
        self.activity_canvas.draw_idle()
        self.burst_table.setRowCount(len(result["bursts"]))
        for i, burst in enumerate(result["bursts"]):
            for j, value in enumerate(
                (
                    burst["probe"]["name"],
                    burst["t0"],
                    burst["t1"],
                    burst["duration_us"],
                    burst["peak_events_per_ms"],
                    burst["event_count"],
                )
            ):
                self.burst_table.setItem(i, j, QTableWidgetItem(str(value)))
        self.frequency_figure.clear()
        axis = self.frequency_figure.add_subplot(111)
        if result["spectrum"]:
            spectrum = result["spectrum"]
            axis.plot(spectrum["frequency_hz"], spectrum["amplitude_events_per_ms"])
            metadata = spectrum["metadata"]
            axis.set_title(
                f"Event-rate periodicity • Nyquist {metadata['nyquist_hz']:g} Hz • spacing {metadata['frequency_spacing_hz']:.3g} Hz"
            )
            peaks = (
                ", ".join(f"{peak['hz']:.3g} Hz" for peak in spectrum["peaks"])
                or "none"
            )
            axis.text(
                0.98,
                0.95,
                "Peaks: " + peaks,
                ha="right",
                va="top",
                transform=axis.transAxes,
                fontsize=8,
            )
        else:
            axis.text(
                0.5,
                0.5,
                result.get("frequency_note", "No spectrum"),
                ha="center",
                transform=axis.transAxes,
            )
        axis.set_xlabel("Frequency (Hz)")
        axis.set_ylabel("Hann-corrected amplitude (events/ms)")
        axis.grid(alpha=0.2)
        self.frequency_canvas.draw_idle()
        self.motion_figure.clear()
        axis = self.motion_figure.add_subplot(211 if result["motion"] else 111)
        if result["motion"]:
            rows = result["motion"]["rows"]
            times = np.array([row["start_us"] - origin for row in rows]) / 1000
            factor = config["amplification"]
            axis.plot(
                times,
                [row["dx_calibrated"] * factor for row in rows],
                label="Estimated horizontal step",
            )
            axis.plot(
                times,
                [row["dy_calibrated"] * factor for row in rows],
                label="Estimated vertical step",
            )
            axis.set_ylabel(
                result["motion"]["metadata"]["unit"] + f" × {factor:g} (display only)"
            )
            axis.set_title(
                "DERIVED displacement"
                if factor == 1
                else "STYLIZED amplified displacement • source unchanged"
            )
            axis.legend()
            failures = sum(not row["valid"] for row in rows[1:])
            axis.text(
                0.02,
                0.95,
                f"Failed links: {failures}; gaps are not interpolated",
                transform=axis.transAxes,
            )
            quality_axis = axis.twinx()
            quality_axis.plot(
                times,
                [row["quality"] for row in rows],
                color="gray",
                alpha=0.4,
                label="Peak prominence",
            )
            quality_axis.set_ylim(0, 1)
            quality_axis.set_ylabel("Quality heuristic (not probability)")
            trajectory = self.motion_figure.add_subplot(212)
            scale = config["units_per_pixel"] or 1
            trajectory.plot(
                [row["cumulative_x_px"] * scale * factor for row in rows],
                [row["cumulative_y_px"] * scale * factor for row in rows],
                ".-",
            )
            trajectory.set_xlabel(
                "Cumulative horizontal estimate " + result["motion"]["metadata"]["unit"]
            )
            trajectory.set_ylabel("Cumulative vertical estimate")
            trajectory.grid(alpha=0.2)
        else:
            axis.text(
                0.5,
                0.5,
                "Check Calculate movement on the left, then click Run analysis.\nThis estimates how event patterns move between time steps.",
                ha="center",
                transform=axis.transAxes,
            )
        axis.set_xlabel("Time since interval start (ms)")
        axis.grid(alpha=0.2)
        self.motion_canvas.draw_idle()

    def select_interval(self, left, right):
        if self.results is None:
            return
        origin = self.results["config"]["start_us"]
        start = max(origin, origin + int(round(left * 1000)))
        end = min(self.results["config"]["end_us"], origin + int(round(right * 1000)))
        if end > start:
            self.owner.duration_us = end - start
            self.owner._seek(start)
            self.start.setText(str(start))
            self.end.setText(str(end))

    def save_plot_interval(self, start, end):
        if not self.results:
            return
        result = self.results
        probes = result["probes"]
        # A comparison span is temporal; a single-probe plot also captures its ROI.
        probe = probes[0] if len(probes) == 1 else None
        self.owner._slice_from_plot(start, end, {
            "source_sha256": result["source"].get("sha256"),
            "polarity": result["config"]["polarity"], "filters": result["filters"],
            "roi_id": probe["id"] if probe else None,
            "roi_snapshot": probe["roi"] if probe else None,
        })

    def navigate_burst(self):
        row = self.burst_table.currentRow()
        if self.results and 0 <= row < len(self.results["bursts"]):
            item = self.results["bursts"][row]
            self.owner.duration_us = item["t1"] - item["t0"]
            self.owner._seek(item["t0"])

    def burst_to_slice(self):
        row = self.burst_table.currentRow()
        if not self.results or not 0 <= row < len(self.results["bursts"]):
            return
        from .app import Slice

        item = self.results["bursts"][row]
        before = self.owner.edit_history.snapshot()
        probe = item["probe"]
        index = next(
            (i for i, p in enumerate(self.owner.rois) if p.id == probe["id"]), None
        )
        self.owner.slices.append(
            Slice(
                f"Burst {row+1} • {probe['name']}",
                item["t0"],
                item["t1"],
                index,
                roi_id=probe["id"],
                roi_snapshot=probe["roi"],
                polarity=item["polarity"],
                source_sha256=item["source_sha256"],
                filters=item["filters"].copy(),
            )
        )
        self.owner._rebuild_slice_list()
        self.owner.slice_list.setCurrentRow(len(self.owner.slices) - 1)
        self.owner._update_timeline_slice_regions()
        self.owner.edit_history.commit("Add burst slice", before)

    def save_measurement(self, title, columns, rows, metadata):
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            str(self.owner.data_dir / "measurements" / "analysis.csv"),
            "CSV (*.csv)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".csv"
        self.owner._run_task(
            lambda: export_table(path, columns, rows, metadata),
            lambda _: self.description.setText(
                "Saved CSV and reproducibility metadata: " + path
            ),
            "Exporting measurements…",
        )

    def export_measurements(self):
        if not self.results:
            return
        result = self.results
        rows = (
            (
                probe["name"],
                probe["id"],
                int(start),
                int(end),
                int(total),
                int(pos),
                int(neg),
                float(rate),
                float(rate) / (probe["roi"]["w"] * probe["roi"]["h"] if probe["roi"]
                               else result["resolution_hw"][0] * result["resolution_hw"][1]),
                int(cumulative),
            )
            for probe, series in zip(result["probes"], result["series"])
            for start, end, total, pos, neg, rate, cumulative in zip(
                series.start_us,
                series.end_us,
                series.total,
                series.positive,
                series.negative,
                series.rate,
                series.cumulative,
            )
        )
        self.save_measurement(
            "Export activity comparison",
            [
                "probe",
                "roi_id",
                "start_us",
                "end_us_exclusive",
                "events",
                "positive",
                "negative",
                "events_per_ms",
                "events_per_ms_per_pixel",
                "cumulative_events",
            ],
            rows,
            {
                "source": result["source"],
                "algorithm": "half-open event histogram",
                "parameters": result["config"],
                "probes": result["probes"],
                "filters": result["filters"],
                "rate_normalization": "CSV includes absolute events/ms and events/ms/pixel; graph normalization uses the same ROI area.",
            },
        )

    def export_bursts(self):
        if not self.results:
            return
        result = self.results
        self.save_measurement(
            "Export bursts",
            [
                "probe",
                "start_us",
                "end_us_exclusive",
                "duration_us",
                "peak_events_per_ms",
                "events",
            ],
            (
                (
                    b["probe"]["name"],
                    b["t0"],
                    b["t1"],
                    b["duration_us"],
                    b["peak_events_per_ms"],
                    b["event_count"],
                )
                for b in result["bursts"]
            ),
            {
                "source": result["source"],
                "algorithm": "contiguous bins strictly above threshold",
                "parameters": result["config"],
                "probes": result["probes"],
                "filters": result["filters"],
            },
        )

    def export_frequency(self):
        if not self.results or not self.results["spectrum"]:
            return
        spectrum = self.results["spectrum"]
        self.save_measurement(
            "Export frequency spectrum",
            ["frequency_hz", "amplitude_events_per_ms"],
            zip(spectrum["frequency_hz"], spectrum["amplitude_events_per_ms"]),
            spectrum["metadata"],
        )

    def export_motion(self):
        if not self.results or not self.results["motion"]:
            return
        result = self.results["motion"]
        columns = list(result["rows"][0])
        self.save_measurement(
            "Export estimated motion",
            columns,
            ([row[key] for key in columns] for row in result["rows"]),
            result["metadata"],
        )

    def export_graph(self):
        figures = {
            0: self.activity_figure,
            2: self.frequency_figure,
            3: self.motion_figure,
        }
        figure = figures.get(self.tabs.currentIndex())
        if figure is None or self.results is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export graph PNG", "analysis.png", "PNG (*.png)"
        )
        if path:
            try:
                import tempfile
                from .io_utils import commit_pair
                from .project_utils import save_json
                from .version import __version__, ANALYSIS_VERSION

                destination = Path(path)
                if not destination.suffix:
                    destination = destination.with_suffix(".png")
                if destination.suffix.lower() != ".png":
                    raise ValueError("Graph exports must use .png.")
                with tempfile.TemporaryDirectory(
                    prefix="graph-", dir=destination.parent
                ) as folder:
                    stage = Path(folder) / destination.name
                    figure.savefig(stage, dpi=180)
                    classification = (
                        "STYLIZED"
                        if self.tabs.currentIndex() == 3
                        and self.results["config"]["amplification"] != 1
                        else "DERIVED"
                    )
                    save_json(
                        stage.with_suffix(".json"),
                        {
                            "source": self.results["source"],
                            "parameters": self.results["config"],
                            "filters": self.results["filters"],
                            "probes": self.results["probes"],
                            "software_version": __version__,
                            "algorithm_version": ANALYSIS_VERSION,
                            "algorithm": "activity histogram / Hann FFT / integer phase correlation; see selected graph",
                            "classification": classification,
                            "graph": self.tabs.tabText(self.tabs.currentIndex()),
                        },
                    )
                    commit_pair(
                        stage,
                        stage.with_suffix(".json"),
                        destination,
                        destination.with_suffix(".json"),
                    )
            except Exception as exc:
                QMessageBox.critical(self, "Graph export", str(exc))

    def build_annotations(self):
        page = QWidget()
        page.setStyleSheet('QLabel, QListWidget, QPlainTextEdit { color: #d9d9df; selection-color: #ffffff; } QPlainTextEdit { placeholder-text-color: #b6b6c2; }')
        layout = QVBoxLayout(page)
        hint = QLabel("All project notes, with times measured from the recording start. Add and edit notes below the main timeline. Double-click a note to go to its time.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.notes = QListWidget()
        self.notes.setAccessibleName("All timeline notes")
        layout.addWidget(self.notes)
        self.note_detail = QPlainTextEdit()
        self.note_detail.setReadOnly(True)
        self.note_detail.setPlaceholderText("Select a note to read it.")
        layout.addWidget(self.note_detail)
        for label, handler in (
            ("Go to annotated time", self.jump_annotation),
            ("Export notes CSV + JSON", self.export_annotations),
        ):
            button = QPushButton(label)
            button.clicked.connect(handler)
            layout.addWidget(button)
        self.notes.currentRowChanged.connect(self.select_annotation)
        self.notes.itemDoubleClicked.connect(lambda _: self.jump_annotation())
        self.tabs.addTab(page, "Annotations")

    def refresh_annotations(self):
        if not hasattr(self, "notes"):
            return
        from .timeline_notes import note_time
        selected = self.notes.currentItem()
        selected_index = selected.data(Qt.UserRole) if selected is not None else None
        self.notes.blockSignals(True)
        self.notes.clear()
        for index, note in sorted(enumerate(self.owner.annotations), key=lambda pair: pair[1]['t0']):
            from PySide6.QtWidgets import QListWidgetItem
            text = note.get('text') or note.get('name', 'Note')
            item = QListWidgetItem(f"{note_time(note, self.owner.t_min)}  |  {text.replace(chr(10), ' ')}")
            item.setData(Qt.UserRole, index)
            item.setToolTip(text)
            self.notes.addItem(item)
            if index == selected_index:
                self.notes.setCurrentItem(item)
        self.notes.blockSignals(False)
        self.select_annotation(self.notes.currentRow())
        if not self.owner.annotations:
            self.note_detail.setPlainText("No notes yet. Add a comment below the main timeline.")

    def selected_annotation_index(self):
        item = self.notes.currentItem()
        return item.data(Qt.UserRole) if item is not None else -1

    def select_annotation(self, row):
        index = self.selected_annotation_index()
        if 0 <= index < len(self.owner.annotations):
            from .timeline_notes import note_time
            note = self.owner.annotations[index]
            self.note_detail.setPlainText(f"{note_time(note, self.owner.t_min)}\n\n{note.get('text') or note.get('name', '')}")
        else:
            self.note_detail.clear()

    def jump_annotation(self):
        index = self.selected_annotation_index()
        if 0 <= index < len(self.owner.annotations):
            self.owner.timeline_notes.select_note(index)

    def export_annotations(self):
        notes = [note.copy() for note in self.owner.annotations]
        self.save_measurement(
            "Export annotations",
            ["id", "name", "start_us", "end_us", "notes", "labels", "roi_id"],
            (
                (
                    n["id"],
                    n["name"],
                    n["t0"],
                    n["t1"],
                    n.get("text", ""),
                    ";".join(n.get("labels", [])),
                    n.get("roi_id"),
                )
                for n in notes
            ),
            {
                "source": self.owner.events.metadata,
                "algorithm": "user annotations",
                "annotations": notes,
            },
        )

    def build_filters(self):
        page = QWidget()
        form = QFormLayout(page)
        label = QLabel(
            "DERIVED view only. Zero disables each filter. Compare with unfiltered RAW in the main window. Filters affect new slices/current-selection exports; full and ROI exports remain raw."
        )
        label.setWordWrap(True)
        form.addRow(label)
        self.refractory = self.integer(0, 1_000_000_000, 0)
        form.addRow("Refractory µs", self.refractory)
        self.support = self.integer(0, 1_000_000_000, 0)
        form.addRow("Prior 3×3 neighbor support µs", self.support)
        self.hot = self.number(0, 1e9, 0, 4)
        form.addRow("Suppress pixels above ev/ms", self.hot)
        details = QLabel(
            "Refractory time is since the last retained event at the same pixel. Neighbor support uses previous raw events at adjacent pixels; no look-ahead. Hot-pixel rate is calculated over the whole recording."
        )
        details.setWordWrap(True)
        form.addRow(details)
        self.button(form, "Apply filters", self.apply_filter_controls)
        self.button(form, "Disable all filters", self.disable_filters)
        self.tabs.addTab(page, "Filters")

    def apply_filter_controls(self):
        settings = {
            "refractory_us": self.refractory.value(),
            "support_us": self.support.value(),
            "hot_pixel_events_per_ms": self.hot.value(),
        }
        self.owner._apply_filter_settings(settings, self.clear_results)

    def disable_filters(self):
        self.refractory.setValue(0)
        self.support.setValue(0)
        self.hot.setValue(0)
        self.owner._apply_filter_settings({}, self.clear_results)

    def build_exports(self):
        page = QWidget()
        form = QFormLayout(page)
        self.fps = self.number(0.001, 240, 30, 3)
        form.addRow("Visual export frames/sec", self.fps)
        self.width = self.integer(1, 8192, 640)
        self.height = self.integer(1, 8192, 480)
        form.addRow("Output width", self.width)
        form.addRow("Output height", self.height)
        self.timestamp_check = QCheckBox("Timestamp captions")
        self.timestamp_check.setChecked(True)
        form.addRow(self.timestamp_check)
        self.overlay_check = QCheckBox("Visible ROI overlays")
        self.overlay_check.setChecked(True)
        form.addRow(self.overlay_check)
        self.mp4 = QCheckBox("Also encode MP4")
        self.mp4.setToolTip('Uses FFmpeg on PATH or the optional requirements-video.txt backend.')
        form.addRow(self.mp4)
        self.button(form, "Export current mode as PNG sequence", self.export_visual)
        label = QLabel(
            "Visual exports use the analysis interval, selected view/filter settings and main accumulation duration. They are presentation artifacts, not event-data exports. Partial/cancelled sequences carry a manifest."
        )
        label.setWordWrap(True)
        form.addRow(label)
        self.batch_rois = QCheckBox(
            "Reuse named ROIs in batch (requires verified matching sensor dimensions)"
        )
        form.addRow(self.batch_rois)
        self.button(form, "Batch analyze CSV recordings", self.run_batch)
        self.batch_results = QTableWidget(0, 6)
        self.batch_results.setHorizontalHeaderLabels(
            ["Recording", "ROI", "Status", "Events", "Events/ms/pixel", "Error"]
        )
        self.batch_results.setEditTriggers(QTableWidget.NoEditTriggers)
        form.addRow(self.batch_results)
        self.tabs.addTab(page, "Visual export / batch")

    def export_visual(self):
        try:
            config = self.configuration()
        except ValueError as exc:
            QMessageBox.warning(self, "Export interval", str(exc))
            return
        directory = QFileDialog.getExistingDirectory(
            self, "Choose output parent directory"
        )
        if not directory:
            return
        from .visual_export import export_sequence

        owner = self.owner
        destination = Path(directory) / ("visualization_" + uuid4().hex[:10])
        events = owner._display_events()
        hw = owner.hw
        mode, parameters, duration = (
            owner.current_view_mode,
            owner._render_parameters(),
            owner.duration_us,
        )
        options = {
            "fps": self.fps.value(),
            "width": self.width.value(),
            "height": self.height.value(),
            "timestamps": self.timestamp_check.isChecked(),
            "mp4": self.mp4.isChecked(),
            "overlays": (
                [
                    {"roi": vars(p.roi).copy(), "color": p.color}
                    for p in owner.rois
                    if p.visible
                ]
                if self.overlay_check.isChecked()
                else []
            ),
        }
        owner._run_task(
            lambda cancel, progress: export_sequence(
                destination,
                events,
                hw,
                config["start_us"],
                config["end_us"],
                mode,
                parameters,
                window_us=duration,
                cancelled=cancel,
                progress=progress,
                **options,
            ),
            lambda result: self.description.setText(
                f"Visual export {result['status']}: {destination}"
            ),
            "Exporting visualization…",
            cooperative=True,
        )

    def run_batch(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Choose CSV recordings", str(self.owner.data_dir), "CSV (*.csv)"
        )
        if not paths:
            return
        directory = QFileDialog.getExistingDirectory(self, "Choose batch output parent")
        if not directory:
            return
        from .batch import analyze_batch

        options = {
            "bin_us": self.bin_us.value(),
            "threshold": self.threshold.value(),
            "min_burst_us": self.min_burst.value(),
            "polarity": self.owner.polarity_combo.currentText(),
            "filters": self.owner.filter_settings.copy(),
            "rois": (
                [{"name": p.name, "roi": vars(p.roi).copy()} for p in self.owner.rois]
                if self.batch_rois.isChecked()
                else None
            ),
            "expected_hw": self.owner.hw,
        }
        destination = Path(directory) / ("batch_" + uuid4().hex[:10])
        self.owner._run_task(
            lambda cancel, progress: analyze_batch(
                paths, destination, cancelled=cancel, progress=progress, **options
            ),
            lambda report: self.show_batch_results(report, destination),
            "Running batch analysis…",
            cooperative=True,
        )

    def show_batch_results(self, report, destination):
        rows = report["results"]
        self.description.setText(
            f"Batch {'cancelled' if report['cancelled'] else 'finished'}: "
            f"{sum(r['status']=='ok' for r in rows)} results; "
            f"{sum(r['status']=='error' for r in rows)} errors. CSV / JSON: {destination}"
        )
        self.batch_results.setRowCount(len(rows))
        for i, row in enumerate(rows):
            values = (Path(row["source"]).name, row.get("probe", ""), row["status"],
                      row.get("events", ""), row.get("events_per_ms_per_pixel", ""), row.get("error", ""))
            for j, value in enumerate(values):
                self.batch_results.setItem(i, j, QTableWidgetItem(str(value)))
        self.batch_results.resizeColumnsToContents()

    def clear_results(self):
        self.results = None
        self.burst_table.setRowCount(0)
        self.selectors = []
        for figure, canvas in (
            (self.activity_figure, self.activity_canvas),
            (self.frequency_figure, self.frequency_canvas),
            (self.motion_figure, self.motion_canvas),
        ):
            figure.clear()
            canvas.draw_idle()
        self.refresh_annotations()
        for key, widget in (
            ("refractory_us", self.refractory),
            ("support_us", self.support),
            ("hot_pixel_events_per_ms", self.hot),
        ):
            widget.setValue(self.owner.filter_settings.get(key, 0))
        self.description.setText(
            "Settings changed. Run analysis to calculate reproducible measurements."
        )
