"""Capture a synthetic-data product screenshot without using private projects."""
import os
from pathlib import Path
import tempfile

os.environ["QT_QPA_PLATFORM"] = "offscreen"


def main():
    import numpy as np
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from event_studio.app import MainWindow
    from event_studio.theme import configure_application, appearance_controller
    from event_studio.viewer import load_events_from_csv

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        os.environ["EVENT_STUDIO_HOME"] = str(root)
        QSettings.setDefaultFormat(QSettings.IniFormat)
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root / "settings"))
        rng = np.random.default_rng(42)
        count = 80000
        t = np.arange(count) * 10
        angle = rng.uniform(0, 2 * np.pi, count)
        radius = 60 + rng.normal(0, 2, count)
        x = np.clip(160 + radius * np.cos(angle) + 25 * np.sin(t / 160000), 0, 319).astype(int)
        y = np.clip(120 + radius * np.sin(angle), 0, 239).astype(int)
        source = root / "Synthetic ring.csv"
        np.savetxt(source, np.column_stack([t, x, y, (np.cos(angle) > 0).astype(int)]), delimiter=",", header="t,x,y,p", comments="", fmt="%d")
        app = QApplication([])
        configure_application(app)
        appearance_controller().set_mode("glass", persist=False)
        window = MainWindow()
        window.resize(1520, 940)
        window._load_csv_into_app(source, "Synthetic motion study", prepared_events=load_events_from_csv(source))
        window.show()
        for _ in range(8):
            app.processEvents()
        destination = Path("website/dist/assets/studio.png")
        destination.parent.mkdir(parents=True, exist_ok=True)
        assert window.grab().save(str(destination))
        window.close()
        print(destination.resolve())


if __name__ == "__main__":
    main()
