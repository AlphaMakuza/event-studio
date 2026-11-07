from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable
from PySide6.QtCore import Qt, QTimer, Signal, QSettings
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from .project_utils import (
    create_project_dir,
    list_projects,
    rename_project,
    sanitize_project_name,
)


def saved_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y  ·  %H:%M")
    except (ValueError, TypeError):
        return "Not saved yet"


class ProjectTile(QFrame):
    openRequested = Signal(str)

    def __init__(self, project_info, parent=None, *, view="cards"):
        super().__init__(parent)
        self.project_info = project_info
        self.project_dir = project_info["project_dir"]
        self.preview_frames = project_info.get("preview_frames", []) or []
        self._preview_index = 0
        self.view = view
        self.setObjectName("ProjectTile")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(
            f"Open {project_info.get('project_name','Untitled Project')}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(240)
        self.setFixedHeight(263 if view == "cards" else 92 if view == "rows" else 72)
        root = QVBoxLayout(self) if view == "cards" else QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setObjectName("ProjectPreview")
        if view == "cards":
            self.image_label.setFixedHeight(150)
            root.addWidget(self.image_label)
        elif view == "rows":
            self.image_label.setFixedSize(96, 64)
            root.addWidget(self.image_label)
        else:
            self.image_label.hide()
        details = QVBoxLayout()
        details.setSpacing(5)
        name = project_info.get("project_name", "Untitled Project")
        self.title_label = QLabel(name)
        self.title_label.setObjectName("ProjectTitle")
        self.title_label.setToolTip(name)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        details.addWidget(self.title_label)
        source = Path(project_info.get("source_csv_path", "")).name or "No dataset yet"
        self.source_label = QLabel(source)
        self.source_label.setObjectName("Muted")
        self.source_label.setToolTip(source)
        self.source_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        details.addWidget(self.source_label)
        root.addLayout(details, 1)
        self.saved_label = QLabel(saved_date(project_info.get("last_saved_at", "")))
        self.saved_label.setObjectName("Muted")
        self.saved_label.setToolTip("Last saved")
        root.addWidget(self.saved_label)
        if view != "cards":
            self.open_btn = QPushButton("Open")
            self.open_btn.setAccessibleName(f"Open {name}")
            self.open_btn.clicked.connect(self._emit_open)
            root.addWidget(self.open_btn)
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(120)
        self.preview_timer.timeout.connect(self._advance_preview)
        self._set_initial_image()

    def _show_image(self, path):
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if pixmap.isNull():
            return False
        self.image_label.setPixmap(
            pixmap.scaled(
                self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
        )
        return True

    def _set_initial_image(self):
        if self.view != "text" and not self._show_image(
            self.project_info.get("thumbnail_path", "")
        ):
            self.image_label.setText("NO PREVIEW")

    def _advance_preview(self):
        if self.preview_frames:
            self._show_image(self.preview_frames[self._preview_index])
            self._preview_index = (self._preview_index + 1) % len(self.preview_frames)

    def _emit_open(self):
        self.openRequested.emit(self.project_dir)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._emit_open()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._emit_open()
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event):
        if self.preview_frames and self.view != "text":
            self._preview_index = 0
            self.preview_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.preview_timer.stop()
        self._set_initial_image()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_initial_image()


class ProjectBrowser(QMainWindow):
    def __init__(
        self,
        projects_root: Path,
        open_project_callback: Callable[[str], None],
        *,
        settings=None,
    ):
        super().__init__()
        self.projects_root = Path(projects_root)
        self.open_project_callback = open_project_callback
        self.settings = (
            settings
            if settings is not None
            else QSettings("EventBasedStudio", "ProjectBrowser")
        )
        self.projects = []
        self._columns = 0
        self.setWindowTitle("Event-Based Studio — Projects")
        self.resize(1180, 760)
        self.setMinimumSize(760, 500)
        self.setStyleSheet("""
            QMainWindow, QWidget#Browser { background: #232323; color: #dedede; }
            QFrame#Sidebar { background: #1c1c1c; border-right: 1px solid #393939; }
            QLabel { background: transparent; color: #dedede; }
            QLabel#Brand { font-size: 21px; font-weight: 600; }
            QLabel#Eyebrow { color: #d69a56; font-size: 10px; }
            QLabel#Heading { font-size: 24px; font-weight: 600; }
            QLabel#Muted { color: #999999; font-size: 11px; }
            QLabel#ProjectTitle { font-size: 14px; font-weight: 600; }
            QLabel#ProjectPreview { background: #151515; color: #666666; font-size: 10px; }
            QPushButton { background: #303030; color: #dddddd; border: 1px solid #444444;
                          border-radius: 4px; padding: 8px 12px; text-align: left; }
            QPushButton:hover { background: #3b3b3b; border-color: #777777; }
            QPushButton#Primary { background: #d49b57; border-color: #d49b57; color: #171717; font-weight: 600; }
            QPushButton#Selected { background: #32302b; border-color: #65523a; color: #e6b477; }
            QLineEdit, QComboBox { background: #303030; color: #dddddd; border: 1px solid #464646;
                                 border-radius: 4px; padding: 7px 9px; }
            QLineEdit:focus, QComboBox:focus { border-color: #d49b57; }
            QComboBox QAbstractItemView { background: #303030; color: #eeeeee; selection-background-color: #665033; }
            QScrollArea, QWidget#ProjectHost { background: #232323; border: none; }
            QFrame#ProjectTile { background: #292929; border: 1px solid #3b3b3b; border-radius: 5px; }
            QFrame#ProjectTile:hover { background: #303030; border-color: #b68a52; }
            QFrame#ProjectTile:focus { border-color: #e6b477; }
        """)
        central = QWidget()
        central.setObjectName("Browser")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        brand = QHBoxLayout()
        brand.setContentsMargins(24, 18, 24, 18)
        from .boot import logo_pixmap

        logo = QLabel()
        logo.setPixmap(
            logo_pixmap().scaled(48, 48, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        brand.addWidget(logo)
        words = QVBoxLayout()
        title = QLabel("Event-Based Studio")
        title.setObjectName("Brand")
        subtitle = QLabel("RECORD  /  EXPLORE  /  ANALYZE")
        subtitle.setObjectName("Eyebrow")
        words.addWidget(title)
        words.addWidget(subtitle)
        brand.addLayout(words)
        brand.addStretch()
        from .version import __version__

        version = QLabel(__version__)
        version.setObjectName("Muted")
        brand.addWidget(version)
        root.addLayout(brand)
        body = QHBoxLayout()
        body.setSpacing(0)
        root.addLayout(body, 1)
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(190)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 22, 16, 18)
        nav.setSpacing(10)
        section = QLabel("WORKSPACE")
        section.setObjectName("Eyebrow")
        nav.addWidget(section)
        self.btn_new = QPushButton("+  New project")
        self.btn_new.setObjectName("Primary")
        self.btn_new.clicked.connect(self._create_project)
        nav.addWidget(self.btn_new)
        local = QPushButton("Local projects")
        local.setObjectName("Selected")
        local.clicked.connect(self._reset_filters)
        nav.addWidget(local)
        self.btn_live = QPushButton("Live Camera")
        self.btn_live.clicked.connect(self._open_live_camera)
        nav.addWidget(self.btn_live)
        nav.addStretch()
        caption = QLabel("Your recordings.\nYour workspace.")
        caption.setObjectName("Muted")
        nav.addWidget(caption)
        body.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(24, 22, 24, 12)
        content.setSpacing(16)
        body.addLayout(content, 1)
        heading = QLabel("Local projects")
        heading.setObjectName("Heading")
        content.addWidget(heading)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search projects or datasets…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search projects")
        toolbar.addWidget(self.search, 1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Recently saved", "recent")
        self.sort_combo.addItem("Name A–Z", "name")
        self.sort_combo.setAccessibleName("Sort projects")
        toolbar.addWidget(self.sort_combo)
        self.view_combo = QComboBox()
        for text, value in [
            ("Image + text", "rows"),
            ("Text only", "text"),
            ("Large tiles", "cards"),
        ]:
            self.view_combo.addItem(text, value)
        self.view_combo.setAccessibleName("Project view")
        self.view_combo.setCurrentIndex(
            max(0, self.view_combo.findData(self.settings.value("view", "rows")))
        )
        toolbar.addWidget(self.view_combo)
        self.btn_refresh = QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self.refresh_projects)
        toolbar.addWidget(self.btn_refresh)
        content.addLayout(toolbar)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        content.addWidget(self.scroll, 1)
        self.grid_host = QWidget()
        self.grid_host.setObjectName("ProjectHost")
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        self.grid.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.grid_host)
        self.count_label = QLabel()
        self.count_label.setObjectName("Muted")
        content.addWidget(self.count_label)
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(100)
        self._resize_timer.timeout.connect(self._resize_grid)
        self.search.textChanged.connect(self._render_projects)
        self.sort_combo.currentIndexChanged.connect(self._render_projects)
        self.view_combo.currentIndexChanged.connect(self._view_changed)
        self.refresh_projects()

    def _reset_filters(self):
        self.search.clear()
        self.refresh_projects()

    def _clear_grid(self):
        while self.grid.count():
            widget = self.grid.takeAt(0).widget()
            if widget is not None:
                if isinstance(widget, ProjectTile):
                    widget.preview_timer.stop()
                widget.hide()
                widget.deleteLater()
        for column in range(self._columns):
            self.grid.setColumnStretch(column, 0)

    def _open_live_camera(self):
        from .live_window import show_live_camera

        self._live_window = show_live_camera()

    def refresh_projects(self):
        self.projects = list_projects(self.projects_root)
        self._render_projects()

    def _view_changed(self):
        self.settings.setValue("view", self.view_combo.currentData())
        self._render_projects()

    def _column_count(self):
        return (
            max(1, self.scroll.viewport().width() // 270)
            if self.view_combo.currentData() == "cards"
            else 1
        )

    def _resize_grid(self):
        if self._column_count() != self._columns:
            self._render_projects()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_resize_timer"):
            self._resize_timer.start()

    def _render_projects(self):
        self._clear_grid()
        query = self.search.text().strip().casefold()
        projects = [
            p
            for p in self.projects
            if query
            in (
                p["project_name"] + " " + Path(p.get("source_csv_path", "")).name
            ).casefold()
        ]
        if self.sort_combo.currentData() == "name":
            projects.sort(key=lambda p: p["project_name"].casefold())
        else:
            projects.sort(key=lambda p: p.get("last_saved_at", "") or "", reverse=True)
        self._columns = self._column_count()
        for column in range(self._columns):
            self.grid.setColumnStretch(column, 1)
        self.count_label.setText(
            f"{len(projects)} of {len(self.projects)} projects  ·  Stored locally"
        )
        if not projects:
            empty = QLabel(
                "No matching projects. Try another search."
                if self.projects
                else "Your next discovery starts here.\n\nCreate a new project to explore a recording."
            )
            empty.setObjectName("Muted")
            empty.setAlignment(Qt.AlignCenter)
            empty.setMinimumHeight(200)
            self.grid.addWidget(empty, 0, 0, 1, self._columns)
        for i, project in enumerate(projects):
            tile = ProjectTile(project, view=self.view_combo.currentData())
            tile.openRequested.connect(self._open_project_from_tile)
            self.grid.addWidget(tile, i // self._columns, i % self._columns)

    def _create_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok:
            return
        name = sanitize_project_name(name) or "Untitled Project"
        project_dir = create_project_dir(self.projects_root, name)
        rename_project(project_dir, name)
        self.refresh_projects()
        self.open_project_callback(str(project_dir))

    def _open_project_from_tile(self, project_dir):
        self.open_project_callback(project_dir)
