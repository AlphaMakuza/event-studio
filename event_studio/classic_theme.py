"""Appearance preserved before the glass refresh for live comparison."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from pathlib import Path


def configure_application(app):
    from .control_style import StudioStyle
    from PySide6.QtCore import Qt
    app.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    if not isinstance(app.style(), StudioStyle):
        app.setStyle(StudioStyle())
    if not QFontDatabase.families():
        # Qt's offscreen platform on Windows may not discover system fonts.
        font = Path("C:/Windows/Fonts/segoeui.ttf")
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in ((QPalette.Window, "#292733"), (QPalette.WindowText, "#e2dfe7"),
                        (QPalette.Base, "#1e1d27"), (QPalette.AlternateBase, "#302d3a"),
                        (QPalette.Text, "#e2dfe7"), (QPalette.Button, "#35313f"),
                        (QPalette.ButtonText, "#e2dfe7"), (QPalette.Highlight, "#55454c"),
                        (QPalette.HighlightedText, "#f0e2d6"), (QPalette.ToolTipBase, "#35313f"),
                        (QPalette.ToolTipText, "#e2dfe7")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#8c8595"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#8c8595"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QMainWindow { background: #292733; }
        QMainWindow#StudioWindow { background: transparent; }
        QWidget#StudioSurface { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
            stop:0 rgba(53,49,63,245), stop:0.55 rgba(41,39,51,245), stop:1 rgba(32,35,46,245)); }
        QGroupBox { background: rgba(163,135,194,12); border: 1px solid #48424f; border-radius: 2px;
                    margin-top: 10px; padding: 8px; padding-top: 14px; }
        QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; }
        QPushButton { padding: 5px 8px; background: #39333f; color: #e2dfe7;
                      border: 1px solid #574d60; border-radius: 2px; }
        QPushButton:hover { background: #48404f; border-color: #b59b8b; }
        QPushButton:pressed, QPushButton:checked { background: #55454c; border-color: #c4a18c; }
        QPushButton:disabled { background: #2d2935; color: #8c8595; border-color: #403947; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 4px;
            background: #24212d; border: 1px solid #504658; border-radius: 2px; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #c4a18c; }
        QMenu { background: #2c2835; color: #e2dfe7; border: 1px solid #574d60; padding: 4px; }
        QMenu::item { padding: 6px 24px 6px 12px; }
        QMenu::item:selected { background: #55454c; color: #f0e2d6; }
        QMenu::item:disabled { color: #8c8595; }
        QMenu::separator { height: 1px; background: #48424f; margin: 4px 8px; }
        QToolTip { color: #e2dfe7; background: #35313f; border: 1px solid #8b7b97; padding: 4px; }
        QStatusBar { background: #24222e; color: #b5acbf; }
        QSplitter::handle { background: #48424f; }
        QScrollArea { border: none; }
        QScrollBar:vertical { background: transparent; width: 12px; margin: 3px 2px; border: none; }
        QScrollBar::handle:vertical { background: rgba(180,163,193,110); min-height: 40px; border: none; border-radius: 4px; }
        QScrollBar::handle:vertical:hover { background: rgba(208,189,220,185); }
        QScrollBar::handle:vertical:pressed { background: #c4a18c; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px 3px; border: none; }
        QScrollBar::handle:horizontal { background: rgba(180,163,193,110); min-width: 40px; border: none; border-radius: 4px; }
        QScrollBar::handle:horizontal:hover { background: rgba(208,189,220,185); }
        QScrollBar::handle:horizontal:pressed { background: #c4a18c; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
        QAbstractScrollArea::corner { background: transparent; border: none; }
    """)


BROWSER_STYLESHEET = '\n            QMainWindow { background: transparent; color: #e2dfe7; }\n            QWidget#Browser { background: qlineargradient(x1:0,y1:0,x2:1,y2:1,\n                stop:0 rgba(53,49,63,245), stop:0.55 rgba(41,39,51,245), stop:1 rgba(32,35,46,245)); color: #e2dfe7; }\n            QFrame#Sidebar { background: rgba(22,18,32,155); border-right: 1px solid rgba(198,174,222,30); }\n            QLabel { background: transparent; color: #e2dfe7; }\n            QLabel#Brand { font-size: 21px; font-weight: 600; }\n            QLabel#Eyebrow { color: #c4a18c; font-size: 10px; }\n            QLabel#Heading { font-size: 24px; font-weight: 600; }\n            QLabel#Muted { color: #b5acbf; font-size: 11px; }\n            QLabel#ProjectTitle { font-size: 14px; font-weight: 600; }\n            QLabel#ProjectPreview { background: rgba(16,13,23,165); color: #9a88ad; font-size: 10px; border-radius: 2px; }\n            QPushButton { background: rgba(163,135,194,22); color: #ded5e5; border: 1px solid rgba(198,174,222,45);\n                          border-radius: 2px; padding: 8px 12px; text-align: left; }\n            QPushButton:hover { background: rgba(182,148,214,45); border-color: #94839e; }\n            QPushButton#Primary { background: #c4a18c; border-color: #c4a18c; color: #2b1e2a; font-weight: 600; }\n            QPushButton#Primary:hover { background: #d0b3a0; }\n            QPushButton#Selected { background: rgba(196,161,140,18); border-color: rgba(196,161,140,80); color: #d0b3a0; }\n            QLineEdit, QComboBox { background: rgba(17,13,25,100); color: #e2dfe7; border: 1px solid rgba(198,174,222,45);\n                                 border-radius: 2px; padding: 7px 9px; }\n            QLineEdit:focus, QComboBox:focus { border-color: #c4a18c; }\n            QComboBox QAbstractItemView { background: #352b42; color: #e2dfe7; selection-background-color: #604963; }\n            QScrollArea, QWidget#ProjectHost { background: transparent; border: none; }\n            QFrame#ProjectTile { background: rgba(163,135,194,17); border: 1px solid rgba(198,174,222,35); border-radius: 2px; }\n            QFrame#ProjectTile:hover { background: rgba(182,148,214,32); border-color: rgba(196,161,140,100); }\n            QFrame#ProjectTile:focus { border-color: #d0b3a0; }\n        '


HEADER_STYLESHEET = '\n            QFrame#StudioHeader { background: rgba(48,43,59,245); border-bottom: 1px solid #574d60; }\n            QLabel { color: #dcd5e3; background: transparent; font-size: 11px; }\n            QToolButton { background: transparent; border: none; border-radius: 0;\n                          color: #e2dfe7; width: 44px; height: 34px; }\n            QToolButton:hover { background: #4b3e50; }\n            QToolButton#WindowClose:hover { background: #b44250; }\n            QMenuBar { background: rgba(39,35,47,245); color: #dcd5e3; padding: 2px 8px; }\n            QMenuBar::item:selected { background: #55454c; }\n        '
