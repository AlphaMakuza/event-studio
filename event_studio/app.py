from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional, Tuple, List

import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
    QListWidget,
    QListWidgetItem,
    QInputDialog,
    QCheckBox,
    QColorDialog,
    QComboBox,
)

from .convert import convert_dat_to_h5_windows, h5_to_csv_windows
from .viewer import (
    load_events_from_csv,
    infer_hw,
    accumulate_frame,
    compute_roi_stats,
)
from .roi_label import ROILabel, Roi
from .project_utils import (
    create_project_dir,
    metadata_json_path,
    now_iso,
    rename_project,
    save_project_bundle,
    session_json_path,
    touch_project_opened,
)
from .project_browser import ProjectBrowser
from .analysis_window import ROIAnalysisPanel
from .timeline_slider import TimelineSlider


def _try_show_boot(app: QApplication) -> None:
    try:
        from .boot import show_boot  # type: ignore
        show_boot(app)  # type: ignore
    except Exception:
        return


ROI_COLOR_PALETTE = [
    "#ff3b30",
    "#34c759",
    "#007aff",
    "#ff9500",
    "#af52de",
    "#ffd60a",
    "#64d2ff",
    "#ff2d55",
]

SLICE_COLOR_PALETTE = [
    "#34c759",
    "#64d2ff",
    "#ffd60a",
    "#ff9500",
    "#af52de",
    "#ff2d55",
    "#007aff",
    "#ff3b30",
]

VIEW_MODE_RAW = "RAW"
VIEW_MODE_HEATMAP = "HEATMAP"
VIEW_MODE_TRAIL = "TRAIL"
VIEW_MODE_MOTION_ARROWS = "MOTION ARROWS"


@dataclass
class NamedROI:
    name: str
    roi: Roi
    visible: bool = True
    color: str = "#ff3b30"


@dataclass
class Slice:
    name: str
    t0: int
    t1: int
    roi_index: Optional[int] = None
    color: str = "#34c759"


class MainWindow(QMainWindow):
    def __init__(self, browser_ref: ProjectBrowser | None = None, project_dir: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Event-Based Studio")

        self.project_root = Path(__file__).resolve().parents[1]
        self.data_dir = self.project_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.projects_root = self.project_root / "projects"
        self.projects_root.mkdir(parents=True, exist_ok=True)

        self.browser_ref = browser_ref
        self.current_project_dir: Optional[Path] = Path(project_dir) if project_dir else None
        self.project_name: str = self.current_project_dir.name if self.current_project_dir else "Untitled Project"

        self.events = None
        self.hw: Optional[Tuple[int, int]] = None
        self.t_min: int = 0
        self.t_max: int = 0
        self.loaded_name: str = ""
        self.loaded_csv_path: str = ""
        self.current_session_path: str = ""

        self.is_playing = False
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._on_tick)

        self._candidate_roi: Optional[Roi] = None
        self.rois: List[NamedROI] = []
        self.active_roi_index: Optional[int] = None

        self.slices: List[Slice] = []
        self.loop_slice_index: Optional[int] = None

        self.current_frame: Optional[np.ndarray] = None
        self.current_view_mode: str = VIEW_MODE_RAW

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        root.addLayout(top, stretch=1)

        self.view = ROILabel()
        self.view.setMinimumSize(760, 500)
        self.view.set_help_text("File → Import .dat to preview")
        self.view.roiChanged.connect(self._on_candidate_roi_changed)
        self.view.roiMoved.connect(self._on_active_roi_moved)
        top.addWidget(self.view, stretch=5)

        self.middle_panel = QVBoxLayout()
        self.middle_panel.setSpacing(10)
        top.addLayout(self.middle_panel, stretch=2)

        # -------------------------
        # Studio View
        # -------------------------
        view_box = QGroupBox("Studio View")
        view_layout = QVBoxLayout(view_box)
        view_layout.setSpacing(6)

        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems([
            VIEW_MODE_RAW,
            VIEW_MODE_HEATMAP,
            VIEW_MODE_TRAIL,
            VIEW_MODE_MOTION_ARROWS,
        ])
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode_changed)
        view_layout.addWidget(self.view_mode_combo)

        self.view_mode_hint = QLabel(
            "RAW = normal event frame\n"
            "HEATMAP = density in current window\n"
            "TRAIL = time-colored motion trail\n"
            "MOTION ARROWS = object silhouette + direction vectors"
        )
        self.view_mode_hint.setWordWrap(True)
        view_layout.addWidget(self.view_mode_hint)

        arrow_row1 = QHBoxLayout()
        arrow_row1.addWidget(QLabel("Grid"))
        self.arrow_grid_spin = QSpinBox()
        self.arrow_grid_spin.setRange(8, 128)
        self.arrow_grid_spin.setValue(24)
        self.arrow_grid_spin.valueChanged.connect(self._render_from_ui)
        arrow_row1.addWidget(self.arrow_grid_spin)

        arrow_row1.addWidget(QLabel("Scale"))
        self.arrow_scale_spin = QDoubleSpinBox()
        self.arrow_scale_spin.setRange(0.2, 10.0)
        self.arrow_scale_spin.setSingleStep(0.2)
        self.arrow_scale_spin.setValue(2.0)
        self.arrow_scale_spin.valueChanged.connect(self._render_from_ui)
        arrow_row1.addWidget(self.arrow_scale_spin)
        view_layout.addLayout(arrow_row1)

        arrow_row2 = QHBoxLayout()
        arrow_row2.addWidget(QLabel("Min events"))
        self.arrow_min_events_spin = QSpinBox()
        self.arrow_min_events_spin.setRange(1, 500)
        self.arrow_min_events_spin.setValue(10)
        self.arrow_min_events_spin.valueChanged.connect(self._render_from_ui)
        arrow_row2.addWidget(self.arrow_min_events_spin)

        arrow_row2.addWidget(QLabel("Silhouette"))
        self.arrow_silhouette_spin = QDoubleSpinBox()
        self.arrow_silhouette_spin.setRange(0.0, 1.0)
        self.arrow_silhouette_spin.setSingleStep(0.05)
        self.arrow_silhouette_spin.setValue(0.40)
        self.arrow_silhouette_spin.valueChanged.connect(self._render_from_ui)
        arrow_row2.addWidget(self.arrow_silhouette_spin)
        view_layout.addLayout(arrow_row2)

        self.middle_panel.addWidget(view_box)

        # -------------------------
        # ROIs
        # -------------------------
        roi_box = QGroupBox("ROIs")
        roi_layout = QVBoxLayout(roi_box)
        roi_layout.setSpacing(6)

        self.roi_status = QLabel(
            "Candidate: None (drag on image to create)\n"
            "Tip: select a visible ROI below, then drag inside it to move it or drag a corner to resize it."
        )
        self.roi_status.setWordWrap(True)
        roi_layout.addWidget(self.roi_status)

        self.chk_show_rois = QCheckBox("Show ROI overlays")
        self.chk_show_rois.setChecked(True)
        self.chk_show_rois.stateChanged.connect(self._on_toggle_roi_overlays)
        roi_layout.addWidget(self.chk_show_rois)

        self.btn_add_roi = QPushButton("Add ROI (name it)")
        self.btn_add_roi.setEnabled(False)
        self.btn_add_roi.clicked.connect(self._add_roi_from_candidate)
        roi_layout.addWidget(self.btn_add_roi)

        self.btn_clear_candidate = QPushButton("Clear candidate (right-click too)")
        self.btn_clear_candidate.clicked.connect(self._clear_candidate_roi)
        roi_layout.addWidget(self.btn_clear_candidate)

        self.roi_list = QListWidget()
        self.roi_list.setMinimumHeight(160)
        self.roi_list.itemSelectionChanged.connect(self._on_roi_selection_changed)
        self.roi_list.itemChanged.connect(self._on_roi_item_changed)
        roi_layout.addWidget(self.roi_list)

        row_edit = QHBoxLayout()
        self.btn_rename_roi = QPushButton("Rename ROI")
        self.btn_rename_roi.clicked.connect(self._rename_selected_roi)
        row_edit.addWidget(self.btn_rename_roi)

        self.btn_set_roi_color = QPushButton("Set ROI Color")
        self.btn_set_roi_color.clicked.connect(self._set_selected_roi_color)
        row_edit.addWidget(self.btn_set_roi_color)
        roi_layout.addLayout(row_edit)

        row_color = QHBoxLayout()
        self.btn_cycle_roi_color = QPushButton("Next Palette Color")
        self.btn_cycle_roi_color.clicked.connect(self._cycle_selected_roi_color)
        row_color.addWidget(self.btn_cycle_roi_color)
        roi_layout.addLayout(row_color)

        row_manage = QHBoxLayout()
        self.btn_duplicate_roi = QPushButton("Duplicate ROI")
        self.btn_duplicate_roi.clicked.connect(self._duplicate_selected_roi)
        row_manage.addWidget(self.btn_duplicate_roi)

        self.btn_export_roi = QPushButton("Export selected ROI CSV")
        self.btn_export_roi.setEnabled(False)
        self.btn_export_roi.clicked.connect(self._export_selected_roi_csv)
        row_manage.addWidget(self.btn_export_roi)
        roi_layout.addLayout(row_manage)

        row_analysis = QHBoxLayout()
        self.btn_toggle_analysis = QPushButton("Open ROI Analysis")
        self.btn_toggle_analysis.setEnabled(False)
        self.btn_toggle_analysis.clicked.connect(self._toggle_analysis_panel)
        row_analysis.addWidget(self.btn_toggle_analysis)
        roi_layout.addLayout(row_analysis)

        row = QHBoxLayout()
        self.btn_delete_roi = QPushButton("Delete selected")
        self.btn_delete_roi.clicked.connect(self._delete_selected_roi)
        row.addWidget(self.btn_delete_roi)

        self.btn_clear_all_rois = QPushButton("Clear all")
        self.btn_clear_all_rois.clicked.connect(self._clear_all_rois)
        row.addWidget(self.btn_clear_all_rois)
        roi_layout.addLayout(row)

        self.middle_panel.addWidget(roi_box)

        # -------------------------
        # Slices
        # -------------------------
        slice_box = QGroupBox("Slices")
        slice_layout = QVBoxLayout(slice_box)
        slice_layout.setSpacing(6)

        self.slice_hint = QLabel("Save current time window (and optional active ROI).")
        self.slice_hint.setWordWrap(True)
        slice_layout.addWidget(self.slice_hint)

        self.btn_add_slice = QPushButton("Add slice from current view")
        self.btn_add_slice.setEnabled(False)
        self.btn_add_slice.clicked.connect(self._add_slice_from_current_view)
        slice_layout.addWidget(self.btn_add_slice)

        self.slice_list = QListWidget()
        self.slice_list.setMinimumHeight(140)
        self.slice_list.itemSelectionChanged.connect(self._on_slice_selection_changed)
        self.slice_list.itemDoubleClicked.connect(self._jump_to_selected_slice)
        slice_layout.addWidget(self.slice_list)

        slice_edit_row = QHBoxLayout()
        self.btn_rename_slice = QPushButton("Rename Slice")
        self.btn_rename_slice.setEnabled(False)
        self.btn_rename_slice.clicked.connect(self._rename_selected_slice)
        slice_edit_row.addWidget(self.btn_rename_slice)

        self.btn_set_slice_color = QPushButton("Set Slice Color")
        self.btn_set_slice_color.setEnabled(False)
        self.btn_set_slice_color.clicked.connect(self._set_selected_slice_color)
        slice_edit_row.addWidget(self.btn_set_slice_color)
        slice_layout.addLayout(slice_edit_row)

        slice_loop_row = QHBoxLayout()
        self.btn_loop_slice = QPushButton("Loop Selected Slice")
        self.btn_loop_slice.setEnabled(False)
        self.btn_loop_slice.clicked.connect(self._toggle_loop_selected_slice)
        slice_loop_row.addWidget(self.btn_loop_slice)
        slice_layout.addLayout(slice_loop_row)

        slice_row = QHBoxLayout()
        self.btn_jump_slice = QPushButton("Jump to slice")
        self.btn_jump_slice.setEnabled(False)
        self.btn_jump_slice.clicked.connect(self._jump_to_selected_slice)
        slice_row.addWidget(self.btn_jump_slice)

        self.btn_export_slice = QPushButton("Export slice CSV")
        self.btn_export_slice.setEnabled(False)
        self.btn_export_slice.clicked.connect(self._export_selected_slice_csv)
        slice_row.addWidget(self.btn_export_slice)
        slice_layout.addLayout(slice_row)

        slice_row2 = QHBoxLayout()
        self.btn_delete_slice = QPushButton("Delete slice")
        self.btn_delete_slice.setEnabled(False)
        self.btn_delete_slice.clicked.connect(self._delete_selected_slice)
        slice_row2.addWidget(self.btn_delete_slice)

        self.btn_clear_slices = QPushButton("Clear slices")
        self.btn_clear_slices.setEnabled(False)
        self.btn_clear_slices.clicked.connect(self._clear_slices)
        slice_row2.addWidget(self.btn_clear_slices)
        slice_layout.addLayout(slice_row2)

        self.middle_panel.addWidget(slice_box)

        # -------------------------
        # Stats
        # -------------------------
        stats_box = QGroupBox("Stats")
        stats_layout = QVBoxLayout(stats_box)

        self.stats_global = QLabel("Global: —")
        self.stats_window = QLabel("Window: —")
        self.stats_roi = QLabel("Active ROI in window: —")
        for lab in (self.stats_global, self.stats_window, self.stats_roi):
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            stats_layout.addWidget(lab)

        self.middle_panel.addWidget(stats_box)
        self.middle_panel.addStretch(1)

        self.analysis_panel = ROIAnalysisPanel()
        self.analysis_panel.closeRequested.connect(self._hide_analysis_panel)
        self.analysis_panel.setVisible(False)
        top.addWidget(self.analysis_panel, stretch=2)

        # -------------------------
        # Bottom controls
        # -------------------------
        controls = QHBoxLayout()
        controls.setSpacing(10)
        root.addLayout(controls)

        self.play_btn = QPushButton("Play")
        self.play_btn.setEnabled(False)
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)

        controls.addWidget(QLabel("Time"))
        self.timeline = TimelineSlider(Qt.Horizontal)
        self.timeline.setRange(0, 1000)
        self.timeline.setValue(0)
        self.timeline.setEnabled(False)
        self.timeline.valueChanged.connect(self._render_from_ui)
        self.timeline.sliceSelected.connect(self._on_timeline_slice_selected)
        self.timeline.sliceEdited.connect(self._on_timeline_slice_edited)
        controls.addWidget(self.timeline, stretch=1)

        self.time_label = QLabel("t = —")
        controls.addWidget(self.time_label)

        controls.addWidget(QLabel("Window:"))
        self.window_ms = QSpinBox()
        self.window_ms.setRange(1, 5000)
        self.window_ms.setValue(50)
        self.window_ms.setSuffix(" ms")
        self.window_ms.setEnabled(False)
        self.window_ms.valueChanged.connect(self._render_from_ui)
        controls.addWidget(self.window_ms)

        # -------------------------
        # Menu
        # -------------------------
        file_menu = self.menuBar().addMenu("&File")

        import_action = QAction("Import .dat", self)
        import_action.triggered.connect(self.on_import_dat_clicked)
        file_menu.addAction(import_action)

        save_project_action = QAction("Save Project", self)
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        rename_project_action = QAction("Rename Project", self)
        rename_project_action.triggered.connect(self.rename_current_project)
        file_menu.addAction(rename_project_action)

        file_menu.addSeparator()

        reset_action = QAction("Reset View", self)
        reset_action.triggered.connect(self._reset_view)
        file_menu.addAction(reset_action)

        self.statusBar().showMessage("Ready")
        self._update_window_title()

        if self.current_project_dir is not None:
            self._load_project_from_dir(self.current_project_dir)

    # =========================================================
    # General helpers
    # =========================================================
    def _update_window_title(self) -> None:
        self.setWindowTitle(f"Event-Based Studio — {self.project_name}")

    def _next_default_roi_color(self) -> str:
        return ROI_COLOR_PALETTE[len(self.rois) % len(ROI_COLOR_PALETTE)]

    def _next_default_slice_color(self) -> str:
        return SLICE_COLOR_PALETTE[len(self.slices) % len(SLICE_COLOR_PALETTE)]

    def _make_color_icon(self, color_hex: str) -> QIcon:
        pix = QPixmap(14, 14)
        pix.fill(QColor(color_hex))
        return QIcon(pix)

    def _sanitize_name_for_file(self, name: str) -> str:
        safe = name.strip().replace(" ", "_")
        for ch in '<>:"/\\|?*':
            safe = safe.replace(ch, "_")
        return safe or "unnamed"

    def _toggle_analysis_panel(self) -> None:
        if self.analysis_panel.isVisible():
            self._hide_analysis_panel()
        else:
            self._show_analysis_panel()

    def _show_analysis_panel(self) -> None:
        if self.events is None or self.active_roi_index is None:
            return
        self.analysis_panel.setVisible(True)
        self.btn_toggle_analysis.setText("Hide ROI Analysis")
        self._refresh_analysis_panel()

    def _hide_analysis_panel(self) -> None:
        self.analysis_panel.setVisible(False)
        self.btn_toggle_analysis.setText("Open ROI Analysis")

    def _on_view_mode_changed(self, mode: str) -> None:
        self.current_view_mode = mode
        self._render_from_ui()

    def closeEvent(self, event) -> None:
        if self.browser_ref is not None:
            self.browser_ref.refresh_projects()
            self.browser_ref.show()
            self.browser_ref.raise_()
            self.browser_ref.activateWindow()
        super().closeEvent(event)

    # =========================================================
    # Data loading / saving
    # =========================================================
    def on_import_dat_clicked(self) -> None:
        dat_file, _ = QFileDialog.getOpenFileName(
            self,
            "Import .dat",
            str(Path.home()),
            "Event files (*.dat)",
        )
        if not dat_file:
            return

        out_dir = self.project_root / "data" / "converted"
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.statusBar().showMessage("Converting .dat → .h5 (WSL/OpenEB)…")
            QApplication.processEvents()
            h5_path = convert_dat_to_h5_windows(dat_file, out_dir=out_dir)

            self.statusBar().showMessage("Exporting .h5 → .csv (WSL/OpenEB)…")
            QApplication.processEvents()
            csv_path = out_dir / (Path(h5_path).stem + ".csv")
            csv_path = h5_to_csv_windows(h5_path, out_csv_path=csv_path)

            if not self.current_project_dir:
                guess_name = Path(dat_file).stem
                self.current_project_dir = create_project_dir(self.projects_root, guess_name)
                self.project_name = self.current_project_dir.name
                self._update_window_title()

            self._load_csv_into_app(
                csv_path=Path(csv_path),
                loaded_name=Path(dat_file).stem,
                reset_annotations=True,
            )

        except Exception as e:
            self.statusBar().showMessage("Import failed")
            QMessageBox.critical(self, "Import failed", str(e))
            return

        QMessageBox.information(
            self,
            "Import complete",
            f"Converted and saved to:\n{h5_path}\n{csv_path}",
        )

    def _load_csv_into_app(
        self,
        csv_path: Path,
        loaded_name: str,
        reset_annotations: bool = True,
    ) -> None:
        self.statusBar().showMessage("Loading events from CSV…")
        QApplication.processEvents()

        events = load_events_from_csv(csv_path, max_events=2_000_000)
        hw = infer_hw(events)

        self.events = events
        self.hw = hw
        self.t_min = int(events.t.min()) if events.t.size else 0
        self.t_max = int(events.t.max()) if events.t.size else 0
        self.loaded_name = loaded_name
        self.loaded_csv_path = str(csv_path)

        if events.t.size == 0:
            QMessageBox.warning(self, "Empty", "CSV contains 0 events.")
            self._reset_view()
            return

        self.timeline.setEnabled(True)
        self.window_ms.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.btn_add_slice.setEnabled(True)

        self.is_playing = False
        self.play_timer.stop()
        self.play_btn.setText("Play")

        if reset_annotations:
            self._candidate_roi = None
            self.view.clear_roi()
            self.rois = []
            self.active_roi_index = None
            self._rebuild_roi_list()
            self._push_rois_to_view()

            self.slices = []
            self.loop_slice_index = None
            self._rebuild_slice_list()

            self.chk_show_rois.setChecked(True)
            self.window_ms.setValue(50)
            self.timeline.setValue(0)
            self.current_view_mode = VIEW_MODE_RAW
            self.view_mode_combo.setCurrentText(VIEW_MODE_RAW)

        self._render_from_ui()
        self._update_stats_global()
        self._update_timeline_slice_regions()

        self.statusBar().showMessage(
            f"Loaded {len(events.t):,} events | {hw[1]}x{hw[0]} | {Path(csv_path).name}"
        )

    def _roi_to_dict(self, roi_item: NamedROI) -> dict:
        return {
            "name": roi_item.name,
            "x": int(roi_item.roi.x),
            "y": int(roi_item.roi.y),
            "w": int(roi_item.roi.w),
            "h": int(roi_item.roi.h),
            "visible": bool(roi_item.visible),
            "color": roi_item.color,
        }

    def _slice_to_dict(self, s: Slice) -> dict:
        return {
            "name": s.name,
            "t0": int(s.t0),
            "t1": int(s.t1),
            "roi_index": None if s.roi_index is None else int(s.roi_index),
            "color": s.color,
        }

    def _build_session_dict(self) -> dict:
        return {
            "format_version": 6,
            "project_name": self.project_name,
            "source": {
                "loaded_name": self.loaded_name,
                "csv_path": self.loaded_csv_path,
                "max_events": 2_000_000,
            },
            "view": {
                "timeline_value": int(self.timeline.value()),
                "window_ms": int(self.window_ms.value()),
                "is_playing": bool(self.is_playing),
                "show_roi_overlays": bool(self.chk_show_rois.isChecked()),
                "active_roi_index": self.active_roi_index,
                "loop_slice_index": self.loop_slice_index,
                "view_mode": self.current_view_mode,
                "arrow_grid": int(self.arrow_grid_spin.value()),
                "arrow_scale": float(self.arrow_scale_spin.value()),
                "arrow_min_events": int(self.arrow_min_events_spin.value()),
                "arrow_silhouette": float(self.arrow_silhouette_spin.value()),
            },
            "rois": [self._roi_to_dict(r) for r in self.rois],
            "slices": [self._slice_to_dict(s) for s in self.slices],
            "saved_at": now_iso(),
        }

    def _generate_preview_frames(self, n_frames: int = 10) -> list[np.ndarray]:
        if self.events is None or self.hw is None or self.events.t.size == 0:
            return []

        if self.t_max <= self.t_min:
            if self.current_frame is not None:
                return [self.current_frame.copy()]
            return []

        window_us = int(self.window_ms.value() * 1000)
        starts = np.linspace(
            self.t_min,
            max(self.t_min, self.t_max - window_us),
            n_frames,
            dtype=np.int64,
        )

        frames: list[np.ndarray] = []
        for t0 in starts.tolist():
            frame = self._render_mode_frame(int(t0), window_us)
            frames.append(frame)
        return frames

    def save_project(self) -> None:
        if self.current_project_dir is None:
            name_guess = self.loaded_name or "Untitled Project"
            self.current_project_dir = create_project_dir(self.projects_root, name_guess)
            self.project_name = self.current_project_dir.name
            self._update_window_title()

        if self.events is None or not self.loaded_csv_path:
            QMessageBox.warning(self, "Save Project", "Load a dataset before saving the project.")
            return

        session_data = self._build_session_dict()
        thumb = self.current_frame.copy() if self.current_frame is not None else None
        previews = self._generate_preview_frames(n_frames=10)

        try:
            save_project_bundle(
                project_dir=self.current_project_dir,
                project_name=self.project_name,
                session_data=session_data,
                thumbnail_frame=thumb,
                preview_frames=previews,
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Project", f"Failed to save project:\n{e}")
            return

        self.current_session_path = str(session_json_path(self.current_project_dir))
        self.statusBar().showMessage(f"Project saved: {self.current_project_dir}")

        if self.browser_ref is not None:
            self.browser_ref.refresh_projects()

    def rename_current_project(self) -> None:
        if self.current_project_dir is None:
            QMessageBox.information(self, "Rename Project", "Create or open a project first.")
            return

        name, ok = QInputDialog.getText(self, "Rename Project", "Project name:", text=self.project_name)
        if not ok:
            return

        name = name.strip()
        if not name:
            return

        rename_project(self.current_project_dir, name)
        self.project_name = name
        self._update_window_title()

        if self.browser_ref is not None:
            self.browser_ref.refresh_projects()

    def _load_project_from_dir(self, project_dir: Path) -> None:
        self.current_project_dir = Path(project_dir)
        self.project_name = self.current_project_dir.name
        self._update_window_title()

        touch_project_opened(self.current_project_dir)

        sess_path = session_json_path(self.current_project_dir)
        meta_path = metadata_json_path(self.current_project_dir)

        if meta_path.exists():
            try:
                with meta_path.open("r", encoding="utf-8") as f:
                    meta = json.load(f)
                self.project_name = meta.get("project_name", self.project_name)
                self._update_window_title()
            except Exception:
                pass

        if sess_path.exists():
            try:
                with sess_path.open("r", encoding="utf-8") as f:
                    session = json.load(f)
                self._restore_session(session)
                self.current_session_path = str(sess_path)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Project Load Warning",
                    f"Project opened, but session restore failed:\n{e}"
                )

    def _restore_session(self, session: dict) -> None:
        version = session.get("format_version")
        if version not in (1, 2, 3, 4, 5, 6):
            raise ValueError(f"Unsupported session format version: {version}")

        self.project_name = session.get("project_name", self.project_name)
        self._update_window_title()

        source = session.get("source", {})
        view = session.get("view", {})
        rois_data = session.get("rois", [])
        slices_data = session.get("slices", [])

        csv_path_str = source.get("csv_path", "")
        if not csv_path_str:
            raise ValueError("Session is missing source.csv_path")

        csv_path = Path(csv_path_str)
        if not csv_path.exists():
            raise FileNotFoundError(
                f"Source CSV not found:\n{csv_path}\n\n"
                "Move the CSV back to that location or edit the session JSON."
            )

        loaded_name = source.get("loaded_name", "") or csv_path.stem
        max_events = int(source.get("max_events", 2_000_000))

        self.statusBar().showMessage("Loading session dataset…")
        QApplication.processEvents()

        events = load_events_from_csv(csv_path, max_events=max_events)
        hw = infer_hw(events)

        self.events = events
        self.hw = hw
        self.t_min = int(events.t.min()) if events.t.size else 0
        self.t_max = int(events.t.max()) if events.t.size else 0
        self.loaded_name = loaded_name
        self.loaded_csv_path = str(csv_path)

        self.timeline.setEnabled(True)
        self.window_ms.setEnabled(True)
        self.play_btn.setEnabled(True)
        self.btn_add_slice.setEnabled(True)

        self.is_playing = False
        self.play_timer.stop()
        self.play_btn.setText("Play")

        self.rois = []
        for item in rois_data:
            try:
                roi = Roi(
                    x=int(item["x"]),
                    y=int(item["y"]),
                    w=int(item["w"]),
                    h=int(item["h"]),
                )
                self.rois.append(
                    NamedROI(
                        name=str(item.get("name", f"ROI {len(self.rois) + 1}")),
                        roi=roi,
                        visible=bool(item.get("visible", True)),
                        color=str(item.get("color", self._next_default_roi_color())),
                    )
                )
            except Exception:
                continue

        self.slices = []
        for i, item in enumerate(slices_data):
            try:
                roi_index_raw = item.get("roi_index", None)
                roi_index = None if roi_index_raw is None else int(roi_index_raw)
                if roi_index is not None and not (0 <= roi_index < len(self.rois)):
                    roi_index = None

                self.slices.append(
                    Slice(
                        name=str(item.get("name", f"Slice {len(self.slices) + 1}")),
                        t0=int(item["t0"]),
                        t1=int(item["t1"]),
                        roi_index=roi_index,
                        color=str(item.get("color", SLICE_COLOR_PALETTE[i % len(SLICE_COLOR_PALETTE)])),
                    )
                )
            except Exception:
                continue

        timeline_value = int(view.get("timeline_value", 0))
        timeline_value = max(self.timeline.minimum(), min(self.timeline.maximum(), timeline_value))

        window_value = int(view.get("window_ms", 50))
        window_value = max(self.window_ms.minimum(), min(self.window_ms.maximum(), window_value))

        active_roi_index_raw = view.get("active_roi_index", None)
        if active_roi_index_raw is None:
            self.active_roi_index = None
        else:
            active_idx = int(active_roi_index_raw)
            self.active_roi_index = active_idx if 0 <= active_idx < len(self.rois) else None

        loop_slice_index_raw = view.get("loop_slice_index", None)
        if loop_slice_index_raw is None:
            self.loop_slice_index = None
        else:
            idx = int(loop_slice_index_raw)
            self.loop_slice_index = idx if 0 <= idx < len(self.slices) else None

        self.current_view_mode = str(view.get("view_mode", VIEW_MODE_RAW))
        if self.current_view_mode not in {
            VIEW_MODE_RAW,
            VIEW_MODE_HEATMAP,
            VIEW_MODE_TRAIL,
            VIEW_MODE_MOTION_ARROWS,
        }:
            self.current_view_mode = VIEW_MODE_RAW

        show_rois = bool(view.get("show_roi_overlays", True))
        should_resume_playing = bool(view.get("is_playing", False))

        self.arrow_grid_spin.setValue(int(view.get("arrow_grid", 24)))
        self.arrow_scale_spin.setValue(float(view.get("arrow_scale", 2.0)))
        self.arrow_min_events_spin.setValue(int(view.get("arrow_min_events", 10)))
        self.arrow_silhouette_spin.setValue(float(view.get("arrow_silhouette", 0.40)))

        self._candidate_roi = None
        self.view.clear_roi()

        self.chk_show_rois.blockSignals(True)
        self.chk_show_rois.setChecked(show_rois)
        self.chk_show_rois.blockSignals(False)
        self.view.set_show_overlays(show_rois)

        self.view_mode_combo.blockSignals(True)
        self.view_mode_combo.setCurrentText(self.current_view_mode)
        self.view_mode_combo.blockSignals(False)

        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._rebuild_slice_list()
        self._update_timeline_slice_regions()
        self._update_loop_button_text()

        self.window_ms.blockSignals(True)
        self.window_ms.setValue(window_value)
        self.window_ms.blockSignals(False)

        self.timeline.blockSignals(True)
        self.timeline.setValue(timeline_value)
        self.timeline.blockSignals(False)

        self._render_from_ui()
        self._update_stats_global()
        self._update_roi_status_label()

        if should_resume_playing:
            self.is_playing = False
            self.play_btn.setText("Play")
            self._toggle_play()
        else:
            self.is_playing = False
            self.play_timer.stop()
            self.play_btn.setText("Play")

    # =========================================================
    # Time helpers
    # =========================================================
    def _format_ratio_percent(self, pos: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return 100.0 * pos / total

    def _current_window(self) -> Tuple[int, int]:
        if self.events is None:
            return (0, 0)
        frac = self.timeline.value() / 1000.0
        t0 = int(self.t_min + frac * max(0, self.t_max - self.t_min))
        t1 = t0 + int(self.window_ms.value() * 1000)
        return t0, t1

    def _time_us_to_slider_value(self, t_us: int) -> int:
        if self.t_max <= self.t_min:
            return 0
        frac = (t_us - self.t_min) / max(1, self.t_max - self.t_min)
        frac = max(0.0, min(1.0, frac))
        return int(round(frac * 1000))

    def _slider_value_to_time_us(self, value: int) -> int:
        if self.t_max <= self.t_min:
            return self.t_min
        frac = value / 1000.0
        return int(round(self.t_min + frac * (self.t_max - self.t_min)))

    def _update_timeline_slice_regions(self) -> None:
        if self.events is None or not self.slices:
            self.timeline.clear_slice_regions()
            return

        selected_index = self.slice_list.currentRow()
        regions = []

        for i, s in enumerate(self.slices):
            start_v = self._time_us_to_slider_value(s.t0)
            end_v = self._time_us_to_slider_value(s.t1)
            if end_v <= start_v:
                end_v = start_v + 1

            regions.append(
                {
                    "index": i,
                    "start_value": start_v,
                    "end_value": end_v,
                    "color": s.color,
                }
            )

        self.timeline.set_slice_regions(regions, selected_index=selected_index if selected_index >= 0 else None)

    # =========================================================
    # Rendering helpers
    # =========================================================
    def _extract_window_batch(self, t0: int, t1: int):
        if self.events is None:
            return None
        mask = (self.events.t >= t0) & (self.events.t < t1)
        if not np.any(mask):
            return None
        return replace(
            self.events,
            t=self.events.t[mask],
            x=self.events.x[mask],
            y=self.events.y[mask],
            p=self.events.p[mask],
        )

    def _normalize_to_uint8(self, arr: np.ndarray) -> np.ndarray:
        arr = arr.astype(np.float32)
        mx = float(arr.max()) if arr.size else 0.0
        if mx <= 0.0:
            return np.zeros(arr.shape, dtype=np.uint8)
        arr = arr / mx
        return np.clip(arr * 255.0, 0, 255).astype(np.uint8)

    def _colorize_heatmap(self, norm: np.ndarray) -> np.ndarray:
        norm = np.clip(norm, 0.0, 1.0)
        r = np.clip(2.8 * norm - 1.2, 0.0, 1.0)
        g = np.clip(3.2 * norm - 0.2, 0.0, 1.0)
        b = np.clip(1.2 - 2.2 * norm, 0.0, 1.0)
        rgb = np.stack([r, g, b], axis=-1)
        rgb = np.power(rgb, 0.8)
        return np.clip(rgb * 255.0, 0, 255).astype(np.uint8)

    def _time_to_rgb(self, t_norm: np.ndarray) -> np.ndarray:
        t_norm = np.clip(t_norm, 0.0, 1.0)
        r = np.clip(2.2 * t_norm - 0.2, 0.0, 1.0)
        g = np.clip(1.8 - 2.0 * np.abs(t_norm - 0.5), 0.0, 1.0)
        b = np.clip(1.2 - 2.0 * t_norm, 0.0, 1.0)
        return np.stack([r, g, b], axis=-1)

    def _blend_rgb(self, base: np.ndarray, overlay: np.ndarray, alpha: float) -> np.ndarray:
        alpha = float(np.clip(alpha, 0.0, 1.0))
        out = (1.0 - alpha) * base.astype(np.float32) + alpha * overlay.astype(np.float32)
        return np.clip(out, 0, 255).astype(np.uint8)

    def _draw_line_rgb(
        self,
        rgb: np.ndarray,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        h, w = rgb.shape[:2]
        dx = abs(x1 - x0)
        dy = abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy

        while True:
            for oy in range(-thickness + 1, thickness):
                for ox in range(-thickness + 1, thickness):
                    xx = x0 + ox
                    yy = y0 + oy
                    if 0 <= xx < w and 0 <= yy < h:
                        rgb[yy, xx] = color
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x0 += sx
            if e2 < dx:
                err += dx
                y0 += sy

    def _draw_arrow_rgb(
        self,
        rgb: np.ndarray,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        color: tuple[int, int, int],
        thickness: int = 1,
    ) -> None:
        self._draw_line_rgb(rgb, x0, y0, x1, y1, color, thickness=thickness)

        dx = x1 - x0
        dy = y1 - y0
        length = max(1.0, float(np.hypot(dx, dy)))

        ux = dx / length
        uy = dy / length

        head_len = max(4.0, min(10.0, 0.30 * length))
        left_x = int(round(x1 - head_len * (ux + uy * 0.6)))
        left_y = int(round(y1 - head_len * (uy - ux * 0.6)))
        right_x = int(round(x1 - head_len * (ux - uy * 0.6)))
        right_y = int(round(y1 - head_len * (uy + ux * 0.6)))

        self._draw_line_rgb(rgb, x1, y1, left_x, left_y, color, thickness=thickness)
        self._draw_line_rgb(rgb, x1, y1, right_x, right_y, color, thickness=thickness)

    def _render_raw_frame(self, t0: int, window_us: int) -> np.ndarray:
        assert self.events is not None
        assert self.hw is not None
        return accumulate_frame(self.events, self.hw, window_us=window_us, t_start_us=t0)

    def _render_heatmap_frame(self, t0: int, t1: int) -> np.ndarray:
        assert self.hw is not None
        batch = self._extract_window_batch(t0, t1)
        h, w = self.hw

        heat = np.zeros((h, w), dtype=np.uint32)
        if batch is not None and batch.t.size > 0:
            np.add.at(heat, (batch.y, batch.x), 1)

        if heat.max() > 0:
            heat_f = np.log1p(heat.astype(np.float32))
            heat_f /= float(heat_f.max())
        else:
            heat_f = heat.astype(np.float32)

        return self._colorize_heatmap(heat_f)

    def _render_trail_frame(self, t0: int, t1: int) -> np.ndarray:
        assert self.hw is not None
        batch = self._extract_window_batch(t0, t1)
        h, w = self.hw

        canvas = np.zeros((h, w, 3), dtype=np.float32)
        if batch is not None and batch.t.size > 0:
            ts = batch.t.astype(np.float32)
            if ts.size > 1 and float(ts.max()) > float(ts.min()):
                t_norm = (ts - float(ts.min())) / (float(ts.max()) - float(ts.min()))
            else:
                t_norm = np.zeros_like(ts, dtype=np.float32)

            colors = self._time_to_rgb(t_norm)
            np.add.at(canvas[..., 0], (batch.y, batch.x), colors[:, 0])
            np.add.at(canvas[..., 1], (batch.y, batch.x), colors[:, 1])
            np.add.at(canvas[..., 2], (batch.y, batch.x), colors[:, 2])

            canvas = np.log1p(canvas)
            mx = float(canvas.max())
            if mx > 0:
                canvas /= mx

        return np.clip(canvas * 255.0, 0, 255).astype(np.uint8)

    def _render_motion_arrows_frame(self, t0: int, t1: int) -> np.ndarray:
        assert self.hw is not None
        h, w = self.hw

        # background
        bg = np.zeros((h, w, 3), dtype=np.uint8)
        bg[..., 0] = 24
        bg[..., 1] = 34
        bg[..., 2] = 58

        # base silhouette from current window heatmap
        heat_rgb = self._render_heatmap_frame(t0, t1)
        silhouette_alpha = float(self.arrow_silhouette_spin.value())
        canvas = self._blend_rgb(bg, heat_rgb, silhouette_alpha)

        total_dt = max(1, t1 - t0)
        t_a0 = t0
        t_a1 = t0 + total_dt // 2
        t_b0 = t_a1
        t_b1 = t1

        batch_a = self._extract_window_batch(t_a0, t_a1)
        batch_b = self._extract_window_batch(t_b0, t_b1)

        if batch_a is None or batch_b is None or batch_a.t.size == 0 or batch_b.t.size == 0:
            return canvas

        cell = int(self.arrow_grid_spin.value())
        min_events_per_half = int(self.arrow_min_events_spin.value())
        arrow_scale = float(self.arrow_scale_spin.value())

        for gy in range(0, h, cell):
            for gx in range(0, w, cell):
                a_mask = (
                    (batch_a.x >= gx) & (batch_a.x < gx + cell) &
                    (batch_a.y >= gy) & (batch_a.y < gy + cell)
                )
                b_mask = (
                    (batch_b.x >= gx) & (batch_b.x < gx + cell) &
                    (batch_b.y >= gy) & (batch_b.y < gy + cell)
                )

                a_count = int(np.sum(a_mask))
                b_count = int(np.sum(b_mask))
                if a_count < min_events_per_half or b_count < min_events_per_half:
                    continue

                ax = float(np.mean(batch_a.x[a_mask]))
                ay = float(np.mean(batch_a.y[a_mask]))
                bx = float(np.mean(batch_b.x[b_mask]))
                by = float(np.mean(batch_b.y[b_mask]))

                dx = bx - ax
                dy = by - ay
                mag = float(np.hypot(dx, dy))

                # threshold tiny/noisy motion
                if mag < 1.3:
                    continue

                # use center between the two centroids as anchor
                sx = int(round((ax + bx) * 0.5))
                sy = int(round((ay + by) * 0.5))
                ex = int(round(sx + dx * arrow_scale))
                ey = int(round(sy + dy * arrow_scale))

                # stronger color for stronger motion
                tmag = min(1.0, mag / max(3.0, cell * 0.45))
                color = self._time_to_rgb(np.array([tmag], dtype=np.float32))[0]
                color_u8 = tuple(int(v * 255.0) for v in color)

                thickness = 2 if mag >= 3.5 else 1
                self._draw_arrow_rgb(canvas, sx, sy, ex, ey, color_u8, thickness=thickness)

        return canvas

    def _render_mode_frame(self, t0: int, window_us: int) -> np.ndarray:
        t1 = int(t0 + window_us)

        if self.current_view_mode == VIEW_MODE_RAW:
            return self._render_raw_frame(t0, window_us)

        if self.current_view_mode == VIEW_MODE_HEATMAP:
            return self._render_heatmap_frame(t0, t1)

        if self.current_view_mode == VIEW_MODE_TRAIL:
            return self._render_trail_frame(t0, t1)

        if self.current_view_mode == VIEW_MODE_MOTION_ARROWS:
            return self._render_motion_arrows_frame(t0, t1)

        return self._render_raw_frame(t0, window_us)

    # =========================================================
    # Main render
    # =========================================================
    def _render_from_ui(self) -> None:
        if self.events is None or self.hw is None:
            return

        t0, t1 = self._current_window()
        window_us = int(self.window_ms.value() * 1000)
        batch = self._extract_window_batch(t0, t1)

        if batch is None:
            win_count = 0
            win_pos = 0
            win_neg = 0
            win_active_pixels = 0
        else:
            win_count = int(batch.t.size)
            win_pos = int(np.sum(batch.p > 0))
            win_neg = win_count - win_pos
            packed = (batch.y.astype(np.int64) * self.hw[1]) + batch.x.astype(np.int64)
            win_active_pixels = int(np.unique(packed).size) if win_count > 0 else 0

        img = self._render_mode_frame(t0, window_us)

        self.current_frame = img.copy()
        self.view.set_frame(img)
        self.time_label.setText(f"t = {t0:,} µs   |   {t0 / 1000.0:.2f} ms")

        self.statusBar().showMessage(
            f"{self.current_view_mode} | t={t0} µs | win={self.window_ms.value()} ms | events_in_win={win_count:,}"
        )

        win_ms = max(1e-9, window_us / 1000.0)
        win_ev_per_ms = win_count / win_ms
        win_pos_pct = self._format_ratio_percent(win_pos, win_count)

        self.stats_window.setText(
            "\n".join(
                [
                    f"Window ({self.current_view_mode})",
                    f"Events: {win_count:,}",
                    f"+ / − : {win_pos:,} / {win_neg:,}   ({win_pos_pct:.1f}% +)",
                    f"Events/ms: {win_ev_per_ms:.2f}",
                    f"Active pixels: {win_active_pixels:,}",
                ]
            )
        )

        self._update_stats_active_roi(t0, t1)
        self._refresh_analysis_panel()
        self._update_timeline_slice_regions()

    # =========================================================
    # Stats / analysis
    # =========================================================
    def _update_stats_global(self) -> None:
        if self.events is None or self.hw is None:
            self.stats_global.setText("Global: —")
            return

        total = int(self.events.t.size)
        h, w = self.hw
        dur_us = int(self.t_max - self.t_min) if self.t_max > self.t_min else 0
        dur_ms = dur_us / 1000.0
        events_per_ms = total / dur_ms if dur_ms > 0 else 0.0

        self.stats_global.setText(
            "\n".join(
                [
                    "Global",
                    f"Events: {total:,}",
                    f"Resolution: {w}x{h}",
                    f"Duration: {dur_ms:.2f} ms",
                    f"Events/ms: {events_per_ms:.2f}",
                ]
            )
        )

    def _update_stats_active_roi(self, t0: int, t1: int) -> None:
        if self.events is None or self.hw is None:
            self.stats_roi.setText("Active ROI in window: —")
            return

        if self.active_roi_index is None or not (0 <= self.active_roi_index < len(self.rois)):
            self.stats_roi.setText("Active ROI in window: —")
            return

        roi_item = self.rois[self.active_roi_index]
        roi = roi_item.roi
        window_us = int(t1 - t0)

        stats = compute_roi_stats(
            events=self.events,
            hw=self.hw,
            roi=roi,
            t0_us=int(t0),
            window_us=int(window_us),
        )

        roi_area = int(roi.w * roi.h)
        density = stats.n_events / roi_area if roi_area > 0 else 0.0
        pos_pct = self._format_ratio_percent(stats.pos, stats.n_events)

        self.stats_roi.setText(
            "\n".join(
                [
                    f'Active ROI "{roi_item.name}"',
                    f"Events: {stats.n_events:,}",
                    f"+ / − : {stats.pos:,} / {stats.neg:,}   ({pos_pct:.1f}% +)",
                    f"Events/ms: {stats.events_per_ms:.2f}",
                    f"Polarity ratio (+/−): {stats.polarity_ratio:.2f}",
                    f"Active pixels: {stats.active_pixels:,}",
                    f"ROI area: {roi_area:,} px",
                    f"Density: {density:.4f} ev/pixel",
                ]
            )
        )

    def _refresh_analysis_panel(self) -> None:
        if not self.analysis_panel.isVisible():
            return

        if self.events is None or self.hw is None:
            self.analysis_panel.clear_analysis()
            return

        if self.active_roi_index is None or not (0 <= self.active_roi_index < len(self.rois)):
            self.analysis_panel.clear_analysis()
            return

        roi_item = self.rois[self.active_roi_index]
        t0, _ = self._current_window()
        window_us = int(self.window_ms.value() * 1000)

        self.analysis_panel.set_analysis_data(
            project_name=self.project_name,
            loaded_name=self.loaded_name,
            events=self.events,
            hw=self.hw,
            roi_name=roi_item.name,
            roi=roi_item.roi,
            roi_color=roi_item.color,
            current_t0_us=int(t0),
            current_window_us=int(window_us),
        )

    # =========================================================
    # ROI candidate / movement
    # =========================================================
    def _on_candidate_roi_changed(self, roi) -> None:
        self._candidate_roi = roi if isinstance(roi, Roi) else None

        if self._candidate_roi is None:
            self.btn_add_roi.setEnabled(False)
        else:
            self.btn_add_roi.setEnabled(True)

        self._update_roi_status_label()

    def _on_active_roi_moved(self, roi) -> None:
        if not isinstance(roi, Roi):
            return
        if self.active_roi_index is None:
            return
        if not (0 <= self.active_roi_index < len(self.rois)):
            return

        self.rois[self.active_roi_index].roi = roi
        self._update_roi_status_label()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._refresh_analysis_panel()

    def _update_roi_status_label(self) -> None:
        lines = []

        if self._candidate_roi is None:
            lines.append("Candidate: None (drag on image to create)")
        else:
            r = self._candidate_roi
            lines.append(f"Candidate: x={r.x} y={r.y} w={r.w} h={r.h}")

        if self.active_roi_index is not None and 0 <= self.active_roi_index < len(self.rois):
            ar = self.rois[self.active_roi_index]
            rr = ar.roi
            lines.append(f'Active ROI "{ar.name}": x={rr.x} y={rr.y} w={rr.w} h={rr.h}')
            lines.append("Tip: drag inside the selected visible ROI to move it or drag a corner handle to resize it.")
        else:
            lines.append("Tip: select a visible ROI below, then drag inside it to move it or drag a corner to resize it.")

        self.roi_status.setText("\n".join(lines))

    def _clear_candidate_roi(self) -> None:
        self._candidate_roi = None
        self.view.clear_roi()
        self.btn_add_roi.setEnabled(False)
        self._update_roi_status_label()

    def _add_roi_from_candidate(self) -> None:
        if self._candidate_roi is None:
            return

        name, ok = QInputDialog.getText(self, "Name ROI", "ROI name:")
        if not ok:
            return
        name = name.strip()
        if not name:
            name = f"ROI {len(self.rois) + 1}"

        self.rois.append(
            NamedROI(
                name=name,
                roi=self._candidate_roi,
                visible=True,
                color=self._next_default_roi_color(),
            )
        )
        self.active_roi_index = len(self.rois) - 1

        self._clear_candidate_roi()
        self._rebuild_roi_list()
        self._push_rois_to_view()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._update_roi_status_label()
        self._refresh_analysis_panel()

    def _rename_selected_roi(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            QMessageBox.information(self, "Rename ROI", "Select an ROI first.")
            return

        current_name = self.rois[row].name
        name, ok = QInputDialog.getText(self, "Rename ROI", "ROI name:", text=current_name)
        if not ok:
            return

        name = name.strip()
        if not name:
            return

        self.rois[row].name = name
        self._rebuild_roi_list()
        self._rebuild_slice_list()
        self._update_roi_status_label()
        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._refresh_analysis_panel()

    def _set_selected_roi_color(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            QMessageBox.information(self, "Set ROI Color", "Select an ROI first.")
            return

        current = QColor(self.rois[row].color)
        color = QColorDialog.getColor(current, self, f'Set color for "{self.rois[row].name}"')
        if not color.isValid():
            return

        self.rois[row].color = color.name()
        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._refresh_analysis_panel()

    def _cycle_selected_roi_color(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            QMessageBox.information(self, "Next Palette Color", "Select an ROI first.")
            return

        current = self.rois[row].color
        try:
            idx = ROI_COLOR_PALETTE.index(current)
            next_idx = (idx + 1) % len(ROI_COLOR_PALETTE)
        except ValueError:
            next_idx = 0

        self.rois[row].color = ROI_COLOR_PALETTE[next_idx]
        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._refresh_analysis_panel()

    def _duplicate_selected_roi(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            QMessageBox.information(self, "Duplicate ROI", "Select an ROI first.")
            return

        src = self.rois[row]
        offset = 10

        new_roi = Roi(
            x=src.roi.x + offset,
            y=src.roi.y + offset,
            w=src.roi.w,
            h=src.roi.h,
        )

        if self.hw is not None:
            max_x = max(0, self.hw[1] - new_roi.w)
            max_y = max(0, self.hw[0] - new_roi.h)
            new_roi.x = max(0, min(max_x, new_roi.x))
            new_roi.y = max(0, min(max_y, new_roi.y))

        new_name = f"{src.name}_copy"
        existing = {r.name for r in self.rois}
        if new_name in existing:
            i = 2
            while f"{src.name}_copy_{i}" in existing:
                i += 1
            new_name = f"{src.name}_copy_{i}"

        self.rois.append(
            NamedROI(
                name=new_name,
                roi=new_roi,
                visible=src.visible,
                color=src.color,
            )
        )
        self.active_roi_index = len(self.rois) - 1

        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._update_roi_status_label()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._refresh_analysis_panel()

    # =========================================================
    # CSV export helpers
    # =========================================================
    def _write_json_sidecar(self, path: Path, payload: dict) -> None:
        with path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _export_selected_roi_csv(self) -> None:
        if self.events is None:
            QMessageBox.information(self, "Export ROI", "Load a dataset first.")
            return

        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            QMessageBox.information(self, "Export ROI", "Select an ROI first.")
            return

        roi_item = self.rois[row]
        roi = roi_item.roi

        rx0, ry0 = roi.x, roi.y
        rx1, ry1 = roi.x + roi.w, roi.y + roi.h

        mask = (
            (self.events.x >= rx0) & (self.events.x < rx1) &
            (self.events.y >= ry0) & (self.events.y < ry1)
        )

        if not np.any(mask):
            QMessageBox.information(self, "Export ROI", f'ROI "{roi_item.name}" contains 0 events.')
            return

        t = self.events.t[mask]
        x = self.events.x[mask]
        y = self.events.y[mask]
        p = self.events.p[mask]

        out_dir = self.project_root / "data" / "roi_exports"
        out_dir.mkdir(parents=True, exist_ok=True)

        base = self.loaded_name or "events"
        safe_roi = self._sanitize_name_for_file(roi_item.name)
        out_csv = out_dir / f"{base}__ROI__{safe_roi}.csv"
        out_json = out_dir / f"{base}__ROI__{safe_roi}.json"

        try:
            with open(out_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t", "x", "y", "p"])
                for ti, xi, yi, pi in zip(t.tolist(), x.tolist(), y.tolist(), p.tolist()):
                    w.writerow([int(ti), int(xi), int(yi), int(pi)])

            sidecar = {
                "export_type": "roi",
                "exported_at": now_iso(),
                "project_name": self.project_name,
                "source_loaded_name": self.loaded_name,
                "source_csv_path": self.loaded_csv_path,
                "source_event_count": int(self.events.t.size),
                "roi": {
                    "name": roi_item.name,
                    "x": int(roi.x),
                    "y": int(roi.y),
                    "w": int(roi.w),
                    "h": int(roi.h),
                    "visible": bool(roi_item.visible),
                    "color": roi_item.color,
                },
                "exported_event_count": int(len(t)),
                "time_range_us": {
                    "t_min": int(t.min()) if len(t) else None,
                    "t_max": int(t.max()) if len(t) else None,
                },
                "files": {
                    "csv": str(out_csv),
                    "metadata_json": str(out_json),
                },
            }
            self._write_json_sidecar(out_json, sidecar)

        except Exception as e:
            QMessageBox.critical(self, "Export ROI failed", str(e))
            return

        QMessageBox.information(
            self,
            "Export ROI",
            f'Saved ROI "{roi_item.name}" with {len(t):,} events:\n{out_csv}\n\nMetadata:\n{out_json}'
        )

    # =========================================================
    # ROI selection / overlay control
    # =========================================================
    def _delete_selected_roi(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            return

        del self.rois[row]

        if self.active_roi_index is not None:
            if self.active_roi_index == row:
                self.active_roi_index = None
            elif self.active_roi_index > row:
                self.active_roi_index -= 1

        for s in self.slices:
            if s.roi_index is None:
                continue
            if s.roi_index == row:
                s.roi_index = None
            elif s.roi_index > row:
                s.roi_index -= 1

        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._rebuild_slice_list()
        self._update_timeline_slice_regions()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._update_roi_status_label()
        self._refresh_analysis_panel()

    def _clear_all_rois(self) -> None:
        self.rois = []
        self.active_roi_index = None

        for s in self.slices:
            s.roi_index = None

        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._rebuild_slice_list()
        self._update_timeline_slice_regions()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._update_roi_status_label()
        self._refresh_analysis_panel()

    def _on_roi_selection_changed(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            self.active_roi_index = None
        else:
            self.active_roi_index = row

        has_selected_roi = self.active_roi_index is not None and self.events is not None
        self.btn_export_roi.setEnabled(has_selected_roi)
        self.btn_toggle_analysis.setEnabled(has_selected_roi)

        self._push_rois_to_view()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._update_roi_status_label()
        self._refresh_analysis_panel()

    def _on_roi_item_changed(self, item: QListWidgetItem) -> None:
        row = self.roi_list.row(item)
        if row < 0 or row >= len(self.rois):
            return

        self.rois[row].visible = (item.checkState() == Qt.Checked)
        self._push_rois_to_view()
        self._update_roi_status_label()
        self._refresh_analysis_panel()

    def _on_toggle_roi_overlays(self) -> None:
        self.view.set_show_overlays(self.chk_show_rois.isChecked())

    # =========================================================
    # Slice / loop logic
    # =========================================================
    def _update_loop_button_text(self) -> None:
        selected_row = self.slice_list.currentRow()
        if selected_row >= 0 and self.loop_slice_index == selected_row:
            self.btn_loop_slice.setText("Stop Loop")
        else:
            self.btn_loop_slice.setText("Loop Selected Slice")

    def _toggle_loop_selected_slice(self) -> None:
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return

        if self.loop_slice_index == row:
            self.loop_slice_index = None
        else:
            self.loop_slice_index = row

        self._update_loop_button_text()
        self._update_timeline_slice_regions()

    def _on_slice_selection_changed(self) -> None:
        has = self.slice_list.currentRow() >= 0
        self.btn_jump_slice.setEnabled(has)
        self.btn_export_slice.setEnabled(has)
        self.btn_delete_slice.setEnabled(has)
        self.btn_rename_slice.setEnabled(has)
        self.btn_set_slice_color.setEnabled(has)
        self.btn_loop_slice.setEnabled(has)
        self._update_loop_button_text()
        self._update_timeline_slice_regions()

    def _rename_selected_slice(self) -> None:
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return

        current_name = self.slices[row].name
        name, ok = QInputDialog.getText(self, "Rename Slice", "Slice name:", text=current_name)
        if not ok:
            return

        name = name.strip()
        if not name:
            return

        self.slices[row].name = name
        self._rebuild_slice_list()
        self.slice_list.setCurrentRow(row)
        self._update_timeline_slice_regions()

    def _set_selected_slice_color(self) -> None:
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return

        current = QColor(self.slices[row].color)
        color = QColorDialog.getColor(current, self, f'Set color for slice "{self.slices[row].name}"')
        if not color.isValid():
            return

        self.slices[row].color = color.name()
        self._rebuild_slice_list()
        self.slice_list.setCurrentRow(row)
        self._update_timeline_slice_regions()

    def _on_timeline_slice_selected(self, index: int) -> None:
        if 0 <= index < len(self.slices):
            self.slice_list.setCurrentRow(index)
            self._update_timeline_slice_regions()

    def _on_timeline_slice_edited(self, index: int, start_value: int, end_value: int) -> None:
        if not (0 <= index < len(self.slices)):
            return

        t0 = self._slider_value_to_time_us(start_value)
        t1 = self._slider_value_to_time_us(end_value)

        if t1 <= t0:
            t1 = t0 + 1

        self.slices[index].t0 = int(t0)
        self.slices[index].t1 = int(t1)

        self._rebuild_slice_list()
        self.slice_list.setCurrentRow(index)
        self._update_timeline_slice_regions()

    def _rebuild_roi_list(self) -> None:
        self.roi_list.blockSignals(True)
        self.roi_list.clear()

        for roi_item in self.rois:
            it = QListWidgetItem(roi_item.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            it.setCheckState(Qt.Checked if roi_item.visible else Qt.Unchecked)
            it.setIcon(self._make_color_icon(roi_item.color))
            self.roi_list.addItem(it)

        if self.active_roi_index is not None and 0 <= self.active_roi_index < len(self.rois):
            self.roi_list.setCurrentRow(self.active_roi_index)

        self.roi_list.blockSignals(False)

        has_selected_roi = self.active_roi_index is not None and self.events is not None
        self.btn_export_roi.setEnabled(has_selected_roi)
        self.btn_toggle_analysis.setEnabled(has_selected_roi)

    def _push_rois_to_view(self) -> None:
        visible_rois: list[tuple[Roi, str]] = [
            (r.roi, r.color) for r in self.rois if r.visible
        ]

        active_vis_idx: Optional[int] = None
        if self.active_roi_index is not None and 0 <= self.active_roi_index < len(self.rois):
            if self.rois[self.active_roi_index].visible:
                active_vis_idx = sum(1 for i in range(self.active_roi_index) if self.rois[i].visible)

        self.view.set_rois(visible_rois, active_index=active_vis_idx)

    def _rebuild_slice_list(self) -> None:
        self.slice_list.blockSignals(True)
        self.slice_list.clear()

        for s in self.slices:
            roi_tag = ""
            if s.roi_index is not None and 0 <= s.roi_index < len(self.rois):
                roi_tag = f' | ROI="{self.rois[s.roi_index].name}"'
            elif s.roi_index is not None:
                roi_tag = " | ROI=(missing)"

            ms0 = s.t0 / 1000.0
            ms1 = s.t1 / 1000.0
            it = QListWidgetItem(f'{s.name} | {ms0:.2f}–{ms1:.2f} ms{roi_tag}')
            it.setIcon(self._make_color_icon(s.color))
            self.slice_list.addItem(it)

        self.slice_list.blockSignals(False)

        any_slices = len(self.slices) > 0
        self.btn_clear_slices.setEnabled(any_slices)

        if self.loop_slice_index is not None and not (0 <= self.loop_slice_index < len(self.slices)):
            self.loop_slice_index = None

        self._on_slice_selection_changed()

    def _add_slice_from_current_view(self) -> None:
        if self.events is None:
            return

        t0, t1 = self._current_window()

        default_name = f"Slice {len(self.slices) + 1}"
        name, ok = QInputDialog.getText(self, "Name slice", "Slice name:", text=default_name)
        if not ok:
            return
        name = name.strip() or default_name

        roi_index = self.active_roi_index
        self.slices.append(
            Slice(
                name=name,
                t0=t0,
                t1=t1,
                roi_index=roi_index,
                color=self._next_default_slice_color(),
            )
        )
        self._rebuild_slice_list()
        self.slice_list.setCurrentRow(len(self.slices) - 1)
        self._update_timeline_slice_regions()

    def _jump_to_selected_slice(self) -> None:
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return
        s = self.slices[row]

        if self.events is None:
            return
        span = max(1, self.t_max - self.t_min)
        frac = (s.t0 - self.t_min) / span
        frac = max(0.0, min(1.0, frac))
        self.timeline.setValue(int(frac * 1000))

        dur_ms = max(1, int((s.t1 - s.t0) / 1000))
        self.window_ms.setValue(min(self.window_ms.maximum(), dur_ms))

        if s.roi_index is not None and 0 <= s.roi_index < len(self.rois):
            self.active_roi_index = s.roi_index
            self._rebuild_roi_list()
            self._push_rois_to_view()

        self._render_from_ui()
        self._update_roi_status_label()
        self._update_timeline_slice_regions()

    def _delete_selected_slice(self) -> None:
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return

        del self.slices[row]

        if self.loop_slice_index is not None:
            if self.loop_slice_index == row:
                self.loop_slice_index = None
            elif self.loop_slice_index > row:
                self.loop_slice_index -= 1

        self._rebuild_slice_list()
        self._update_timeline_slice_regions()

    def _clear_slices(self) -> None:
        self.slices = []
        self.loop_slice_index = None
        self._rebuild_slice_list()
        self._update_timeline_slice_regions()

    def _export_selected_slice_csv(self) -> None:
        if self.events is None:
            return
        row = self.slice_list.currentRow()
        if row < 0 or row >= len(self.slices):
            return

        s = self.slices[row]
        t0, t1 = s.t0, s.t1

        m = (self.events.t >= t0) & (self.events.t < t1)
        if not np.any(m):
            QMessageBox.information(self, "Export slice", "Slice contains 0 events.")
            return

        x = self.events.x[m]
        y = self.events.y[m]
        p = self.events.p[m]
        t = self.events.t[m]

        roi_name = None
        roi_box = None
        roi_name_tag = "full"

        if s.roi_index is not None and 0 <= s.roi_index < len(self.rois):
            roi_item = self.rois[s.roi_index]
            roi = roi_item.roi
            rx0, ry0 = roi.x, roi.y
            rx1, ry1 = roi.x + roi.w, roi.y + roi.h
            in_roi = (x >= rx0) & (x < rx1) & (y >= ry0) & (y < ry1)

            if not np.any(in_roi):
                QMessageBox.information(self, "Export slice", "Slice ROI contains 0 events.")
                return

            x = x[in_roi]
            y = y[in_roi]
            p = p[in_roi]
            t = t[in_roi]
            roi_name = roi_item.name
            roi_name_tag = self._sanitize_name_for_file(roi_item.name)
            roi_box = {
                "x": int(roi.x),
                "y": int(roi.y),
                "w": int(roi.w),
                "h": int(roi.h),
                "color": roi_item.color,
            }

        out_dir = self.project_root / "data" / "slices"
        out_dir.mkdir(parents=True, exist_ok=True)

        base = self.loaded_name or "events"
        safe_slice = self._sanitize_name_for_file(s.name)
        out_csv = out_dir / f"{base}__{safe_slice}__{roi_name_tag}.csv"
        out_json = out_dir / f"{base}__{safe_slice}__{roi_name_tag}.json"

        try:
            with open(out_csv, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t", "x", "y", "p"])
                for ti, xi, yi, pi in zip(t.tolist(), x.tolist(), y.tolist(), p.tolist()):
                    w.writerow([int(ti), int(xi), int(yi), int(pi)])

            sidecar = {
                "export_type": "slice",
                "exported_at": now_iso(),
                "project_name": self.project_name,
                "source_loaded_name": self.loaded_name,
                "source_csv_path": self.loaded_csv_path,
                "source_event_count": int(self.events.t.size),
                "slice": {
                    "name": s.name,
                    "t0_us": int(s.t0),
                    "t1_us": int(s.t1),
                    "duration_us": int(s.t1 - s.t0),
                    "roi_index": s.roi_index,
                    "roi_name": roi_name,
                    "roi_box": roi_box,
                    "color": s.color,
                },
                "exported_event_count": int(len(t)),
                "time_range_us": {
                    "t_min": int(t.min()) if len(t) else None,
                    "t_max": int(t.max()) if len(t) else None,
                },
                "files": {
                    "csv": str(out_csv),
                    "metadata_json": str(out_json),
                },
            }
            self._write_json_sidecar(out_json, sidecar)

        except Exception as e:
            QMessageBox.critical(self, "Export slice failed", str(e))
            return

        QMessageBox.information(
            self,
            "Export slice",
            f"Saved:\n{out_csv}\n\nMetadata:\n{out_json}"
        )

    # =========================================================
    # Playback
    # =========================================================
    def _toggle_play(self) -> None:
        if self.events is None:
            return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.play_btn.setText("Pause")
            self.play_timer.start(33)
        else:
            self.play_btn.setText("Play")
            self.play_timer.stop()

    def _on_tick(self) -> None:
        if not self.is_playing:
            return

        if self.loop_slice_index is not None and 0 <= self.loop_slice_index < len(self.slices):
            s = self.slices[self.loop_slice_index]
            span = max(1, self.t_max - self.t_min)

            current_t0, _ = self._current_window()
            next_t0 = current_t0 + int((3 / 1000.0) * span)

            if next_t0 >= s.t1:
                loop_frac = (s.t0 - self.t_min) / span
                loop_frac = max(0.0, min(1.0, loop_frac))
                self.timeline.setValue(int(loop_frac * 1000))
                return

        v = self.timeline.value() + 3
        if v >= self.timeline.maximum():
            self.timeline.setValue(self.timeline.maximum())
            self._toggle_play()
            return
        self.timeline.setValue(v)

    # =========================================================
    # Reset
    # =========================================================
    def _reset_view(self) -> None:
        self.play_timer.stop()
        self.is_playing = False
        self.play_btn.setText("Play")
        self.play_btn.setEnabled(False)

        self.timeline.setEnabled(False)
        self.window_ms.setEnabled(False)

        self.events = None
        self.hw = None
        self.t_min = 0
        self.t_max = 0
        self.loaded_name = ""
        self.loaded_csv_path = ""
        self.current_frame = None

        self._candidate_roi = None
        self.view.clear_roi()
        self.rois = []
        self.active_roi_index = None
        self._rebuild_roi_list()
        self._push_rois_to_view()

        self.slices = []
        self.loop_slice_index = None
        self._rebuild_slice_list()
        self.timeline.clear_slice_regions()

        self.chk_show_rois.blockSignals(True)
        self.chk_show_rois.setChecked(True)
        self.chk_show_rois.blockSignals(False)
        self.view.set_show_overlays(True)

        self.current_view_mode = VIEW_MODE_RAW
        self.view_mode_combo.blockSignals(True)
        self.view_mode_combo.setCurrentText(VIEW_MODE_RAW)
        self.view_mode_combo.blockSignals(False)

        self.view.set_help_text("File → Import .dat to preview")
        self.view.set_frame(np.zeros((10, 10), dtype=np.uint8))

        self.btn_add_roi.setEnabled(False)
        self.btn_add_slice.setEnabled(False)
        self.btn_clear_slices.setEnabled(False)
        self.btn_export_roi.setEnabled(False)
        self.btn_toggle_analysis.setEnabled(False)
        self.btn_loop_slice.setEnabled(False)
        self._update_loop_button_text()

        self.stats_global.setText("Global: —")
        self.stats_window.setText("Window: —")
        self.stats_roi.setText("Active ROI in window: —")
        self.time_label.setText("t = —")

        self.analysis_panel.clear_analysis()
        self._hide_analysis_panel()

        self._update_roi_status_label()
        self.statusBar().showMessage("Ready")


def main() -> None:
    app = QApplication(sys.argv)
    _try_show_boot(app)

    project_root = Path(__file__).resolve().parents[1]
    projects_root = project_root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)

    windows: list[MainWindow] = []

    def open_project(project_dir: str) -> None:
        browser.hide()
        win = MainWindow(browser_ref=browser, project_dir=project_dir)
        win.resize(1600, 950)
        win.show()
        windows.append(win)

    browser = ProjectBrowser(projects_root=projects_root, open_project_callback=open_project)
    browser.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()