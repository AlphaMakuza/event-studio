"""Publisher, version, and bundled legal documents."""
from pathlib import Path
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout

from .version import __version__


def show_about(parent):
    dialog = QDialog(parent)
    dialog.setWindowTitle("About Event-Based Studio")
    dialog.setMinimumWidth(480)
    layout = QVBoxLayout(dialog)
    text = QLabel(f"Event-Based Studio {__version__}\nCopyright © 2026 Alpha Makuza\nProprietary application; separately licensed third-party components.\n\nUses Qt/PySide6 under the LGPLv3. You may replace LGPL libraries\nand exercise the modification/debugging rights in their licenses.")
    text.setWordWrap(True)
    layout.addWidget(text)
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    documents = [("Application license", root / "LICENSE.txt"),
                 ("Third-party notices", root / "THIRD-PARTY.md" if getattr(sys, "frozen", False) else root / "docs" / "THIRD-PARTY.md"),
                 ("Privacy", root / "PRIVACY.md" if getattr(sys, "frozen", False) else root / "docs" / "PRIVACY.md"),
                 ("Support", root / "SUPPORT.md" if getattr(sys, "frozen", False) else root / "docs" / "SUPPORT.md")]
    for label, path in documents:
        button = QPushButton(label)
        button.clicked.connect(lambda _=False, p=path: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
        layout.addWidget(button)
    close = QDialogButtonBox(QDialogButtonBox.Close)
    close.rejected.connect(dialog.reject)
    layout.addWidget(close)
    dialog.exec()
