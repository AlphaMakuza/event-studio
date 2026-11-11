"""Live-switchable studio appearance."""
from PySide6.QtCore import QObject, QEvent, QSettings, QSize, Signal
from PySide6.QtGui import QColor, QPalette, QAction
from PySide6.QtWidgets import QApplication, QPushButton, QMenu, QWidget
from . import classic_theme
from .ui_icons import icon, control_icon


GLASS_STYLESHEET = """
    QMainWindow, QDialog { background: #15212e; color: #e4eef5; }
    QMainWindow#StudioWindow { background: transparent; }
    QWidget#StudioSurface, QWidget#Browser { background: transparent; }
    QLabel { background: transparent; }
    QGroupBox { background: qlineargradient(x1:0,y1:0,x2:0.8,y2:1,
        stop:0 rgba(221,243,255,17), stop:0.5 rgba(198,226,245,6), stop:1 rgba(10,20,31,34));
        border: 1px solid rgba(197,226,245,35); border-top-color: rgba(222,245,255,70);
        border-radius: 2px; margin-top: 12px; padding: 9px; padding-top: 16px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #c6dce9; }
    QPushButton, QToolButton { color: #deebf5;
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
            stop:0 rgba(224,245,255,28), stop:0.48 rgba(180,215,240,12), stop:1 rgba(155,200,226,8));
        border: 1px solid rgba(204,234,249,47); border-top-color: rgba(235,250,255,91);
        border-bottom-color: rgba(147,188,211,25); border-radius: 2px; padding: 6px 9px; }
    QPushButton:hover, QToolButton:hover { background: rgba(151,218,239,35); border-color: rgba(169,233,249,115); }
    QPushButton:pressed, QPushButton:checked, QToolButton:pressed { background: rgba(86,185,212,40); border-color: #79d7e8; }
    QPushButton:focus, QToolButton:focus { border-color: #91e2f0; }
    QPushButton:disabled, QToolButton:disabled { color: #687b8d; background: rgba(150,190,210,5); border-color: rgba(180,210,230,15); }
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: rgba(6,17,29,135); color: #e4eef5;
        border: 1px solid rgba(192,224,245,37); border-bottom-color: rgba(218,241,255,65);
        border-radius: 2px; padding: 5px 8px; selection-background-color: #305c71; }
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #79d7e8; }
    QComboBox QAbstractItemView { background: #1c3041; color: #e4eef5; selection-background-color: #30576b; }
    QMenu { background: #1c2c3b; color: #e4eef5; border: 1px solid #4c6577; padding: 5px; }
    QMenu::item { padding: 7px 25px 7px 10px; }
    QMenu::item:selected { background: #30546a; }
    QMenu::item:disabled { color: #687b8d; }
    QMenu::separator { height: 1px; background: #3b5060; margin: 5px 8px; }
    QToolTip { background: #203648; color: #e4eef5; border: 1px solid #5e7d90; padding: 6px; }
    QStatusBar { background: rgba(8,20,32,100); color: #a6bdcc; border-top: 1px solid rgba(210,235,250,23); }
    QScrollArea { background: transparent; border: none; }
    QSplitter::handle { background: rgba(195,230,250,24); }
    QScrollBar:vertical { background: transparent; width: 12px; margin: 3px 2px; border: none; }
    QScrollBar::handle:vertical { background: rgba(151,195,213,110); min-height: 40px; border: none; border-radius: 4px; }
    QScrollBar::handle:vertical:hover { background: rgba(170,223,238,185); }
    QScrollBar::handle:vertical:pressed { background: #91d9e5; }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px 3px; border: none; }
    QScrollBar::handle:horizontal { background: rgba(151,195,213,110); min-width: 40px; border: none; border-radius: 4px; }
    QScrollBar::handle:horizontal:hover { background: rgba(170,223,238,185); }
    QScrollBar::handle:horizontal:pressed { background: #91d9e5; }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
    QAbstractScrollArea::corner { background: transparent; border: none; }
    QTableWidget, QListWidget, QTreeWidget { background: #142332; alternate-background-color: #1c3040;
        color: #deebf5; border: 1px solid #344c5d; selection-background-color: #30546a; }
    QHeaderView::section { background: #223849; color: #c7deeb; border: none;
        border-right: 1px solid #385264; border-bottom: 1px solid #4a6576; padding: 5px; }
    QTabWidget::pane { border: 1px solid #3a5264; }
    QTabBar::tab { background: #1a2b3a; color: #a6bdcc; padding: 8px 13px; border: 1px solid #304758; }
    QTabBar::tab:selected { background: #294658; color: #e4f6ff; border-bottom: 2px solid #82d9e9; }
    QSlider::groove:horizontal { height: 4px; background: #0c1c2a; }
    QSlider::sub-page:horizontal { background: #5eb4c7; }
    QSlider::handle:horizontal { background: #d3f1fa; width: 9px; margin: -5px 0; border: 1px solid #7fcfdf; border-radius: 1px; }
"""

BROWSER_STYLESHEET = """
    QLabel { color: #e4eef5; background: transparent; }
    QLabel#Brand { font-size: 21px; font-weight: 600; }
    QLabel#Eyebrow { color: #89cedd; font-size: 10px; letter-spacing: 2px; }
    QLabel#Heading { font-size: 26px; font-weight: 600; }
    QLabel#Muted { color: #9eb5c6; font-size: 11px; }
    QLabel#ProjectTitle { font-size: 14px; font-weight: 600; }
    QLabel#ProjectPreview { background: rgba(3,14,25,150); color: #84a4b8; font-size: 10px;
        border: 1px solid rgba(173,216,239,24); border-radius: 1px; }
    QFrame#Sidebar { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 rgba(7,19,30,150), stop:1 rgba(14,31,45,95)); border-right: 1px solid rgba(200,235,255,33);
        border-top: 1px solid rgba(215,242,255,30); }
    QPushButton { padding: 9px 12px; text-align: left; }
    QPushButton#Primary { color: #112a35; font-weight: 600;
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1,stop:0 #c0eef5,stop:0.48 #91d9e5,stop:1 #73bece);
        border-color: #8ed8e7; border-top-color: #e2fcff; }
    QPushButton#Primary:hover { background: #bbf1fa; border-color: #e2fcff; }
    QPushButton#Selected { background: rgba(124,211,231,20); border-color: rgba(151,223,239,65);
        border-left: 2px solid #94e3ee; color: #b7eff7; }
    QPushButton#ProjectMenu { padding: 5px; background: transparent; border-color: transparent; }
    QPushButton#ProjectMenu:hover { background: rgba(194,234,255,24); border-color: rgba(204,234,249,47); }
    QLineEdit, QComboBox { padding: 8px 10px; }
    QScrollArea, QWidget#ProjectHost { background: transparent; border: none; }
    QFrame#ProjectTile { background: qlineargradient(x1:0,y1:0,x2:0.35,y2:1,
        stop:0 rgba(227,246,255,23), stop:0.18 rgba(204,235,251,12), stop:1 rgba(141,185,214,6));
        border: 1px solid rgba(204,234,249,40); border-top-color: rgba(230,249,255,88);
        border-left-color: rgba(220,243,255,58); border-bottom-color: rgba(156,196,220,22); border-radius: 2px; }
    QFrame#ProjectTile:hover { background: qlineargradient(x1:0,y1:0,x2:0.5,y2:1,
        stop:0 rgba(184,239,255,36), stop:1 rgba(119,194,221,14)); border-color: rgba(150,224,244,125); }
    QFrame#ProjectTile:focus { border: 1px solid #a2e6f3; }
"""

HEADER_STYLESHEET = """
    QFrame#StudioHeader { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 rgba(165,207,227,32), stop:1 rgba(18,35,50,230));
        border-top: 1px solid rgba(228,247,255,90); border-bottom: 1px solid rgba(198,232,250,42); }
    QLabel { color: #bdcedb; background: transparent; font-size: 11px; }
    QToolButton { background: transparent; border: none; border-radius: 0; color: #e4eef5; width: 44px; height: 34px; padding: 0; }
    QToolButton:hover { background: rgba(187,234,255,25); }
    QToolButton#WindowClose:hover { background: #b44250; }
    QComboBox { background: rgba(8,24,37,100); color: #cce8f4; border: 1px solid rgba(202,237,255,50);
        border-radius: 2px; padding: 3px 8px; font-size: 11px; min-width: 110px; }
    QComboBox QAbstractItemView { background: #203748; color: #e4eef5; selection-background-color: #365e72; }
    QMenuBar { background: rgba(8,22,35,100); color: #d5e6f1; padding: 3px 8px; }
    QMenuBar::item:selected { background: rgba(152,217,241,35); }
"""


class AppearanceController(QObject):
    changed = Signal(str)

    def __init__(self, app):
        super().__init__(app)
        self.settings = QSettings("EventBasedStudio", "Appearance")
        saved = self.settings.value("mode", "glass")
        self.mode = saved if saved in ("glass", "classic") else "glass"

    def watch_window(self, window):
        # A QApplication-wide Python filter can encounter stale wrappers for
        # unrelated widgets during GC in PySide6. Observe only the live window.
        window.installEventFilter(self)

    def decorate_window(self, window):
        for button in window.findChildren(QPushButton):
            self.decorate(button)
        for action in window.findChildren(QAction):
            self.decorate(action)
        for menu in window.findChildren(QMenu):
            if not getattr(menu, "_studio_menu_observed", False):
                menu._studio_menu_observed = True
                menu.aboutToShow.connect(self.decorate_menu)

    def decorate_menu(self):
        menu = self.sender()
        if isinstance(menu, QMenu):
            for action in menu.actions():
                self.decorate(action)

    def set_mode(self, mode, *, persist=True):
        if mode not in ("glass", "classic"):
            raise ValueError(f"Unknown appearance: {mode}")
        self.mode = mode
        if persist:
            self.settings.setValue("mode", mode)
        self.apply()
        self.changed.emit(mode)

    def apply(self):
        app = QApplication.instance()
        classic_theme.configure_application(app)
        if self.mode == "glass":
            palette = app.palette()
            for role, color in ((QPalette.Window, "#15212e"), (QPalette.Base, "#142332"),
                                (QPalette.Button, "#263e50"), (QPalette.Text, "#e4eef5"),
                                (QPalette.WindowText, "#e4eef5"), (QPalette.ButtonText, "#e4eef5"),
                                (QPalette.Highlight, "#305c71"), (QPalette.HighlightedText, "#ecfaff")):
                palette.setColor(role, QColor(color))
            palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#687b8d"))
            palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#687b8d"))
            app.setPalette(palette)
            app.setStyleSheet(GLASS_STYLESHEET)
        for widget in app.allWidgets():
            if isinstance(widget, QPushButton):
                self.decorate(widget)
            for action in widget.findChildren(QAction):
                self.decorate(action)
            widget.update()

    def decorate(self, target):
        name = control_icon(target.text())
        if not name:
            return
        if not hasattr(target, "_original_studio_icon"):
            target._original_studio_icon = target.icon()
            if isinstance(target, QPushButton):
                target._original_studio_icon_size = target.iconSize()
        key = (self.mode, name, target.objectName())
        if getattr(target, "_studio_icon_key", None) == key:
            return
        target._studio_icon_key = key
        if self.mode == "classic":
            target.setIcon(target._original_studio_icon)
            if isinstance(target, QPushButton):
                target.setIconSize(target._original_studio_icon_size)
        else:
            color = "#153541" if target.objectName() == "Primary" else "#dceaf3"
            target.setIcon(icon(name, color))
            if isinstance(target, QPushButton):
                target.setIconSize(QSize(18, 18))

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Show and isinstance(watched, QWidget):
            self.decorate_window(watched)
        return False


def appearance_controller():
    app = QApplication.instance()
    if not hasattr(app, "studio_appearance"):
        app.studio_appearance = AppearanceController(app)
    return app.studio_appearance


def configure_application(app):
    appearance_controller().apply()


class StudioMenu(QMenu):
    """Decorate transient context menus without an application event filter."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._studio_menu_observed = True
        self.aboutToShow.connect(appearance_controller().decorate_menu)
