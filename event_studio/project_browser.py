from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .project_utils import create_project_dir, list_projects, rename_project, sanitize_project_name


class ProjectTile(QFrame):
    openRequested = Signal(str)

    def __init__(self, project_info: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project_info = project_info
        self.project_dir = project_info["project_dir"]
        self.preview_frames = project_info.get("preview_frames", []) or []
        self._preview_index = 0

        self.setObjectName("ProjectTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet(
            """
            QFrame#ProjectTile {
                border: 1px solid #3a3a3a;
                border-radius: 10px;
                background: #1f1f1f;
            }
            QFrame#ProjectTile:hover {
                border: 1px solid #7c5cff;
                background: #262626;
            }
            QLabel {
                color: #f0f0f0;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        self.image_label = QLabel()
        self.image_label.setFixedSize(260, 150)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setStyleSheet("background: #111; border-radius: 8px;")
        root.addWidget(self.image_label)

        self.title_label = QLabel(project_info.get("project_name", "Untitled Project"))
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        root.addWidget(self.title_label)

        source_name = Path(project_info.get("source_csv_path", "")).name if project_info.get("source_csv_path") else "No dataset yet"
        self.source_label = QLabel(source_name)
        self.source_label.setStyleSheet("color: #b8b8b8;")
        root.addWidget(self.source_label)

        last_saved = project_info.get("last_saved_at", "") or "Unknown"
        self.saved_label = QLabel(f"Last saved: {last_saved}")
        self.saved_label.setStyleSheet("color: #9d9d9d; font-size: 11px;")
        root.addWidget(self.saved_label)

        self.open_btn = QPushButton("Open Project")
        self.open_btn.clicked.connect(self._emit_open)
        root.addWidget(self.open_btn)

        self.preview_timer = QTimer(self)
        self.preview_timer.timeout.connect(self._advance_preview)
        self.preview_timer.setInterval(120)

        self._set_initial_image()

    def _pixmap_for(self, path_str: str) -> QPixmap:
        pm = QPixmap(path_str)
        if pm.isNull():
            return QPixmap()
        return pm.scaled(
            self.image_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )

    def _set_initial_image(self) -> None:
        thumb = self.project_info.get("thumbnail_path", "")
        if thumb:
            pm = self._pixmap_for(thumb)
            if not pm.isNull():
                self.image_label.setPixmap(pm)
                return
        self.image_label.setText("No Preview")

    def _advance_preview(self) -> None:
        if not self.preview_frames:
            return
        path_str = self.preview_frames[self._preview_index]
        pm = self._pixmap_for(path_str)
        if not pm.isNull():
            self.image_label.setPixmap(pm)
        self._preview_index = (self._preview_index + 1) % len(self.preview_frames)

    def _emit_open(self) -> None:
        self.openRequested.emit(self.project_dir)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._emit_open()
            return
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:
        if self.preview_frames:
            self._preview_index = 0
            self.preview_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.preview_timer.stop()
        self._set_initial_image()
        super().leaveEvent(event)


class ProjectBrowser(QMainWindow):
    def __init__(
        self,
        projects_root: Path,
        open_project_callback: Callable[[str], None],
    ) -> None:
        super().__init__()
        self.projects_root = Path(projects_root)
        self.open_project_callback = open_project_callback

        self.setWindowTitle("Event-Based Studio — Project Browser")
        self.resize(1180, 760)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(12)

        header = QHBoxLayout()
        root.addLayout(header)

        title = QLabel("Projects")
        title.setStyleSheet("font-size: 26px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch(1)

        self.btn_live = QPushButton("Live Camera")
        self.btn_live.clicked.connect(self._open_live_camera)
        header.addWidget(self.btn_live)

        self.btn_new = QPushButton("New Project")
        self.btn_new.clicked.connect(self._create_project)
        header.addWidget(self.btn_new)

        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_projects)
        header.addWidget(self.btn_refresh)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.scroll)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.scroll.setWidget(self.grid_host)

        self.refresh_projects()

    def _clear_grid(self) -> None:
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _open_live_camera(self) -> None:
        from .live_window import show_live_camera
        self._live_window = show_live_camera()

    def refresh_projects(self) -> None:
        self._clear_grid()

        projects = list_projects(self.projects_root)
        if not projects:
            empty = QLabel("No projects yet. Click New Project to start.")
            empty.setStyleSheet("font-size: 16px; color: #bdbdbd;")
            self.grid.addWidget(empty, 0, 0)
            return

        cols = 3
        for i, proj in enumerate(projects):
            tile = ProjectTile(proj)
            tile.openRequested.connect(self._open_project_from_tile)

            row = i // cols
            col = i % cols
            self.grid.addWidget(tile, row, col)

    def _create_project(self) -> None:
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok:
            return

        name = sanitize_project_name(name)
        if not name:
            name = "Untitled Project"

        project_dir = create_project_dir(self.projects_root, name)
        rename_project(project_dir, name)
        self.refresh_projects()
        self.open_project_callback(str(project_dir))

    def _open_project_from_tile(self, project_dir: str) -> None:
        self.open_project_callback(project_dir)
