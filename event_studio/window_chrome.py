"""Compact studio window header with native move and resize gestures."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QPen, QColor
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QStyle, QToolButton, QVBoxLayout, QMainWindow, QWidget, QProgressDialog

from .boot import logo_pixmap
from .theme import appearance_controller, HEADER_STYLESHEET
from . import classic_theme
from .ui_icons import icon


class StudioHeader(QFrame):
    def __init__(self, window, menu=None, *, show_appearance=False):
        super().__init__(window)
        self.studio = window
        self.setObjectName("StudioHeader")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(12, 0, 0, 0)
        title_row.setSpacing(10)
        logo = QLabel()
        pixmap = logo_pixmap()
        logo.setPixmap(pixmap.scaled(28, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setAttribute(Qt.WA_TransparentForMouseEvents)
        window.setWindowIcon(QIcon(pixmap))
        title_row.addWidget(logo)
        self.title = QLabel(window.windowTitle())
        self.title.setAttribute(Qt.WA_TransparentForMouseEvents)
        title_row.addWidget(self.title, 1)
        window.windowTitleChanged.connect(self.title.setText)
        self.appearance = QComboBox()
        self.appearance.setAccessibleName("Interface appearance")
        self.appearance.setToolTip("Compare the glass redesign with the original interface")
        self.appearance.addItem("Glass", "glass")
        self.appearance.addItem("Original", "classic")
        self.appearance.setCurrentIndex(self.appearance.findData(appearance_controller().mode))
        self.appearance.currentIndexChanged.connect(self._appearance_selected)
        title_row.addWidget(self.appearance)
        self.appearance.setVisible(show_appearance)
        self.minimize = self._button("Minimize", QStyle.SP_TitleBarMinButton, window.showMinimized)
        self.maximize = self._button("Maximize", QStyle.SP_TitleBarMaxButton, self.toggle_maximized)
        self.close_button = self._button("Close", QStyle.SP_TitleBarCloseButton, window.close)
        self.close_button.setObjectName("WindowClose")
        for button in (self.minimize, self.maximize, self.close_button):
            title_row.addWidget(button)
        layout.addLayout(title_row)
        if menu is not None:
            layout.addWidget(menu)
        window.setWindowFlag(Qt.FramelessWindowHint)
        window.setObjectName("StudioWindow")
        window.setAttribute(Qt.WA_TranslucentBackground, isinstance(window, QMainWindow))
        # Per-pixel alpha lets the video stay opaque while the shell is translucent.
        window.setWindowOpacity(1.0)
        window.installEventFilter(self)
        appearance_controller().watch_window(window)
        appearance_controller().changed.connect(self._apply_appearance)
        self._apply_appearance()

    def _appearance_selected(self):
        appearance_controller().set_mode(self.appearance.currentData())

    def _apply_appearance(self, *_):
        mode = appearance_controller().mode
        self.setStyleSheet(HEADER_STYLESHEET if mode == "glass" else classic_theme.HEADER_STYLESHEET)
        self.appearance.blockSignals(True)
        self.appearance.setCurrentIndex(self.appearance.findData(mode))
        self.appearance.blockSignals(False)
        maximized = self.studio.isMaximized()
        self.minimize.setIcon(self._control_icon(QStyle.SP_TitleBarMinButton))
        self.maximize.setIcon(self._control_icon(QStyle.SP_TitleBarNormalButton if maximized else QStyle.SP_TitleBarMaxButton))
        self.close_button.setIcon(self._control_icon(QStyle.SP_TitleBarCloseButton))
        self._apply_backdrop()

    def _apply_backdrop(self):
        from .native_backdrop import apply_backdrop
        active = apply_backdrop(self.studio, appearance_controller().mode == "glass")
        self.studio.setProperty("nativeGlassBackdrop", active and appearance_controller().mode == "glass")
        if isinstance(self.studio, QMainWindow) and self.studio.centralWidget() is not None:
            self.studio.centralWidget().update()

    def _button(self, text, icon, callback):
        button = QToolButton(self)
        button.setIcon(self._control_icon(icon))
        button.setToolTip(text)
        button.setAccessibleName(text)
        button.clicked.connect(callback)
        return button

    def _control_icon(self, kind):
        if appearance_controller().mode == "glass":
            name = {QStyle.SP_TitleBarCloseButton: "x", QStyle.SP_TitleBarMinButton: "minus",
                    QStyle.SP_TitleBarNormalButton: "copy", QStyle.SP_TitleBarMaxButton: "square"}[kind]
            return icon(name)
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(QColor("#e2dfe7"), 1.2))
        if kind == QStyle.SP_TitleBarCloseButton:
            painter.drawLine(4, 4, 12, 12)
            painter.drawLine(12, 4, 4, 12)
        elif kind == QStyle.SP_TitleBarMinButton:
            painter.drawLine(3, 10, 12, 10)
        elif kind == QStyle.SP_TitleBarNormalButton:
            painter.drawRect(5, 3, 7, 7)
            painter.fillRect(3, 6, 7, 7, QColor("#302b3b"))
            painter.drawRect(3, 6, 7, 7)
        else:
            painter.drawRect(4, 4, 8, 8)
        painter.end()
        return QIcon(pixmap)

    def toggle_maximized(self):
        if self.studio.isMaximized():
            self.studio.showNormal()
        else:
            self.studio.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.studio.windowHandle():
            self.studio.windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.toggle_maximized()
            event.accept()

    def eventFilter(self, watched, event):
        if not hasattr(self, "studio"):
            return False
        if watched is self.studio and event.type() == QEvent.Show:
            self._apply_backdrop()
        if watched is self.studio and event.type() == QEvent.Resize and getattr(self, '_overlay_header', False):
            self.setGeometry(0, 0, QWidget.width(self.studio), self.sizeHint().height())
        if watched is self.studio and event.type() == QEvent.WindowStateChange:
            maximized = self.studio.isMaximized()
            self.maximize.setIcon(self._control_icon(
                QStyle.SP_TitleBarNormalButton if maximized else QStyle.SP_TitleBarMaxButton
            ))
            self.maximize.setToolTip("Restore" if maximized else "Maximize")
            self.maximize.setAccessibleName("Restore" if maximized else "Maximize")
        if (event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                and hasattr(watched, "window") and watched.window() is self.studio
                and not self.studio.isMaximized()):
            point = self.studio.mapFromGlobal(event.globalPosition().toPoint())
            edges = Qt.Edges()
            if point.x() < 6:
                edges |= Qt.LeftEdge
            elif point.x() >= QWidget.width(self.studio) - 6:
                edges |= Qt.RightEdge
            if point.y() < 6:
                edges |= Qt.TopEdge
            elif point.y() >= QWidget.height(self.studio) - 6:
                edges |= Qt.BottomEdge
            if edges and self.studio.windowHandle():
                return self.studio.windowHandle().startSystemResize(edges)
        return super().eventFilter(watched, event)


def install_window_header(window):
    """Use the same header for secondary windows and Qt dialogs."""
    if (not window.isWindow() or not window.windowTitle()
            or (window.layout() is None and not isinstance(window, QProgressDialog))
            or window.windowType() in (Qt.Popup, Qt.ToolTip, Qt.SplashScreen)
            or getattr(window, 'studio_header', None) is not None
            or window.property('studioHeaderInstalling')
            or window.findChild(StudioHeader, options=Qt.FindDirectChildrenOnly) is not None):
        return
    window.setProperty('studioHeaderInstalling', True)
    was_visible = window.isVisible()
    header = StudioHeader(window)
    window.studio_header = header
    if isinstance(window, QMainWindow):
        window.setMenuWidget(header)
    else:
        header._overlay_header = True
        height = header.sizeHint().height()
        if window.layout() is not None:
            margins = window.layout().contentsMargins()
            window.layout().setContentsMargins(margins.left(), margins.top() + height,
                                              margins.right(), margins.bottom())
        elif isinstance(window, QProgressDialog):
            # QProgressDialog places its children directly rather than using a layout.
            label = window.findChild(QLabel, options=Qt.FindDirectChildrenOnly)
            if label is not None:
                label.setContentsMargins(0, height, 0, 0)
                label.setMinimumHeight(label.sizeHint().height())
            window.setMinimumHeight(window.minimumHeight() + height)
        header.setGeometry(0, 0, QWidget.width(window), height)
        header.raise_()
    header.show()
    window.setProperty('studioHeaderInstalling', False)
    if was_visible:
        window.show()
