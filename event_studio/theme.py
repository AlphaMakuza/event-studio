"""Use Qt's native widgets with a consistent, readable studio palette."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from pathlib import Path


def configure_application(app):
    app.setStyle("Fusion")
    if not QFontDatabase.families():
        # Qt's offscreen platform on Windows may not discover system fonts.
        font = Path("C:/Windows/Fonts/segoeui.ttf")
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont("Segoe UI", 10))
    palette = QPalette()
    for role, color in ((QPalette.Window, "#191d25"), (QPalette.WindowText, "#e5eaf3"),
                        (QPalette.Base, "#10141c"), (QPalette.AlternateBase, "#222937"),
                        (QPalette.Text, "#e5eaf3"), (QPalette.Button, "#293142"),
                        (QPalette.ButtonText, "#e5eaf3"), (QPalette.Highlight, "#5276ce"),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, "#293142"),
                        (QPalette.ToolTipText, "#ffffff")):
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#7e8798"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#7e8798"))
    app.setPalette(palette)
    app.setStyleSheet("""
        QGroupBox { border: 1px solid #394255; border-radius: 6px;
                    margin-top: 10px; padding: 8px; padding-top: 14px; }
        QGroupBox::title { subcontrol-origin: margin; left: 9px; padding: 0 4px; }
        QPushButton { padding: 5px 8px; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { padding: 4px; }
        QScrollArea { border: none; }
    """)
