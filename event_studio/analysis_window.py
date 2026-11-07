from __future__ import annotations

import time
from typing import Optional

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .roi_label import Roi
from .viewer import compute_roi_stats


class ActivityPlotWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ROI Activity Plot")
        self.resize(820, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.info_label = QLabel("No ROI plot loaded.")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.info_label)

        self.figure = Figure(figsize=(7, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        root.addWidget(self.canvas, stretch=1)

    def set_plot_data(
        self,
        *,
        roi_name: str,
        loaded_name: str,
        times_ms: np.ndarray,
        total_counts: np.ndarray,
        pos_counts: np.ndarray,
        neg_counts: np.ndarray,
        current_time_ms: float,
    ) -> None:
        self.info_label.setText(
            f'ROI Activity Plot — "{roi_name}"\n'
            f"Source: {loaded_name}\n"
            f"Current playback time: {current_time_ms:.2f} ms"
        )

        self.figure.clear()
        ax = self.figure.add_subplot(111)

        ax.plot(times_ms, total_counts, label="Total events")
        ax.plot(times_ms, pos_counts, label="Positive events")
        ax.plot(times_ms, neg_counts, label="Negative events")
        ax.axvline(current_time_ms, linestyle="--", label="Current time")

        ax.set_title(f'ROI Activity Over Time — "{roi_name}"')
        ax.set_xlabel("Time (ms)")
        ax.set_ylabel("Events per bin")
        ax.legend()
        ax.grid(True, alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw_idle()


class SpatialPlotWindow(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("ROI Spatial Plot")
        self.resize(860, 760)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.info_label = QLabel("No ROI spatial plot loaded.")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.info_label)

        button_row = QHBoxLayout()
        self.btn_mode_raw = QPushButton("Raw Spatial")
        self.btn_mode_time = QPushButton("Time-Colored")
        button_row.addWidget(self.btn_mode_raw)
        button_row.addWidget(self.btn_mode_time)
        button_row.addStretch(1)
        root.addLayout(button_row)

        self.figure = Figure(figsize=(6, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        root.addWidget(self.canvas, stretch=1)

        self._last_payload: Optional[dict] = None
        self._mode = "raw"

        self.btn_mode_raw.clicked.connect(self._set_raw_mode)
        self.btn_mode_time.clicked.connect(self._set_time_mode)

    def _set_raw_mode(self) -> None:
        self._mode = "raw"
        self._redraw()

    def _set_time_mode(self) -> None:
        self._mode = "time"
        self._redraw()

    def set_plot_data(
        self,
        *,
        roi_name: str,
        loaded_name: str,
        xs: np.ndarray,
        ys: np.ndarray,
        ts: np.ndarray,
        roi_w: int,
        roi_h: int,
        n_events: int,
    ) -> None:
        self._last_payload = {
            "roi_name": roi_name,
            "loaded_name": loaded_name,
            "xs": xs,
            "ys": ys,
            "ts": ts,
            "roi_w": roi_w,
            "roi_h": roi_h,
            "n_events": n_events,
        }
        self._redraw()

    def _redraw(self) -> None:
        if self._last_payload is None:
            return

        roi_name = self._last_payload["roi_name"]
        loaded_name = self._last_payload["loaded_name"]
        xs = self._last_payload["xs"]
        ys = self._last_payload["ys"]
        ts = self._last_payload["ts"]
        roi_w = int(self._last_payload["roi_w"])
        roi_h = int(self._last_payload["roi_h"])
        n_events = int(self._last_payload["n_events"])

        mode_label = "Raw Spatial" if self._mode == "raw" else "Time-Colored Spatial"
        self.info_label.setText(
            f'{mode_label} Plot — "{roi_name}"\n'
            f"Source: {loaded_name}\n"
            f"ROI size: {roi_w}x{roi_h} px\n"
            f"Events shown: {n_events:,}"
        )

        self.figure.clear()
        ax = self.figure.add_subplot(111)

        if xs.size > 0:
            if self._mode == "raw":
                ax.scatter(xs, ys, s=1)
            else:
                if ts.size > 1 and int(ts.max()) > int(ts.min()):
                    t_norm = (ts - int(ts.min())).astype(np.float64) / (int(ts.max()) - int(ts.min()))
                else:
                    t_norm = np.zeros_like(ts, dtype=np.float64)

                sc = ax.scatter(xs, ys, s=1, c=t_norm, cmap="turbo")
                cbar = self.figure.colorbar(sc, ax=ax)
                cbar.set_label("Older → Newer")
        else:
            ax.text(0.5, 0.5, "No ROI events", ha="center", va="center", transform=ax.transAxes)

        ax.set_title(f'{mode_label} — "{roi_name}"')
        ax.set_xlabel("x (ROI-local)")
        ax.set_ylabel("y (ROI-local)")
        ax.set_xlim(0, max(1, roi_w))
        ax.set_ylim(max(1, roi_h), 0)
        ax.set_aspect("equal", adjustable="box")
        ax.grid(True, alpha=0.25)

        self.figure.tight_layout()
        self.canvas.draw_idle()


class ROIAnalysisPanel(QWidget):
    closeRequested = Signal()

    TRAIL_UPDATE_INTERVAL_SEC = 0.25
    MIN_PLAYHEAD_DELTA_US = 30_000
    MAX_SPATIAL_POINTS = 50_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._last_heatmap_rgb: Optional[np.ndarray] = None
        self._last_trail_rgb: Optional[np.ndarray] = None
        self._last_title: str = "roi_analysis"

        self._plot_window: Optional[ActivityPlotWindow] = None
        self._spatial_plot_window: Optional[SpatialPlotWindow] = None

        self._last_plot_payload: Optional[dict] = None
        self._last_spatial_plot_payload: Optional[dict] = None

        self._cached_roi_key: Optional[tuple] = None
        self._cached_events_key: Optional[tuple] = None
        self._cached_heatmap_rgb: Optional[np.ndarray] = None
        self._cached_spatial_payload: Optional[dict] = None

        self._last_trail_update_walltime: float = 0.0
        self._last_trail_playhead_us: Optional[int] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        header = QHBoxLayout()

        self.title_label = QLabel("ROI Analysis")
        self.title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        header.addWidget(self.title_label)

        header.addStretch(1)

        self.btn_export_heatmap = QPushButton("Export Heatmap PNG")
        self.btn_export_heatmap.clicked.connect(self.export_heatmap_png)
        self.btn_export_heatmap.setEnabled(False)
        header.addWidget(self.btn_export_heatmap)

        self.btn_export_trail = QPushButton("Export Trail PNG")
        self.btn_export_trail.clicked.connect(self.export_trail_png)
        self.btn_export_trail.setEnabled(False)
        header.addWidget(self.btn_export_trail)

        self.btn_open_plot = QPushButton("Open Activity Plot")
        self.btn_open_plot.clicked.connect(self.open_activity_plot)
        self.btn_open_plot.setEnabled(False)
        header.addWidget(self.btn_open_plot)

        self.btn_open_spatial_plot = QPushButton("Open Spatial Plot")
        self.btn_open_spatial_plot.clicked.connect(self.open_spatial_plot)
        self.btn_open_spatial_plot.setEnabled(False)
        header.addWidget(self.btn_open_spatial_plot)

        self.btn_close = QPushButton("Hide")
        self.btn_close.clicked.connect(self.closeRequested.emit)
        header.addWidget(self.btn_close)

        root.addLayout(header)

        self.subtitle_label = QLabel("No ROI selected.")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.subtitle_label)

        maps_grid = QGridLayout()
        maps_grid.setHorizontalSpacing(8)
        maps_grid.setVerticalSpacing(6)

        self.heatmap_title = QLabel("Density Heatmap")
        self.heatmap_title.setStyleSheet("font-weight: 600;")
        maps_grid.addWidget(self.heatmap_title, 0, 0)

        self.trail_title = QLabel("Temporal Trail Map (progressive)")
        self.trail_title.setStyleSheet("font-weight: 600;")
        maps_grid.addWidget(self.trail_title, 0, 1)

        self.heatmap_label = QLabel("Heatmap will appear here")
        self.heatmap_label.setAlignment(Qt.AlignCenter)
        self.heatmap_label.setMinimumSize(220, 220)
        self.heatmap_label.setStyleSheet("background: #111; border: 1px solid #333;")
        maps_grid.addWidget(self.heatmap_label, 1, 0)

        self.trail_label = QLabel("Trail map will appear here")
        self.trail_label.setAlignment(Qt.AlignCenter)
        self.trail_label.setMinimumSize(220, 220)
        self.trail_label.setStyleSheet("background: #111; border: 1px solid #333;")
        maps_grid.addWidget(self.trail_label, 1, 1)

        root.addLayout(maps_grid)

        self.full_stats_label = QLabel("Full ROI stats: —")
        self.full_stats_label.setWordWrap(True)
        self.full_stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.full_stats_label.setStyleSheet(
            "background: #171717; padding: 8px; border: 1px solid #2f2f2f;"
        )
        root.addWidget(self.full_stats_label)

        self.window_stats_label = QLabel("Current-window ROI stats: —")
        self.window_stats_label.setWordWrap(True)
        self.window_stats_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.window_stats_label.setStyleSheet(
            "background: #171717; padding: 8px; border: 1px solid #2f2f2f;"
        )
        root.addWidget(self.window_stats_label)

    def _format_ratio_percent(self, pos: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return 100.0 * pos / total

    def clear_analysis(self) -> None:
        self.title_label.setText("ROI Analysis")
        self.subtitle_label.setText("No ROI selected.")
        self.full_stats_label.setText("Full ROI stats: —")
        self.window_stats_label.setText("Current-window ROI stats: —")

        self.heatmap_label.setText("Heatmap will appear here")
        self.heatmap_label.setPixmap(QPixmap())

        self.trail_label.setText("Trail map will appear here")
        self.trail_label.setPixmap(QPixmap())

        self._last_heatmap_rgb = None
        self._last_trail_rgb = None
        self._last_plot_payload = None
        self._last_spatial_plot_payload = None

        self._cached_roi_key = None
        self._cached_events_key = None
        self._cached_heatmap_rgb = None
        self._cached_spatial_payload = None

        self._last_trail_update_walltime = 0.0
        self._last_trail_playhead_us = None

        self.btn_export_heatmap.setEnabled(False)
        self.btn_export_trail.setEnabled(False)
        self.btn_open_plot.setEnabled(False)
        self.btn_open_spatial_plot.setEnabled(False)

    def _events_key(self, events) -> tuple:
        if events is None or events.t.size == 0:
            return (0, 0, 0)
        return (
            id(events),
            events.metadata.get("sha256"),
            int(events.t.size),
            int(events.t[0]),
            int(events.t[-1]),
        )

    def _roi_key(self, roi: Roi) -> tuple:
        return (int(roi.x), int(roi.y), int(roi.w), int(roi.h))

    def _colorize_heatmap(self, norm: np.ndarray) -> np.ndarray:
        norm = np.clip(norm, 0.0, 1.0)

        r = np.clip(2.8 * norm - 1.2, 0.0, 1.0)
        g = np.clip(3.2 * norm - 0.2, 0.0, 1.0)
        b = np.clip(1.2 - 2.2 * norm, 0.0, 1.0)

        rgb = np.stack([r, g, b], axis=-1)
        rgb = np.power(rgb, 0.8)
        rgb = (rgb * 255.0).astype(np.uint8)
        return np.ascontiguousarray(rgb)

    def _rgb_to_pixmap(self, rgb: np.ndarray) -> QPixmap:
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format_RGB888).copy()
        return QPixmap.fromImage(qimg)

    def _fit_label_pixmap(self, rgb: np.ndarray, label: QLabel) -> QPixmap:
        pm = self._rgb_to_pixmap(rgb)
        return pm.scaled(
            label.size(),
            Qt.KeepAspectRatio,
            Qt.FastTransformation,
        )

    def _extract_roi_events(self, events, roi: Roi):
        x0, y0 = int(roi.x), int(roi.y)
        w, h = int(roi.w), int(roi.h)
        x1, y1 = x0 + w, y0 + h

        mask = (
            (events.x >= x0) & (events.x < x1) &
            (events.y >= y0) & (events.y < y1)
        )

        xs = events.x[mask] - x0
        ys = events.y[mask] - y0
        ts = events.t[mask]
        ps = events.p[mask]

        return xs, ys, ts, ps, w, h

    def _build_roi_heatmap(self, events, roi: Roi) -> np.ndarray:
        xs, ys, _ts, _ps, w, h = self._extract_roi_events(events, roi)

        heat = np.zeros((h, w), dtype=np.uint32)
        if xs.size > 0:
            np.add.at(heat, (ys, xs), 1)

        if heat.max() > 0:
            heat_f = np.log1p(heat.astype(np.float32))
            heat_f /= float(heat_f.max())
        else:
            heat_f = heat.astype(np.float32)

        rgb = self._colorize_heatmap(heat_f)

        target = 240
        scale = max(1, min(12, target // max(1, max(h, w))))
        if scale > 1:
            rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)

        return rgb

    def _time_to_rgb(self, t_norm: np.ndarray) -> np.ndarray:
        t_norm = np.clip(t_norm, 0.0, 1.0)

        r = np.clip(2.2 * t_norm - 0.2, 0.0, 1.0)
        g = np.clip(1.8 - 2.0 * np.abs(t_norm - 0.5), 0.0, 1.0)
        b = np.clip(1.2 - 2.0 * t_norm, 0.0, 1.0)

        return np.stack([r, g, b], axis=-1)

    def _build_roi_trail_map(self, events, roi: Roi, current_t_end_us: int) -> np.ndarray:
        xs, ys, ts, _ps, w, h = self._extract_roi_events(events, roi)

        canvas = np.zeros((h, w, 3), dtype=np.float32)

        if xs.size > 0:
            progressive_mask = ts < int(current_t_end_us)
            xs = xs[progressive_mask]
            ys = ys[progressive_mask]
            ts = ts[progressive_mask]

            if xs.size > 0:
                if ts.size > self.MAX_SPATIAL_POINTS:
                    step = int(np.ceil(ts.size / self.MAX_SPATIAL_POINTS))
                    xs = xs[::step]
                    ys = ys[::step]
                    ts = ts[::step]

                t_min = int(ts.min())
                t_max = int(ts.max())

                if t_max > t_min:
                    t_norm = (ts - t_min).astype(np.float64) / (t_max - t_min)
                else:
                    t_norm = np.zeros_like(ts, dtype=np.float32)

                colors = self._time_to_rgb(t_norm)

                np.add.at(canvas[..., 0], (ys, xs), colors[:, 0])
                np.add.at(canvas[..., 1], (ys, xs), colors[:, 1])
                np.add.at(canvas[..., 2], (ys, xs), colors[:, 2])

                canvas = np.log1p(canvas)
                m = float(canvas.max())
                if m > 0:
                    canvas /= m

        rgb = (canvas * 255.0).astype(np.uint8)
        rgb = np.ascontiguousarray(rgb)

        target = 240
        scale = max(1, min(12, target // max(1, max(h, w))))
        if scale > 1:
            rgb = np.repeat(np.repeat(rgb, scale, axis=0), scale, axis=1)

        return rgb

    def _build_activity_plot_payload(self, events, roi: Roi, roi_name: str, loaded_name: str, current_t_end_us: int) -> dict:
        _xs, _ys, ts, ps, _w, _h = self._extract_roi_events(events, roi)

        if ts.size == 0:
            return {
                "roi_name": roi_name,
                "loaded_name": loaded_name,
                "times_ms": np.array([0.0]),
                "total_counts": np.array([0]),
                "pos_counts": np.array([0]),
                "neg_counts": np.array([0]),
                "current_time_ms": current_t_end_us / 1000.0,
            }

        t0 = int(ts.min())
        t1 = int(ts.max())
        span_us = max(1, t1 - t0)

        n_bins = int(np.clip(span_us / 2000, 60, 300))
        edges = np.linspace(t0, t1, n_bins + 1)

        total_counts, _ = np.histogram(ts, bins=edges)
        pos_counts, _ = np.histogram(ts[ps > 0], bins=edges)
        neg_counts, _ = np.histogram(ts[ps <= 0], bins=edges)

        centers = 0.5 * (edges[:-1] + edges[1:])
        times_ms = centers / 1000.0

        return {
            "roi_name": roi_name,
            "loaded_name": loaded_name,
            "times_ms": times_ms,
            "total_counts": total_counts,
            "pos_counts": pos_counts,
            "neg_counts": neg_counts,
            "current_time_ms": current_t_end_us / 1000.0,
        }

    def _build_spatial_plot_payload(self, events, roi: Roi, roi_name: str, loaded_name: str) -> dict:
        xs, ys, ts, _ps, w, h = self._extract_roi_events(events, roi)

        if xs.size > self.MAX_SPATIAL_POINTS:
            step = int(np.ceil(xs.size / self.MAX_SPATIAL_POINTS))
            xs = xs[::step]
            ys = ys[::step]
            ts = ts[::step]

        return {
            "roi_name": roi_name,
            "loaded_name": loaded_name,
            "xs": xs,
            "ys": ys,
            "ts": ts,
            "roi_w": int(w),
            "roi_h": int(h),
            "n_events": int(xs.size),
        }

    def open_activity_plot(self) -> None:
        if self._last_plot_payload is None:
            QMessageBox.information(self, "Activity Plot", "No plot data available yet.")
            return

        if self._plot_window is None:
            self._plot_window = ActivityPlotWindow(self)

        self._plot_window.set_plot_data(**self._last_plot_payload)
        self._plot_window.show()
        self._plot_window.raise_()
        self._plot_window.activateWindow()

    def open_spatial_plot(self) -> None:
        if self._last_spatial_plot_payload is None:
            QMessageBox.information(self, "Spatial Plot", "No spatial plot data available yet.")
            return

        if self._spatial_plot_window is None:
            self._spatial_plot_window = SpatialPlotWindow(self)

        self._spatial_plot_window.set_plot_data(**self._last_spatial_plot_payload)
        self._spatial_plot_window.show()
        self._spatial_plot_window.raise_()
        self._spatial_plot_window.activateWindow()

    def set_analysis_data(
        self,
        *,
        project_name: str,
        loaded_name: str,
        events,
        hw,
        roi_name: str,
        roi: Roi,
        roi_color: str,
        current_t0_us: int,
        current_window_us: int,
    ) -> None:
        if events is None or hw is None or events.t.size == 0:
            self.clear_analysis()
            self.subtitle_label.setText("No dataset loaded.")
            return

        self._last_title = roi_name.replace(" ", "_") or "roi_analysis"

        self.title_label.setText(f'ROI Analysis — "{roi_name}"')
        self.subtitle_label.setText(
            f"Project: {project_name}\n"
            f"Source: {loaded_name}\n"
            f"ROI box: x={roi.x} y={roi.y} w={roi.w} h={roi.h} | color={roi_color}\n"
            "Unfiltered analysis. DERIVED heatmap: full recording, log-relative scale.\n"
            "DERIVED trail: history through playhead, time color and log-relative scale.\n"
            f"Spatial/trail presentations use at most {self.MAX_SPATIAL_POINTS:,} sampled events; statistics and CSV exports use every selected event."
        )

        full_t0 = int(events.t.min())
        full_t1 = int(events.t.max())
        full_window_us = max(1, full_t1 - full_t0 + 1)

        stats_key = (self._events_key(events), self._roi_key(roi))
        if getattr(self, "_full_stats_key", None) != stats_key:
            self._full_stats_key = stats_key
            self._full_stats = compute_roi_stats(events, hw, roi, full_t0, full_window_us)
        full_stats = self._full_stats

        curr_stats = compute_roi_stats(
            events=events,
            hw=hw,
            roi=roi,
            t0_us=int(current_t0_us),
            window_us=int(current_window_us),
        )

        roi_area = int(roi.w * roi.h)

        full_density = full_stats.n_events / roi_area if roi_area > 0 else 0.0
        curr_density = curr_stats.n_events / roi_area if roi_area > 0 else 0.0

        full_pos_pct = self._format_ratio_percent(full_stats.pos, full_stats.n_events)
        curr_pos_pct = self._format_ratio_percent(curr_stats.pos, curr_stats.n_events)

        self.full_stats_label.setText(
            "\n".join(
                [
                    f'Full ROI stats — "{roi_name}"',
                    f"Events: {full_stats.n_events:,}",
                    f"+ / − : {full_stats.pos:,} / {full_stats.neg:,}   ({full_pos_pct:.1f}% +)",
                    f"Events/ms: {full_stats.events_per_ms:.4f}",
                    f"Polarity ratio (+/−): {full_stats.polarity_ratio:.4f}",
                    f"Active pixels: {full_stats.active_pixels:,}",
                    f"ROI area: {roi_area:,} px",
                    f"Density: {full_density:.6f} ev/pixel",
                ]
            )
        )

        self.window_stats_label.setText(
            "\n".join(
                [
                    f'Current-window ROI stats — "{roi_name}"',
                    f"Events: {curr_stats.n_events:,}",
                    f"+ / − : {curr_stats.pos:,} / {curr_stats.neg:,}   ({curr_pos_pct:.1f}% +)",
                    f"Events/ms: {curr_stats.events_per_ms:.4f}",
                    f"Polarity ratio (+/−): {curr_stats.polarity_ratio:.4f}",
                    f"Active pixels: {curr_stats.active_pixels:,}",
                    f"ROI area: {roi_area:,} px",
                    f"Density: {curr_density:.6f} ev/pixel",
                ]
            )
        )

        current_t_end_us = int(current_t0_us + current_window_us)

        roi_key = self._roi_key(roi)
        events_key = self._events_key(events)

        cache_invalid = (roi_key != self._cached_roi_key) or (events_key != self._cached_events_key)

        if cache_invalid:
            self._cached_roi_key = roi_key
            self._cached_events_key = events_key
            self._cached_heatmap_rgb = self._build_roi_heatmap(events, roi)
            self._cached_spatial_payload = self._build_spatial_plot_payload(
                events=events,
                roi=roi,
                roi_name=roi_name,
                loaded_name=loaded_name,
            )
            self._last_trail_update_walltime = 0.0
            self._last_trail_playhead_us = None
            self._last_plot_payload = self._build_activity_plot_payload(
                events, roi, roi_name, loaded_name, current_t_end_us)

        if self._cached_heatmap_rgb is not None:
            self._last_heatmap_rgb = self._cached_heatmap_rgb
            self.heatmap_label.setPixmap(self._fit_label_pixmap(self._last_heatmap_rgb, self.heatmap_label))
            self.heatmap_label.setText("")

        now = time.monotonic()
        playhead_changed_enough = (
            self._last_trail_playhead_us is None
            or abs(current_t_end_us - self._last_trail_playhead_us) >= self.MIN_PLAYHEAD_DELTA_US
        )
        time_interval_elapsed = (now - self._last_trail_update_walltime) >= self.TRAIL_UPDATE_INTERVAL_SEC

        if cache_invalid or self._last_trail_playhead_us != current_t_end_us:
            self._last_trail_rgb = self._build_roi_trail_map(events, roi, current_t_end_us)
            self._last_trail_update_walltime = now
            self._last_trail_playhead_us = current_t_end_us

        if self._last_trail_rgb is not None:
            self.trail_label.setPixmap(self._fit_label_pixmap(self._last_trail_rgb, self.trail_label))
            self.trail_label.setText("")

        self._last_spatial_plot_payload = self._cached_spatial_payload

        if self._plot_window is not None and self._plot_window.isVisible():
            self._last_plot_payload = self._build_activity_plot_payload(
                events=events,
                roi=roi,
                roi_name=roi_name,
                loaded_name=loaded_name,
                current_t_end_us=current_t_end_us,
            )
            self._plot_window.set_plot_data(**self._last_plot_payload)
        elif self._last_plot_payload is None:
            self._last_plot_payload = self._build_activity_plot_payload(
                events=events,
                roi=roi,
                roi_name=roi_name,
                loaded_name=loaded_name,
                current_t_end_us=current_t_end_us,
            )

        if (
            self._spatial_plot_window is not None
            and self._spatial_plot_window.isVisible()
            and self._last_spatial_plot_payload is not None
        ):
            self._spatial_plot_window.set_plot_data(**self._last_spatial_plot_payload)

        self.btn_export_heatmap.setEnabled(True)
        self.btn_export_trail.setEnabled(True)
        self.btn_open_plot.setEnabled(True)
        self.btn_open_spatial_plot.setEnabled(True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)

        if self._last_heatmap_rgb is not None:
            self.heatmap_label.setPixmap(
                self._fit_label_pixmap(self._last_heatmap_rgb, self.heatmap_label)
            )

        if self._last_trail_rgb is not None:
            self.trail_label.setPixmap(
                self._fit_label_pixmap(self._last_trail_rgb, self.trail_label)
            )

    def export_heatmap_png(self) -> None:
        if self._last_heatmap_rgb is None:
            QMessageBox.information(self, "Export Heatmap", "No heatmap available yet.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Heatmap PNG",
            f"{self._last_title}_heatmap.png",
            "PNG Image (*.png)",
        )
        if not out_path:
            return

        pm = self._rgb_to_pixmap(self._last_heatmap_rgb)
        if not pm.save(out_path, "PNG"):
            QMessageBox.critical(self, "Export Heatmap", "Failed to save PNG.")
            return

        QMessageBox.information(self, "Export Heatmap", f"Saved:\n{out_path}")

    def export_trail_png(self) -> None:
        if self._last_trail_rgb is None:
            QMessageBox.information(self, "Export Trail", "No trail map available yet.")
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Trail PNG",
            f"{self._last_title}_trail.png",
            "PNG Image (*.png)",
        )
        if not out_path:
            return

        pm = self._rgb_to_pixmap(self._last_trail_rgb)
        if not pm.save(out_path, "PNG"):
            QMessageBox.critical(self, "Export Trail", "Failed to save PNG.")
            return

        QMessageBox.information(self, "Export Trail", f"Saved:\n{out_path}")
