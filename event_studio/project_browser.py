from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
from typing import Callable
from .glass_surface import GlassSurface
from .theme import appearance_controller, BROWSER_STYLESHEET, StudioMenu as QMenu
from . import classic_theme
from .ui_icons import icon
from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QSize
from PySide6.QtGui import QPixmap, QIcon, QPainter, QColor, QPen
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QStylePainter,
    QVBoxLayout,
    QWidget,
)
from .project_utils import (
    create_project_dir,
    list_projects,
    rename_project,
    rename_project_folder,
    sanitize_project_name,
)


class ViewComboBox(QComboBox):
    """Keep a stable menu title while the popup contains view glyphs."""

    def paintEvent(self, event):
        painter = QStylePainter(self)
        try:
            option = QStyleOptionComboBox()
            self.initStyleOption(option)
            option.currentText = "View"
            # QComboBox exposes itemIcon(index), not currentIcon(). An error
            # in this native paint callback must never leave its painter active.
            option.currentIcon = (
                self.itemIcon(self.currentIndex())
                if appearance_controller().mode == "glass" else QIcon()
            )
            painter.drawComplexControl(QStyle.CC_ComboBox, option)
            painter.drawControl(QStyle.CE_ComboBoxLabel, option)
        finally:
            painter.end()


def view_icon(mode):
    """Small, consistent view glyphs that do not depend on installed fonts."""
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor("#e2dfe7"), 1.4))
    if mode == "cards":
        for x in (3, 12):
            for y in (3, 12):
                painter.drawRect(x, y, 5, 5)
    else:
        for y in (4, 10, 16):
            if mode == "rows":
                painter.drawRect(2, y - 2, 4, 4)
                painter.drawLine(9, y, 18, y)
            else:
                painter.drawLine(3, y, 18, y)
    painter.end()
    return QIcon(pixmap)


def saved_date(value):
    try:
        return datetime.fromisoformat(value).strftime("%d %b %Y  ·  %H:%M")
    except (ValueError, TypeError):
        return "Not saved yet"


class ProjectTile(QFrame):
    openRequested = Signal(str)
    deleteRequested = Signal(str)
    renameRequested = Signal(str)

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
        self.menu_btn = QPushButton("...")
        self.menu_btn.setObjectName("ProjectMenu")
        self.menu_btn.setFixedWidth(36)
        self.menu_btn.setAccessibleName(f"Actions for {name}")
        self.menu_btn.setToolTip("Project actions")
        self.menu_btn.clicked.connect(
            lambda: self._show_project_menu(self.menu_btn.mapToGlobal(self.menu_btn.rect().bottomLeft()))
        )
        if view == "cards":
            footer = QHBoxLayout()
            footer.addWidget(self.saved_label, 1)
            footer.addWidget(self.menu_btn)
            root.addLayout(footer)
        else:
            root.addWidget(self.saved_label)
            root.addWidget(self.menu_btn)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self._show_project_menu(self.mapToGlobal(pos))
        )
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(120)
        self.preview_timer.timeout.connect(self._advance_preview)
        self._set_initial_image()

        appearance_controller().changed.connect(self._apply_appearance)
        self._apply_appearance()

    def _apply_appearance(self, *_):
        glass = appearance_controller().mode == "glass"
        self.menu_btn.setText("" if glass else "...")
        self.menu_btn.setIcon(icon("dots-three") if glass else QIcon())

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

    def _show_project_menu(self, position):
        menu = QMenu(self)
        menu.addAction("Open project", self._emit_open)
        menu.addAction("Rename project", lambda: self.renameRequested.emit(self.project_dir))
        menu.addSeparator()
        menu.addAction("Delete project", lambda: self.deleteRequested.emit(self.project_dir))
        menu.exec(position)
        menu.deleteLater()

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
        autoload=True,
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
        self._transfer_task = None
        self._columns = 0
        self.setWindowTitle("Event-Based Studio — Projects")
        self.resize(1180, 760)
        self.setMinimumSize(760, 500)
        self._apply_appearance()
        central = GlassSurface()
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
        from .about import show_about
        about = QPushButton("About")
        about.clicked.connect(lambda: show_about(self))
        brand.addWidget(about)
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
        self.btn_import = QPushButton("Import project")
        self.btn_import.setToolTip("Import an Event-Based Studio project (.ebs)")
        self.btn_import.clicked.connect(self._import_project_bundle)
        nav.addWidget(self.btn_import)
        nav.addStretch()
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
        self.search_action = self.search.addAction(icon("magnifying-glass"), QLineEdit.LeadingPosition)
        toolbar.addWidget(self.search, 1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Recently saved", "recent")
        self.sort_combo.addItem("Name A–Z", "name")
        self.sort_combo.setAccessibleName("Sort projects")
        toolbar.addWidget(self.sort_combo)
        self.view_combo = ViewComboBox()
        for text, value in [
            ("Image + text", "rows"),
            ("Text only", "text"),
            ("Large tiles", "cards"),
        ]:
            self.view_combo.addItem(view_icon(value), "", value)
            index = self.view_combo.count() - 1
            self.view_combo.setItemData(index, text, Qt.ToolTipRole)
            self.view_combo.setItemData(index, text, Qt.AccessibleTextRole)
        self.view_combo.setIconSize(QSize(20, 20))
        self.view_combo.setFixedWidth(80)
        self.view_combo.setAccessibleName("Project view")
        self.view_combo.setCurrentIndex(
            max(0, self.view_combo.findData(self.settings.value("view", "rows")))
        )
        self.view_combo.setToolTip(self.view_combo.currentData(Qt.ToolTipRole))
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
        from .window_chrome import StudioHeader
        self.studio_header = StudioHeader(self, show_appearance=True)
        self.setMenuWidget(self.studio_header)
        appearance_controller().changed.connect(self._apply_appearance)
        self._apply_appearance()
        if autoload:
            self.refresh_projects()
        else:
            self._render_projects()

    def _apply_appearance(self, *_):
        glass = appearance_controller().mode == "glass"
        self.setStyleSheet(BROWSER_STYLESHEET if glass else classic_theme.BROWSER_STYLESHEET)
        if hasattr(self, "btn_new"):
            self.btn_new.setText("New project" if glass else "+  New project")
            self.search_action.setVisible(glass)
            self.view_combo.setFixedWidth(104 if glass else 80)
            for index in range(self.view_combo.count()):
                mode = self.view_combo.itemData(index)
                glyph = {"cards": "squares-four", "rows": "rows", "text": "list"}[mode]
                self.view_combo.setItemIcon(index, icon(glyph) if glass else view_icon(mode))
            self.btn_new.update()
        self.update()

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

    def _import_project_bundle(self):
        if self._transfer_task is not None:
            return
        from .project_transfer import IMPORT_FILTER, import_project
        from .workers import Task
        path, _ = QFileDialog.getOpenFileName(self, "Import project", str(Path.home()), IMPORT_FILTER)
        if not path:
            return
        progress = QProgressDialog("Checking and importing project…", "Cancel", 0, 100, self)
        progress.setWindowTitle("Import project")
        progress.setAutoClose(False)
        progress.setMinimumDuration(200)
        task = Task(lambda: import_project(path, self.projects_root,
            cancel=task.isInterruptionRequested, progress=task.progress.emit), self)
        self._transfer_task = task
        self.centralWidget().setEnabled(False)
        progress.canceled.connect(task.requestInterruption)
        task.progress.connect(lambda value, text: (progress.setValue(min(99, value)), progress.setLabelText(text)))
        def imported(directory):
            self.refresh_projects()
            self.statusBar().showMessage(f"Project imported: {directory.name}. Open it to continue.", 15000)
        def complete():
            self.centralWidget().setEnabled(True)
            progress.close()
            progress.deleteLater()
            self._transfer_task = None
            task.deleteLater()
        task.succeeded.connect(imported)
        task.failed.connect(lambda error: QMessageBox.critical(self, "Project import failed", error))
        task.cancelled.connect(self.statusBar().showMessage)
        task.finished.connect(complete)
        task.start()

    def closeEvent(self, event):
        if self._transfer_task is not None:
            self.statusBar().showMessage("Wait for project import to finish, or cancel it before closing.")
            event.ignore()
            return
        super().closeEvent(event)

    def refresh_projects(self):
        self.projects = list_projects(self.projects_root)
        self._render_projects()

    def _view_changed(self):
        self.view_combo.setToolTip(self.view_combo.currentData(Qt.ToolTipRole))
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
        rows = (len(projects) + self._columns - 1) // self._columns
        height = {"cards": 263, "rows": 92, "text": 72}[self.view_combo.currentData()]
        self.grid_host.setMinimumHeight(
            rows * height + max(0, rows - 1) * self.grid.spacing() if rows else 200
        )
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
            tile.deleteRequested.connect(self._delete_project)
            tile.renameRequested.connect(self._rename_project)
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

    def _delete_project(self, project_dir):
        target = Path(project_dir)
        try:
            root = self.projects_root.resolve(strict=True)
            resolved = target.resolve(strict=True)
            if (resolved.parent != root or target.is_symlink()
                    or target.is_junction() or not resolved.is_dir()):
                raise ValueError("The project must be a folder directly inside the projects directory.")
            answer = QMessageBox.question(
                self, "Delete project",
                f'Permanently delete "{target.name}"?\n\n'
                f"This deletes the project folder and all files inside it:\n{resolved}\n\n"
                "Source recordings outside this folder are kept. This cannot be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            # Recheck the target after the confirmation dialog before deleting.
            if target.resolve(strict=True) != resolved or target.is_symlink() or target.is_junction():
                raise ValueError("The project folder changed. Please try again.")
            shutil.rmtree(resolved)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not delete project", str(exc))
        self.refresh_projects()

    def _rename_project(self, project_dir):
        project = next((p for p in self.projects if p["project_dir"] == project_dir), None)
        if project is None:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename project", "Project name:", text=project["project_name"]
        )
        if not accepted or not name.strip():
            return
        try:
            old = Path(project_dir).resolve()
            editors = [window for window in QApplication.topLevelWidgets()
                       if getattr(window, "current_project_dir", None) is not None
                       and Path(window.current_project_dir).resolve() == old]
            if any(getattr(window, "_task", None) is not None for window in editors):
                raise ValueError("Wait for the project's current operation to finish before renaming.")
            renamed = rename_project_folder(self.projects_root, old, name.strip())
            for window in editors:
                window.current_project_dir = renamed
                from .recovery import recovery_revision
                window._recovery_revision = recovery_revision(renamed)
                window.project_name = renamed.name
                window.current_session_path = str(renamed / "session.json")
                if window.loaded_csv_path:
                    source = Path(window.loaded_csv_path)
                    if source.is_relative_to(old):
                        window.loaded_csv_path = str(renamed / source.relative_to(old))
                window._update_window_title()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Could not rename project", str(exc))
        self.refresh_projects()
