"""Small project-transfer dialogs shared by the browser and editor."""
from pathlib import Path
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QLabel, QVBoxLayout
from .project_transfer import EXTENSION


def choose_bundle_export(parent, name, source_path):
    dialog = QDialog(parent)
    dialog.setWindowTitle("Export project")
    dialog.setMinimumWidth(440)
    layout = QVBoxLayout(dialog)
    summary = QLabel("Pack the current session, ROIs, annotations, analysis settings, and available previews into one file.")
    summary.setWordWrap(True)
    layout.addWidget(summary)
    include = QCheckBox("Include recording for use on another computer")
    include.setChecked(True)
    include.setToolTip("Includes the loaded CSV and its metadata sidecar. Original DAT/H5 files are not included.")
    layout.addWidget(include)
    try:
        size = Path(source_path).stat().st_size / (1024 * 1024)
        description = f"Recording: {Path(source_path).name} ({size:,.1f} MiB before compression)."
    except OSError:
        description = "Locate the source recording before exporting."
    details = QLabel(description + "\nWithout the recording, the recipient must locate an identical CSV; its checksum will be checked.")
    details.setWordWrap(True)
    layout.addWidget(details)
    buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
    buttons.button(QDialogButtonBox.Save).setText("Choose destination…")
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.Accepted:
        dialog.deleteLater()
        return None
    include_recording = include.isChecked()
    dialog.deleteLater()
    path, _ = QFileDialog.getSaveFileName(parent, "Export project", name + EXTENSION, f"Event-Based Studio project (*{EXTENSION})")
    if not path:
        return None
    destination = Path(path)
    if not destination.suffix:
        destination = destination.with_suffix(EXTENSION)
    return destination, include_recording
