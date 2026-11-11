"""Capture the browser and editor without boot audio or changing project data.

python -m scripts.preview_appearance --label before
"""
import argparse
import os
from pathlib import Path
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QEvent
from PySide6.QtGui import QImage, QPainter, QColor, QFont
from PySide6.QtWidgets import QApplication
from event_studio.theme import configure_application, appearance_controller
from event_studio.project_browser import ProjectBrowser
from event_studio.app import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="glass")
    parser.add_argument("--appearance", choices=("glass", "classic"), default="glass")
    parser.add_argument("--native", action="store_true", help="Capture using the Windows Qt platform")
    args = parser.parse_args()
    output = Path("artifacts/appearance-comparison")
    output.mkdir(parents=True, exist_ok=True)
    if args.native:
        os.environ["QT_QPA_PLATFORM"] = "windows"
    app = QApplication([])
    configure_application(app)
    appearance_controller().set_mode(args.appearance, persist=False)
    with tempfile.TemporaryDirectory() as directory:
        settings = QSettings(str(Path(directory) / "preview.ini"), QSettings.IniFormat)
        browser = ProjectBrowser(Path("projects"), lambda _: None, settings=settings)
        editor = MainWindow()
        for name, window in (("browser", browser), ("editor", editor)):
            window.resize(1400, 900) if name == "editor" else window.resize(1180, 760)
            window.show()
            for _ in range(5):
                app.processEvents()
            window.grab().save(str(output / f"{args.label}-{name}.png"))
            if args.native:
                print(f"{name}: native acrylic request accepted = {window.property('nativeGlassBackdrop')}")
            window.close()
            window.deleteLater()
            app.sendPostedEvents(None, QEvent.DeferredDelete)
    if args.label == "glass":
        for name in ("browser", "editor"):
            before = QImage(str(output / f"before-{name}.png"))
            after = QImage(str(output / f"glass-{name}.png"))
            if before.isNull() or after.isNull():
                continue
            sheet = QImage(before.width() + after.width() + 24, max(before.height(), after.height()) + 52, QImage.Format_RGB32)
            sheet.fill(QColor("#0c1722"))
            painter = QPainter(sheet)
            painter.setFont(QFont("Segoe UI", 12))
            painter.setPen(QColor("#dceaf3"))
            painter.drawText(16, 33, "BEFORE  /  ORIGINAL")
            painter.drawText(before.width() + 40, 33, "AFTER  /  GLASS + PHOSPHOR ICONS")
            painter.drawImage(0, 52, before)
            painter.drawImage(before.width() + 24, 52, after)
            painter.end()
            sheet.save(str(output / f"comparison-{name}.png"))
    print(f"Screenshots saved to {output.resolve()}")


if __name__ == "__main__":
    main()
