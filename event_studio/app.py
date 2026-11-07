from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from uuid import uuid4
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
    QLineEdit,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QProgressDialog,
)
from .science import select, export_csv, polarity_ratio
from . import rendering
from .workers import Task

from .convert import convert_dat_to_h5_windows, h5_to_csv_windows
from .viewer import (
    load_events_from_csv,
    infer_hw,
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
        app.boot_overlay = show_boot(app)  # keep startup/audio alive
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
VIEW_MODE_PERSISTENCE = "PERSISTENCE TRAILS"
VIEW_MODE_GLOW = "POLARITY GLOW"


@dataclass
class NamedROI:
    name: str
    roi: Roi
    visible: bool = True
    color: str = "#ff3b30"
    id: str = field(default_factory=lambda: uuid4().hex)


@dataclass
class Slice:
    name: str
    t0: int
    t1: int
    roi_index: Optional[int] = None
    color: str = "#34c759"
    id: str = field(default_factory=lambda: uuid4().hex)
    roi_id: Optional[str] = None
    roi_snapshot: Optional[dict] = None
    polarity: str = "both"
    source_sha256: str = ""
    filters: dict = field(default_factory=dict)


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
        self.position_us = 0
        self.duration_us = 50_000
        self.zoom_start = 0
        self.zoom_end = 1
        self._task = None
        self._restoring = False
        self.filtered_events = None
        self.filter_settings = {}
        self.analysis_settings = {}
        self.annotations = []
        self.detections = []
        self._workspace = None
        self._live_window = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        root.addLayout(top, stretch=1)

        self.view = ROILabel()
        self.view.setMinimumSize(360, 300)
        self.view.set_help_text("File → Import .dat to preview")
        self.view.roiChanged.connect(self._on_candidate_roi_changed)
        self.view.roiMoved.connect(self._on_active_roi_moved)
        self.compare_view = ROILabel()
        self.compare_view.setMinimumSize(300, 300)
        self.compare_view.roiChanged.connect(self._on_candidate_roi_changed)
        self.compare_view.roiMoved.connect(self._on_active_roi_moved)
        self.compare_box = QGroupBox("RAW • unfiltered reference")
        compare_layout = QVBoxLayout(self.compare_box)
        compare_layout.addWidget(self.compare_view)
        self.compare_box.hide()
        top.addWidget(self.compare_box, stretch=3)
        self.view_box = QGroupBox("RAW • scientific view")
        viewer_layout = QVBoxLayout(self.view_box)
        viewer_layout.addWidget(self.view)
        top.addWidget(self.view_box, stretch=3)

        self.middle_panel = QVBoxLayout()
        self.middle_panel.setSpacing(10)
        sidebar = QWidget()
        sidebar.setLayout(self.middle_panel)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(sidebar)
        sidebar_scroll.setMinimumWidth(350)
        top.addWidget(sidebar_scroll, stretch=2)

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
            VIEW_MODE_PERSISTENCE,
            VIEW_MODE_GLOW,
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
        self.polarity_combo = QComboBox()
        self.polarity_combo.addItems(["both", "pos", "neg"])
        polarity_label = QLabel("Non-destructive polarity filter (view, window stats, new slices)")
        polarity_label.setWordWrap(True)
        view_layout.addWidget(polarity_label)
        view_layout.addWidget(self.polarity_combo)
        self.polarity_combo.currentTextChanged.connect(self._render_from_ui)
        self.polarity_combo.setToolTip("both = all events; pos = positive; neg = negative. The source recording remains unchanged.")
        self.compare_check = QCheckBox("Compare with unfiltered RAW")
        self.compare_check.toggled.connect(self._toggle_comparison)
        view_layout.addWidget(self.compare_check)
        self.persistence_ms = QDoubleSpinBox()
        self.persistence_ms.setRange(0.001, 60000)
        self.persistence_ms.setDecimals(3)
        self.persistence_ms.setValue(100)
        self.persistence_ms.setSuffix(" ms")
        self.persistence_ms.valueChanged.connect(self._render_from_ui)
        self.persistence_label = QLabel("Persistence duration • linear decay")
        view_layout.addWidget(self.persistence_label)
        view_layout.addWidget(self.persistence_ms)
        self.glow_intensity = QDoubleSpinBox()
        self.glow_intensity.setRange(0, 3)
        self.glow_intensity.setSingleStep(0.1)
        self.glow_intensity.setValue(0.7)
        self.glow_label = QLabel("Glow intensity • 5×5 spatial halo")
        view_layout.addWidget(self.glow_label)
        self.glow_intensity.valueChanged.connect(self._render_from_ui)
        view_layout.addWidget(self.glow_intensity)
        self.heat_scale = QComboBox()
        self.heat_scale.addItems(["Log relative", "Linear relative", "Absolute (100 events/pixel)"])
        self.heat_scale.currentTextChanged.connect(self._render_from_ui)
        self.heat_label = QLabel("Heatmap normalization")
        view_layout.addWidget(self.heat_label)
        view_layout.addWidget(self.heat_scale)

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
        self.arrow_widgets = [layout.itemAt(i).widget() for layout in (arrow_row1, arrow_row2)
                              for i in range(layout.count())]

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
        edit_bounds = QPushButton("Use exact current interval for selected slice")
        edit_bounds.clicked.connect(self._edit_slice_bounds)
        slice_layout.addWidget(edit_bounds)
        self.slice_stats = QLabel("Select a slice to inspect its saved interval.")
        self.slice_stats.setWordWrap(True)
        slice_layout.addWidget(self.slice_stats)

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
        self.roi_table = QTableWidget(0, 5)
        self.roi_table.setHorizontalHeaderLabels(["ROI", "Events", "+ / −", "ev/ms", "Pixels"])
        self.roi_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.roi_table.setMinimumHeight(170)
        self.roi_table.setEditTriggers(QTableWidget.NoEditTriggers)
        stats_layout.addWidget(QLabel("All ROI probes • current interval and polarity filter"))
        stats_layout.addWidget(self.roi_table)
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
        self.timeline.setRange(0, 1_000_000)
        self.timeline.setValue(0)
        self.timeline.setEnabled(False)
        self.timeline.valueChanged.connect(self._on_timeline_changed)
        self.timeline.sliceSelected.connect(self._on_timeline_slice_selected)
        self.timeline.sliceEdited.connect(self._on_timeline_slice_edited)
        self.timeline.markerSelected.connect(self._on_analysis_marker)
        controls.addWidget(self.timeline, stretch=1)

        self.time_label = QLabel("t = —")
        controls.addWidget(self.time_label)

        controls.addWidget(QLabel("Window:"))
        self.window_ms = QDoubleSpinBox()
        self.window_ms.setDecimals(3)
        self.window_ms.setRange(0.001, 1_000_000_000)
        self.window_ms.setValue(50)
        self.window_ms.setSuffix(" ms")
        self.window_ms.setEnabled(False)
        self.window_ms.valueChanged.connect(self._on_window_changed)
        controls.addWidget(self.window_ms)

        precise = QHBoxLayout()
        root.addLayout(precise)
        self.start_edit = QLineEdit("0")
        self.end_edit = QLineEdit("50000")
        self.start_edit.setMaximumWidth(190)
        self.end_edit.setMaximumWidth(190)
        precise.addWidget(QLabel("Start µs"))
        precise.addWidget(self.start_edit)
        precise.addWidget(QLabel("End µs (exclusive)"))
        precise.addWidget(self.end_edit)
        apply_time = QPushButton("Apply interval")
        apply_time.clicked.connect(self._apply_interval)
        precise.addWidget(apply_time)
        self.step_us = QSpinBox()
        self.step_us.setRange(1, 1_000_000_000)
        self.step_us.setValue(1000)
        self.step_us.setSuffix(" µs / tick")
        precise.addWidget(self.step_us)
        for label, delta, shortcut in (("Step back", -1, "Left"), ("Step forward", 1, "Right")):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, d=delta: self._step(d))
            precise.addWidget(button)
            action = QAction(label, self)
            action.setShortcut(shortcut)
            action.triggered.connect(lambda checked=False, d=delta: self._step(d))
            self.addAction(action)
        for label, handler in (("Zoom to interval", self._zoom_interval), ("Full timeline", self._zoom_full)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            precise.addWidget(button)

        # -------------------------
        # Menu
        # -------------------------
        file_menu = self.menuBar().addMenu("&File")

        import_action = QAction("Import .dat", self)
        import_action.triggered.connect(self.on_import_dat_clicked)
        file_menu.addAction(import_action)
        for label, handler in (("Open CSV / H5", self._open_recording),
                               ("Export full recording CSV", self._export_full),
                               ("Export current selection CSV", self._export_current),
                               ("Save Session As…", self._save_session_as),
                               ("Load Session…", self._load_session_dialog)):
            action = QAction(label, self)
            action.triggered.connect(handler)
            file_menu.addAction(action)
        sensor_action = QAction("Set sensor resolution…", self)
        sensor_action.triggered.connect(self._set_sensor_resolution)
        file_menu.addAction(sensor_action)

        save_project_action = QAction("Save Project", self)
        save_project_action.setShortcut("Ctrl+S")
        save_project_action.triggered.connect(self.save_project)
        file_menu.addAction(save_project_action)

        rename_project_action = QAction("Rename Project", self)
        rename_project_action.triggered.connect(self.rename_current_project)
        file_menu.addAction(rename_project_action)

        file_menu.addSeparator()

        reset_action = QAction("Reset View", self)
        reset_action.triggered.connect(self._reset_view)
        file_menu.addAction(reset_action)
        analysis_menu = self.menuBar().addMenu("&Analysis")
        analysis_action = QAction("Advanced Analysis…", self)
        analysis_action.setShortcut("Ctrl+Shift+A")
        analysis_action.triggered.connect(self._open_analysis_workspace)
        analysis_menu.addAction(analysis_action)
        live_action = QAction("Live camera…",self)
        live_action.triggered.connect(self._open_live_window)
        analysis_menu.addAction(live_action)

        self.statusBar().showMessage("Ready")
        self._update_window_title()
        self._update_mode_description()

        if self.current_project_dir is not None:
            self._load_project_from_dir(self.current_project_dir)

    # =========================================================
    # General helpers
    # =========================================================
    def _run_task(self, function, finished, message="Working…", cooperative=False) -> None:
        if self._task is not None:
            return
        if self.is_playing:
            self._toggle_play()
        self.centralWidget().setEnabled(False)
        self.menuBar().setEnabled(False)
        self.statusBar().showMessage(message)
        dialog = QProgressDialog(message, "Cancel" if cooperative else "", 0, 100 if cooperative else 0, self)
        dialog.setWindowTitle("Event-Based Studio")
        dialog.setAutoClose(False)
        dialog.setMinimumDuration(300)
        if not cooperative:
            dialog.setCancelButton(None)
        task = Task(lambda: function(task.isInterruptionRequested, task.progress.emit) if cooperative else function(), self)
        dialog.canceled.connect(task.requestInterruption)
        task.progress.connect(lambda value, text: (dialog.setValue(min(99,value)), dialog.setLabelText(text)))
        if self._workspace is not None:
            self._workspace.setEnabled(False)
        self._task = task

        def success(result):
            try:
                finished(result)
            except Exception as exc:
                self._restoring = False
                QMessageBox.critical(self, "Operation failed", str(exc))

        def cleanup():
            self.centralWidget().setEnabled(True)
            self.menuBar().setEnabled(True)
            self._task = None
            dialog.close()
            dialog.deleteLater()
            if self._workspace is not None:
                self._workspace.setEnabled(True)
            task.deleteLater()

        task.succeeded.connect(success)
        task.failed.connect(lambda error: QMessageBox.critical(self, "Operation failed", error))
        task.cancelled.connect(self.statusBar().showMessage)
        task.finished.connect(cleanup)
        task.start()

    def _display_events(self):
        return self.filtered_events if self.filtered_events is not None else self.events

    def _window_batch(self,t0,t1):
        key=(id(self._display_events()),t0,t1,self.polarity_combo.currentText())
        if getattr(self,'_window_cache_key',None)!=key:
            self._window_cache_key=key
            self._window_cache=select(self._display_events(),t0,t1,polarity=key[-1])
            self._probe_cache={}
        return self._window_cache

    def _probe_stats(self,roi,t0,t1):
        batch=self._window_batch(t0,t1)
        key=(roi.x,roi.y,roi.w,roi.h)
        if key not in self._probe_cache:
            self._probe_cache[key]=compute_roi_stats(batch,self.hw,roi,t0,t1-t0)
        return self._probe_cache[key]

    def _open_analysis_workspace(self):
        if self.events is None:
            QMessageBox.information(self, "Advanced analysis", "Load a recording first.")
            return
        from .analysis_workspace import AnalysisWorkspace
        if self._workspace is None:
            self._workspace = AnalysisWorkspace(self)
        self._workspace.restore_settings()
        self._workspace.show()
        self._workspace.raise_()

    def _open_live_window(self):
        from .live_window import LiveWindow
        if self._live_window is None:
            self._live_window=LiveWindow(self)
        self._live_window.show()
        self._live_window.raise_()

    def _apply_filter_settings(self, settings, after=None):
        from .filters import apply_filters
        source = self.events
        def completed(filtered):
            self.filter_settings = dict(settings)
            self.filtered_events = filtered if any(settings.values()) else None
            self._slice_stats_cache = None
            self._render_from_ui()
            if after is not None:
                after()
        self._run_task(lambda cancel, progress: apply_filters(source,settings,cancel,progress),completed,
                       "Applying explicit filters…",cooperative=True)

    def _on_analysis_marker(self, index):
        markers = self.detections + self.annotations
        if 0 <= index < len(markers):
            item = markers[index]
            self.duration_us = max(1,item['t1']-item['t0'])
            self._seek(item['t0'])

    def _open_recording(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open recording", str(self.data_dir),
                                             "Event recordings (*.csv *.h5)")
        if not path:
            return

        def load():
            source = Path(path)
            if source.suffix.lower() == ".h5":
                source = h5_to_csv_windows(source, self.data_dir / "converted" / uuid4().hex[:12] / (source.stem + ".csv"))
            events = load_events_from_csv(source)
            if Path(path).suffix.lower() == ".h5":
                from .science import fingerprint
                events.metadata.update({"original_path": path, "original_sha256": fingerprint(Path(path)),
                                        "conversion": "OpenEB H5 → CSV"})
            return source, events

        self._run_task(load, lambda result: self._load_csv_into_app(result[0], Path(path).stem,
                                                                   prepared_events=result[1]), "Loading full recording…")

    def _seek(self, timestamp: int) -> None:
        if self.events is None:
            return
        self.position_us = max(self.t_min, min(self.t_max, int(timestamp)))
        self._render_from_ui()

    def _sync_time_widgets(self) -> None:
        self.timeline.blockSignals(True)
        self.timeline.setValue(self._time_us_to_slider_value(self.position_us))
        self.timeline.blockSignals(False)
        self.window_ms.blockSignals(True)
        self.window_ms.setValue(self.duration_us / 1000)
        self.window_ms.blockSignals(False)
        self.start_edit.setText(str(self.position_us))
        self.end_edit.setText(str(self.position_us + self.duration_us))

    def _on_timeline_changed(self, value) -> None:
        self._seek(self._slider_value_to_time_us(value))

    def _on_window_changed(self, value) -> None:
        self.duration_us = max(1, int(round(value * 1000)))
        self._render_from_ui()

    def _apply_interval(self) -> None:
        if self.events is None:
            return
        try:
            start, end = int(self.start_edit.text()), int(self.end_edit.text())
            if not (self.t_min <= start <= self.t_max and start < end <= self.t_max + 1):
                raise ValueError("Use a nonempty interval within the recording; end is exclusive.")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid interval", str(exc))
            return
        self.duration_us = end - start
        self._seek(start)

    def _step(self, direction) -> None:
        if self.events is not None:
            if self.is_playing:
                self._toggle_play()
            self._seek(self.position_us + direction * self.step_us.value())

    def _zoom_interval(self) -> None:
        if self.events is not None:
            self.zoom_start = self.position_us
            self.zoom_end = min(self.t_max + 1, self.position_us + self.duration_us)
            self._render_from_ui()

    def _zoom_full(self) -> None:
        if self.events is not None:
            self.zoom_start, self.zoom_end = self.t_min, self.t_max + 1
            self._render_from_ui()

    def _toggle_comparison(self, checked) -> None:
        self.compare_box.setVisible(checked)
        self._render_from_ui()

    def _update_mode_description(self) -> None:
        mode = self.current_view_mode
        inherited=self.events is not None and self.events.metadata.get('classification')=='DERIVED'
        classification = "RAW" if mode == VIEW_MODE_RAW and not inherited else "STYLIZED" if mode == VIEW_MODE_GLOW else "DERIVED"
        self.view_box.setTitle(f"{classification} • {mode}")
        self.compare_box.setTitle('DERIVED • unfiltered loaded file' if inherited else 'RAW • unfiltered reference')
        for widget in (self.persistence_label, self.persistence_ms):
            widget.setVisible(mode == VIEW_MODE_PERSISTENCE)
        for widget in (self.glow_label, self.glow_intensity):
            widget.setVisible(mode == VIEW_MODE_GLOW)
        for widget in (self.heat_label, self.heat_scale):
            widget.setVisible(mode == VIEW_MODE_HEATMAP)
        for widget in self.arrow_widgets:
            widget.setVisible(mode == VIEW_MODE_MOTION_ARROWS)
        if mode == VIEW_MODE_HEATMAP:
            batch = select(self._display_events(), *self._current_window(), polarity=self.polarity_combo.currentText())
            packed = batch.y.astype(np.int64) * self.hw[1] + batch.x
            self._heat_peak = int(np.bincount(packed).max()) if len(packed) else 0
        descriptions = {
            VIEW_MODE_RAW: "RAW • real event presence; no intensity normalization. + orange, − blue, both white.",
            VIEW_MODE_HEATMAP: f"DERIVED • {self.heat_scale.currentText()}; black = 0, red → yellow → white = increasing density. Window peak: {getattr(self, '_heat_peak', 0)} events/pixel. Relative scales map peak to white; absolute white = 100.",
            VIEW_MODE_PERSISTENCE: "DERIVED • latest real event per polarity/pixel, linear decay to zero over the persistence duration, ending at the interval's exclusive end.",
            VIEW_MODE_GLOW: "STYLIZED • polarity presence plus a 5×5 spatial halo. Halo pixels are styling, not additional events.",
            VIEW_MODE_TRAIL: "DERIVED • legacy time-colored accumulation in this interval; logarithmic scaling and relative normalization. No fading decay.",
            VIEW_MODE_MOTION_ARROWS: "DERIVED • legacy grid centroid displacement estimate, not measured optical flow. Two half-windows, minimum-event and displacement thresholds; normalized heatmap backdrop.",
        }
        prefix = "DERIVED filtered view: " + str(self.filter_settings) + "\n" if self.filtered_events is not None else ""
        if inherited:
            prefix='Loaded file has DERIVED processing provenance; original acquisition events are not reconstructed.\n'+prefix
        if self.filtered_events is not None:
            self.view_box.setTitle("DERIVED filtered | " + mode)
        self.view_mode_hint.setText(prefix + descriptions[mode] + "\nPolarity filter: " + self.polarity_combo.currentText())

    def _update_probe_table(self, t0, t1) -> None:
        self.roi_table.setRowCount(len(self.rois))
        for row, item in enumerate(self.rois):
            stats = self._probe_stats(item.roi,t0,t1)
            values = (item.name, str(stats.n_events), f"{stats.pos} / {stats.neg}",
                      f"{stats.events_per_ms:.4f}", str(stats.active_pixels))
            for column, value in enumerate(values):
                self.roi_table.setItem(row, column, QTableWidgetItem(value))

    def _update_slice_stats(self) -> None:
        row = self.slice_list.currentRow()
        if self.events is None or not (0 <= row < len(self.slices)):
            self.slice_stats.setText("Select a slice to inspect its saved interval.")
            return
        item = self.slices[row]
        roi = Roi(**item.roi_snapshot) if item.roi_snapshot else None
        cache_key = (id(self.events), item.id, item.t0, item.t1, item.polarity,tuple(sorted(item.filters.items())),
                     None if roi is None else (roi.x, roi.y, roi.w, roi.h))
        cached = getattr(self, "_slice_stats_cache", None)
        if cached is not None and cached[0] == cache_key:
            self.slice_stats.setText(cached[1])
            return
        from .filters import apply_filters
        source = self._display_events() if item.filters == self.filter_settings else apply_filters(self.events,item.filters)
        batch = select(source, item.t0, item.t1, roi, item.polarity)
        count = len(batch.t)
        pos = int(np.sum(batch.p > 0))
        active = len(np.unique(batch.y.astype(np.int64) * self.hw[1] + batch.x))
        duration = item.t1 - item.t0
        self.slice_stats.setText(f"Saved selection [{item.t0}, {item.t1}) µs | {duration} µs\n"
                                 f"Polarity: {item.polarity} | Events: {count:,} | + / −: {pos:,} / {count-pos:,}\n"
                                 f"{count / max(0.001, duration/1000):.4f} ev/ms | +/− ratio: {polarity_ratio(pos,count-pos):.4f} | Active pixels: {active:,}\n"
                                 "ROI bounds are saved with the slice; later ROI edits do not change its export.")
        self._slice_stats_cache = (cache_key, self.slice_stats.text())

    def _edit_slice_bounds(self) -> None:
        row = self.slice_list.currentRow()
        if self.events is not None and 0 <= row < len(self.slices):
            item = self.slices[row]
            item.t0, item.t1 = self._current_window()
            item.polarity = self.polarity_combo.currentText()
            item.filters = self.filter_settings.copy()
            self._rebuild_slice_list()
            self.slice_list.setCurrentRow(row)

    def _export_dialog(self, title, **selection) -> None:
        if self.events is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, title, str(self.data_dir / "exports" / "events.csv"), "CSV (*.csv)")
        if path:
            if not Path(path).suffix:
                path += ".csv"
            events, hw = self.events, self.hw
            self._run_task(lambda: export_csv(path, events, hw, **selection),
                           lambda count: self.statusBar().showMessage(f"Exported {count:,} original events and JSON metadata to {path}"),
                           "Exporting original event data…")

    def _set_sensor_resolution(self) -> None:
        if self.events is None:
            return
        text, ok = QInputDialog.getText(self, "Sensor resolution", "Actual width × height in pixels (for example 640x480):",
                                       text=f"{self.hw[1]}x{self.hw[0]}")
        if not ok:
            return
        try:
            width, height = map(int, text.lower().replace("×", "x").split("x"))
            if width <= int(self.events.x.max()) or height <= int(self.events.y.max()) or width * height > 16_777_216:
                raise ValueError("Resolution must contain all event coordinates and stay within 16 megapixels.")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid resolution", str(exc))
            return
        self.events = replace(self.events, metadata={**self.events.metadata,
                              "resolution": [width, height], "resolution_origin": "user-specified sensor dimensions"})
        self.hw = height, width
        if self.filtered_events is not None:
            self.filtered_events=replace(self.filtered_events,metadata={**self.filtered_events.metadata,
                'resolution':[width,height],'resolution_origin':self.events.metadata['resolution_origin']})
        self.analysis_panel.clear_analysis()
        self._update_stats_global()
        self._render_from_ui()

    def _export_full(self) -> None:
        self._export_dialog("Export full recording", extra={"type": "full recording", "filters": "none"})

    def _export_current(self) -> None:
        t0, t1 = self._current_window()
        roi = self.rois[self.active_roi_index].roi if self.active_roi_index is not None else None
        self._export_dialog("Export current selection", t0=t0, t1=t1, roi=roi,
                            polarity=self.polarity_combo.currentText(),filter_spec=self.filter_settings)

    def _save_session_as(self) -> None:
        if self.events is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Session", str(self.projects_root / "session.json"), "JSON (*.json)")
        if path:
            from .project_utils import save_json
            try:
                if not Path(path).suffix:
                    path += ".json"
                if Path(path).suffix.lower() != ".json":
                    raise ValueError("Session filenames must end in .json.")
                save_json(Path(path), self._build_session_dict())
                self.statusBar().showMessage(f"Session saved: {path}")
            except Exception as exc:
                QMessageBox.critical(self, "Session save failed", str(exc))

    def _load_session_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Load Session", str(self.projects_root), "JSON (*.json)")
        if path:
            try:
                session = json.loads(Path(path).read_text(encoding="utf-8"))
                self._restore_session(session)
            except Exception as exc:
                QMessageBox.critical(self, "Session load failed", str(exc))

    def _update_window_title(self) -> None:
        from .version import __version__
        self.setWindowTitle(f"Event-Based Studio {__version__} — {self.project_name}")

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
        if self._live_window is not None and self._live_window.worker is not None:
            self._live_window.stop_camera()
            event.ignore()
            return
        if self._task is not None:
            self.statusBar().showMessage("Finish the current import/export before closing.")
            event.ignore()
            return
        self.play_timer.stop()
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
        path, _ = QFileDialog.getOpenFileName(self, "Import DAT", str(Path.home()), "Event files (*.dat)")
        if not path:
            return
        def convert_and_load():
            out_dir = self.data_dir / "converted" / uuid4().hex[:12]
            h5 = convert_dat_to_h5_windows(path, out_dir=out_dir)
            csv_path = h5_to_csv_windows(h5, out_dir / (h5.stem + ".csv"))
            events = load_events_from_csv(csv_path)
            from .science import dat_resolution, fingerprint
            dimensions = dat_resolution(path)
            events.metadata.update({"original_path": path, "original_sha256": fingerprint(Path(path)),
                                    "conversion": "OpenEB DAT → H5 → CSV"})
            if "width" in dimensions and "height" in dimensions:
                width, height = dimensions["width"], dimensions["height"]
                if width <= int(events.x.max()) or height <= int(events.y.max()) or width * height > 16_777_216:
                    raise ValueError("DAT sensor metadata conflicts with converted event coordinates.")
                events.metadata.update({"resolution": [width, height], "resolution_origin": "DAT header"})
            return csv_path, events
        self._run_task(convert_and_load,
                       lambda result: self._load_csv_into_app(result[0], Path(path).stem, prepared_events=result[1]),
                       "Converting DAT → H5 → CSV and loading full recording…")

    def _load_csv_into_app(
        self,
        csv_path: Path,
        loaded_name: str,
        reset_annotations: bool = True,
        prepared_events=None,
    ) -> None:
        self.statusBar().showMessage("Loading events from CSV…")
        QApplication.processEvents()

        events = prepared_events if prepared_events is not None else load_events_from_csv(csv_path)
        hw = infer_hw(events)

        self.events = events
        self.hw = hw
        self.t_min = int(events.t.min()) if events.t.size else 0
        self.t_max = int(events.t.max()) if events.t.size else 0
        self.loaded_name = loaded_name
        self.loaded_csv_path = str(csv_path)
        self.position_us = self.t_min
        self.zoom_start, self.zoom_end = self.t_min, self.t_max + 1
        self.duration_us = min(50_000, self.t_max - self.t_min + 1)
        self.analysis_panel.clear_analysis()

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
            self.filtered_events = None
            self.filter_settings = {}
            self.annotations = []
            self.detections = []
            if self._workspace is not None:
                self._workspace.clear_results()
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
            self._sync_time_widgets()
            self.current_view_mode = VIEW_MODE_RAW
            self.view_mode_combo.setCurrentText(VIEW_MODE_RAW)

        self._render_from_ui()
        self._update_stats_global()
        self._update_timeline_slice_regions()

        self.statusBar().showMessage(
            f"Loaded {len(events.t):,} events | {'Complete recording' if events.metadata.get('complete') else 'LIMITED PREVIEW'} | {hw[1]}x{hw[0]} ({events.metadata.get('resolution_origin')}) | {Path(csv_path).name}"
        )

    def _roi_to_dict(self, roi_item: NamedROI) -> dict:
        return {
            "id": roi_item.id,
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
            "id": s.id,
            "filters": s.filters,
            "roi_id": s.roi_id,
            "roi_snapshot": s.roi_snapshot,
            "polarity": s.polarity,
            "source_sha256": s.source_sha256,
            "name": s.name,
            "t0": int(s.t0),
            "t1": int(s.t1),
            "roi_index": None if s.roi_index is None else int(s.roi_index),
            "color": s.color,
        }

    def _build_session_dict(self) -> dict:
        return {
            "format_version": 8,
            "project_name": self.project_name,
            "filters": self.filter_settings,
            "analysis_settings": self.analysis_settings,
            "annotations": self.annotations,
            "detections": self.detections,
            "source": {
                "loaded_name": self.loaded_name,
                "csv_path": self.loaded_csv_path,
                "max_events": None,
                "metadata": self.events.metadata if self.events is not None else {},
            },
            "view": {
                "timeline_value": int(self.timeline.value()),
                "window_ms": self.duration_us / 1000,
                "position_us": self.position_us,
                "duration_us": self.duration_us,
                "zoom_start": self.zoom_start,
                "zoom_end": self.zoom_end,
                "step_us": self.step_us.value(),
                "polarity": self.polarity_combo.currentText(),
                "comparison": self.compare_check.isChecked(),
                "persistence_ms": self.persistence_ms.value(),
                "glow_intensity": self.glow_intensity.value(),
                "heat_scale": self.heat_scale.currentText(),
                "is_playing": bool(self.is_playing),
                "show_roi_overlays": bool(self.chk_show_rois.isChecked()),
                "active_roi_index": self.active_roi_index,
                "selected_slice_index": self.slice_list.currentRow(),
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

        window_us = self.duration_us
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
        if self.events is None or not self.loaded_csv_path:
            QMessageBox.warning(self, "Save Project", "Load a dataset before saving the project.")
            return
        if self.current_project_dir is None:
            self.current_project_dir = create_project_dir(self.projects_root, self.loaded_name or "Untitled Project")
            self.project_name = self.current_project_dir.name
            self._update_window_title()
        session = self._build_session_dict()
        thumb = self.current_frame.copy() if self.current_frame is not None else None
        events, hw, mode = self._display_events(), self.hw, self.current_view_mode
        parameters, duration = self._render_parameters(), self.duration_us
        directory, name = self.current_project_dir, self.project_name
        starts = np.linspace(self.t_min, max(self.t_min, self.t_max - duration + 1), 10, dtype=np.int64)
        def save():
            previews = [rendering.render_frame(events, hw, int(t), duration, mode, parameters) for t in starts]
            save_project_bundle(directory, name, session, thumb, previews)
            return directory
        def complete(result):
            self.current_session_path = str(session_json_path(result))
            self.statusBar().showMessage(f"Project saved: {result}")
            if self.browser_ref is not None:
                self.browser_ref.refresh_projects()
        self._run_task(save, complete, "Saving session, thumbnail and previews...")

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

    def _restore_session(self, session: dict, prepared_events=None) -> None:
        from .session_validation import validate_settings
        from .filters import apply_filters
        validate_settings(session)
        settings = session.get("filters", {})
        if prepared_events is None:
            source = Path(session.get("source", {}).get("csv_path", ""))
            def prepare(cancel, progress):
                raw = load_events_from_csv(source)
                if cancel():
                    from .filters import CancelledError
                    raise CancelledError('Session restoration cancelled; previous analysis preserved.')
                return raw, apply_filters(raw,settings,cancel,progress)
            self._run_task(prepare,lambda result:self._restore_session(session,result),
                           "Restoring analysis dataset and filters...",cooperative=True)
            return
        raw, filtered = prepared_events if isinstance(prepared_events,tuple) else (prepared_events,apply_filters(prepared_events,settings))
        previous = self._build_session_dict() if self.events is not None else None
        previous_events, previous_name = self.events, self.project_name
        previous_filtered, previous_settings = self.filtered_events, self.filter_settings
        self.filtered_events = filtered if any(settings.values()) else None
        self.filter_settings = dict(settings)
        try:
            self._apply_session(session, raw)
        except Exception:
            self._restoring = False
            self.filtered_events, self.filter_settings = previous_filtered, previous_settings
            if previous is not None:
                self._apply_session(previous, previous_events)
            else:
                self._reset_view()
            self.project_name = previous_name
            self._update_window_title()
            raise

    def _apply_session(self, session: dict, prepared_events=None) -> None:
        version = session.get("format_version")
        if version not in (1, 2, 3, 4, 5, 6, 7, 8):
            raise ValueError(f"Unsupported session format version: {version}")

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
        if prepared_events is None:
            self._run_task(lambda: load_events_from_csv(csv_path),
                           lambda events: self._restore_session(session, events), "Restoring full session dataset…")
            return
        expected_hash = source.get("metadata", {}).get("sha256")
        if expected_hash and expected_hash != prepared_events.metadata.get("sha256"):
            raise ValueError("Source CSV content has changed since this session was saved. Open it as a new recording instead.")

        def valid_box(box):
            return all(isinstance(box.get(key), int) for key in ("x", "y", "w", "h")) and min(box["x"], box["y"]) >= 0 and min(box["w"], box["h"]) > 0

        roi_ids = [item.get("id") for item in rois_data if item.get("id")]
        slice_ids = [item.get("id") for item in slices_data if item.get("id")]
        if len(set(roi_ids)) != len(roi_ids) or len(set(slice_ids)) != len(slice_ids):
            raise ValueError("Session contains duplicate ROI or slice IDs.")
        for item in rois_data:
            if not valid_box(item):
                raise ValueError("Session contains invalid ROI bounds; analysis was not restored.")
        for item in slices_data:
            if not isinstance(item.get("t0"), int) or not isinstance(item.get("t1"), int) or item["t1"] <= item["t0"]:
                raise ValueError("Session contains an invalid slice interval.")
            if item.get("polarity", "both") not in ("both", "pos", "neg"):
                raise ValueError("Session contains an unknown slice polarity filter.")
            if item.get("roi_snapshot") and not valid_box(item["roi_snapshot"]):
                raise ValueError("Session contains invalid saved slice ROI bounds.")
            if item.get("roi_index") is not None and not item.get("roi_snapshot") and not (0 <= int(item["roi_index"]) < len(rois_data)):
                raise ValueError("A slice references a missing ROI without saved spatial bounds.")
            if item.get("source_sha256") and item["source_sha256"] != prepared_events.metadata.get("sha256"):
                raise ValueError("A slice belongs to a different source recording.")
        for item in session.get('annotations',[]) + session.get('detections',[]):
            if item.get('source_sha256') and item['source_sha256']!=prepared_events.metadata.get('sha256'):
                raise ValueError('An annotation or detection belongs to a different source recording.')
        if view.get("polarity", "both") not in ("both", "pos", "neg"):
            raise ValueError("Session contains an unknown polarity filter.")

        self.statusBar().showMessage("Loading session dataset…")
        QApplication.processEvents()

        events = prepared_events
        saved_metadata = source.get("metadata", {})
        if saved_metadata.get("resolution"):
            width, height = map(int, saved_metadata["resolution"])
            if width <= int(events.x.max()) or height <= int(events.y.max()) or width * height > 16_777_216:
                raise ValueError("Saved sensor resolution conflicts with event coordinates.")
            events = replace(events, metadata={**events.metadata, **saved_metadata,
                             "complete": True, "loaded_events": len(events.t), "load_limit": None})
        self._restoring = True
        self.project_name = session.get("project_name", self.project_name)
        self._update_window_title()
        hw = infer_hw(events)

        self.events = events
        self.hw = hw
        if self.filtered_events is not None and prepared_events is not None:
            self.filtered_events=replace(self.filtered_events,metadata={**self.filtered_events.metadata,
                'resolution':list(events.metadata.get('resolution',[hw[1],hw[0]])),
                'resolution_origin':events.metadata.get('resolution_origin','unknown')})
        self.t_min = int(events.t.min()) if events.t.size else 0
        self.t_max = int(events.t.max()) if events.t.size else 0
        self.loaded_name = loaded_name
        self.loaded_csv_path = str(csv_path)
        # Older versions skipped the first numeric row of headerless CSVs and
        # navigated only their capped prefix. Preserve that historical time.
        skip = 0 if events.metadata.get("header_present", True) else min(1, len(events.t) - 1)
        legacy_limit = int(source.get("max_events") or 2_000_000)
        legacy_min = int(events.t[skip])
        legacy_max = int(events.t[min(len(events.t) - 1, skip + legacy_limit - 1)])
        legacy_position = int(legacy_min + int(view.get("timeline_value", 0)) / 1000 * (legacy_max - legacy_min))
        self.position_us = int(view.get("position_us", legacy_position))
        self.position_us = max(self.t_min, min(self.t_max, self.position_us))
        self.duration_us = max(1, int(view.get("duration_us", float(view.get("window_ms", 50)) * 1000)))
        self.zoom_start = max(self.t_min, min(self.t_max, int(view.get("zoom_start", self.t_min))))
        self.zoom_end = max(self.zoom_start + 1, min(self.t_max + 1, int(view.get("zoom_end", self.t_max + 1))))
        self.analysis_panel.clear_analysis()

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
                        id=str(item.get("id") or uuid4().hex),
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
                if item.get("roi_id"):
                    roi_index = next((index for index, roi in enumerate(self.rois) if roi.id == item["roi_id"]), None)
                if roi_index is not None and not (0 <= roi_index < len(self.rois)):
                    roi_index = None

                self.slices.append(
                    Slice(
                        id=str(item.get("id") or uuid4().hex),
                        roi_id=item.get("roi_id") or (self.rois[roi_index].id if roi_index is not None else None),
                        roi_snapshot=item.get("roi_snapshot") or (vars(self.rois[roi_index].roi).copy() if roi_index is not None else None),
                        polarity=item.get("polarity", "both"),
                        source_sha256=item.get("source_sha256") or events.metadata.get("sha256", ""),
                        filters=item.get("filters", {}),
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
            VIEW_MODE_PERSISTENCE,
            VIEW_MODE_GLOW,
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
        self.compare_view.set_show_overlays(show_rois)

        self.view_mode_combo.blockSignals(True)
        self.view_mode_combo.setCurrentText(self.current_view_mode)
        self.view_mode_combo.blockSignals(False)

        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._rebuild_slice_list()
        selected_slice = int(view.get("selected_slice_index", -1))
        if 0 <= selected_slice < len(self.slices):
            self.slice_list.setCurrentRow(selected_slice)
        self._update_timeline_slice_regions()
        self._update_loop_button_text()

        self.window_ms.blockSignals(True)
        self.window_ms.setValue(window_value)
        self.window_ms.blockSignals(False)

        self.timeline.blockSignals(True)
        self.timeline.setValue(timeline_value)
        self.timeline.blockSignals(False)

        self.polarity_combo.setCurrentText(view.get("polarity", "both"))
        self.persistence_ms.setValue(float(view.get("persistence_ms", 100)))
        self.glow_intensity.setValue(float(view.get("glow_intensity", 0.7)))
        self.heat_scale.setCurrentText(view.get("heat_scale", "Log relative"))
        self.step_us.setValue(int(view.get("step_us", 1000)))
        self.compare_check.setChecked(bool(view.get("comparison", False)))
        self.analysis_settings = session.get("analysis_settings", {})
        self.annotations = session.get("annotations", [])
        self.detections = session.get("detections", [])
        if self._workspace is not None:
            self._workspace.clear_results()
        self._restoring = False
        self._sync_time_widgets()
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
        return self.position_us, self.position_us + self.duration_us


    def _time_us_to_slider_value(self, t_us: int) -> int:
        span = max(1, self.zoom_end - self.zoom_start)
        return max(0, min(1_000_000, ((t_us - self.zoom_start) * 1_000_000) // span))


    def _slider_value_to_time_us(self, value: int) -> int:
        return self.zoom_start + (value * max(1, self.zoom_end - self.zoom_start)) // 1_000_000


    def _update_timeline_slice_regions(self) -> None:
        markers = self.detections + self.annotations if self.events is not None else []
        self.timeline.set_analysis_markers([
            {"index":i,"start_value":self._time_us_to_slider_value(item['t0']),
             "end_value":self._time_us_to_slider_value(item['t1']),
             "color":"#ff9500" if i < len(self.detections) else "#64d2ff"}
            for i,item in enumerate(markers) if item['t1'] >= self.zoom_start and item['t0'] <= self.zoom_end])
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
        batch = self._window_batch(t0,t1)
        return batch if len(batch.t) else None


    def _render_parameters(self):
        return {"polarity": self.polarity_combo.currentText(),
                "heat_scale": self.heat_scale.currentText(),
                "persistence_us": int(round(self.persistence_ms.value() * 1000)),
                "glow": self.glow_intensity.value(), "grid": self.arrow_grid_spin.value(),
                "scale": self.arrow_scale_spin.value(), "minimum": self.arrow_min_events_spin.value(),
                "silhouette": self.arrow_silhouette_spin.value()}

    def _render_mode_frame(self, t0: int, window_us: int) -> np.ndarray:
        return rendering.render_frame(self._display_events(), self.hw, t0, window_us,
                                      self.current_view_mode, self._render_parameters())

    def _render_from_ui(self) -> None:
        if self.events is None or self.hw is None or self._restoring:
            return

        t0, t1 = self._current_window()
        window_us = self.duration_us
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
        self._sync_time_widgets()
        self._update_mode_description()
        if self.compare_check.isChecked():
            self.compare_view.set_frame(rendering.raw(self.events, self.hw, t0, t1))
        self._update_probe_table(t0, t1)
        self._update_slice_stats()
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
        dur_us = int(self.t_max - self.t_min + 1)
        dur_ms = dur_us / 1000.0
        events_per_ms = total / dur_ms if dur_ms > 0 else 0.0

        self.stats_global.setText(
            "\n".join(
                [
                    "Global",
                    f"Events: {total:,}",
                    f"Resolution: {w}x{h} ({self.events.metadata.get('resolution_origin', 'unknown')})",
                    "Complete recording" if self.events.metadata.get("complete") else "LIMITED PREVIEW — export disabled",
                    f"+ / −: {int(np.sum(self.events.p > 0)):,} / {int(np.sum(self.events.p <= 0)):,}",
                    f"Active pixels: {len(np.unique(self.events.y.astype(np.int64) * w + self.events.x)):,}",
                    f"+/− ratio: {polarity_ratio(int(np.sum(self.events.p > 0)), int(np.sum(self.events.p <= 0))):.4f}",
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

        stats = self._probe_stats(roi,t0,t1)

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
        window_us = self.duration_us

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
        self.view.set_candidate_roi(self._candidate_roi)
        self.compare_view.set_candidate_roi(self._candidate_roi)

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
        self._push_rois_to_view()
        self._update_roi_status_label()

        t0, t1 = self._current_window()
        self._update_stats_active_roi(t0, t1)
        self._update_probe_table(t0, t1)
        self._refresh_analysis_panel()
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
        row = self.roi_list.currentRow()
        if self.events is not None and 0 <= row < len(self.rois):
            item = self.rois[row]
            self._export_dialog("Export ROI", roi=item.roi, extra={"roi_id": item.id, "roi_name": item.name})


    def _delete_selected_roi(self) -> None:
        row = self.roi_list.currentRow()
        if row < 0 or row >= len(self.rois):
            return

        for item in self.slices:
            if item.roi_index == row and item.roi_snapshot is None:
                item.roi_snapshot = vars(self.rois[row].roi).copy()
                item.roi_id = self.rois[row].id
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
        for item in self.slices:
            if item.roi_snapshot is None and item.roi_index is not None and item.roi_index < len(self.rois):
                item.roi_snapshot = vars(self.rois[item.roi_index].roi).copy()
                item.roi_id = self.rois[item.roi_index].id
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
        self.compare_view.set_show_overlays(self.chk_show_rois.isChecked())

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
        self._update_slice_stats()

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
        self.compare_view.set_rois(visible_rois, active_index=active_vis_idx)
        if self.events is not None:
            self._update_probe_table(*self._current_window())

    def _rebuild_slice_list(self) -> None:
        self.slice_list.blockSignals(True)
        self.slice_list.clear()

        for s in self.slices:
            roi_tag = ""
            if s.roi_index is not None and 0 <= s.roi_index < len(self.rois):
                roi_tag = f' | ROI="{self.rois[s.roi_index].name}"'
            elif s.roi_snapshot:
                roi_tag = " | saved ROI bounds"
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
                roi_id=self.rois[roi_index].id if roi_index is not None else None,
                roi_snapshot=vars(self.rois[roi_index].roi).copy() if roi_index is not None else None,
                polarity=self.polarity_combo.currentText(),
                source_sha256=self.events.metadata.get("sha256", ""),
                filters=self.filter_settings.copy(),
            )
        )
        self._rebuild_slice_list()
        self.slice_list.setCurrentRow(len(self.slices) - 1)
        self._update_timeline_slice_regions()

    def _jump_to_selected_slice(self) -> None:
        row = self.slice_list.currentRow()
        if self.events is None or not (0 <= row < len(self.slices)):
            return
        item = self.slices[row]
        if item.filters != self.filter_settings:
            self._apply_filter_settings(item.filters,self._jump_to_selected_slice)
            return
        self.duration_us = item.t1 - item.t0
        self.polarity_combo.blockSignals(True)
        self.polarity_combo.setCurrentText(item.polarity)
        self.polarity_combo.blockSignals(False)
        if item.roi_id:
            self.active_roi_index = next((i for i, roi in enumerate(self.rois) if roi.id == item.roi_id), None)
        else:
            self.active_roi_index = item.roi_index
        self._rebuild_roi_list()
        self._push_rois_to_view()
        self._seek(item.t0)
        self._update_roi_status_label()


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
        row = self.slice_list.currentRow()
        if self.events is None or not (0 <= row < len(self.slices)):
            return
        item = self.slices[row]
        if item.source_sha256 and item.source_sha256 != self.events.metadata.get("sha256"):
            QMessageBox.warning(self, "Source mismatch", "This slice belongs to a different recording.")
            return
        roi = Roi(**item.roi_snapshot) if item.roi_snapshot else None
        if roi is None and item.roi_index is not None and item.roi_index < len(self.rois):
            roi = self.rois[item.roi_index].roi
        self._export_dialog("Export slice", t0=item.t0, t1=item.t1, roi=roi,
                            polarity=item.polarity, filter_spec=item.filters, extra={"slice_id": item.id, "name": item.name})


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
        if not self.is_playing or self.events is None:
            return
        target = self.position_us + self.step_us.value()
        if self.loop_slice_index is not None and 0 <= self.loop_slice_index < len(self.slices):
            item = self.slices[self.loop_slice_index]
            if target >= item.t1 or target < item.t0:
                target = item.t0
        elif target > self.t_max:
            target = self.t_max
            self._toggle_play()
        self._seek(target)


    def _reset_view(self) -> None:
        self.play_timer.stop()
        self.is_playing = False
        self.play_btn.setText("Play")
        self.play_btn.setEnabled(False)

        self.timeline.setEnabled(False)
        self.window_ms.setEnabled(False)

        self.position_us = 0
        self.duration_us = 50_000
        self.zoom_start, self.zoom_end = 0, 1
        self.filtered_events = None
        self.filter_settings = {}
        self.annotations = []
        self.detections = []
        self.timeline.set_analysis_markers([])
        self.events = None
        self.hw = None
        self.t_min = 0
        self.t_max = 0
        self.loaded_name = ""
        self.loaded_csv_path = ""
        self.current_frame = None
        self._slice_stats_cache = None
        self.roi_table.setRowCount(0)
        self.compare_view.set_frame(np.zeros((10, 10), dtype=np.uint8))

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
        self.compare_view.set_show_overlays(True)

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
        if self._workspace is not None:
            self._workspace.clear_results()
            self._workspace.hide()


def main() -> None:
    app = QApplication(sys.argv)
    from .theme import configure_application
    configure_application(app)
    _try_show_boot(app)

    project_root = Path(__file__).resolve().parents[1]
    projects_root = project_root / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)

    windows: list[MainWindow] = []

    def open_project(project_dir: str) -> None:
        browser.hide()
        win = MainWindow(browser_ref=browser, project_dir=project_dir)
        win.setAttribute(Qt.WA_DeleteOnClose, True)
        win.resize(1600, 950)
        win.show()
        windows.append(win)
        win.destroyed.connect(lambda _=None, window=win: windows.remove(window) if window in windows else None)

    browser = ProjectBrowser(projects_root=projects_root, open_project_callback=open_project)
    browser.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
