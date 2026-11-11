import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
import gc
from unittest.mock import patch
from PySide6.QtCore import (
    QObject,
    QSettings,
    QUrl,
    Signal,
    Qt,
    QCoreApplication,
    QEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
from event_studio.analysis_window import ActivityPlotWindow, SpatialPlotWindow
from event_studio.project_browser import ProjectBrowser, ProjectTile
from event_studio.project_utils import create_project_dir, rename_project, rename_project_folder
import json
from event_studio.boot import show_boot
from shiboken6 import isValid


class Sound(QObject):
    playingChanged = Signal()
    statusChanged = Signal()
    Error = 2

    def __init__(self, parent):
        super().__init__(parent)
        self.playing = False

    def setVolume(self, value):
        pass

    def setLoopCount(self, value):
        pass

    def setSource(self, value):
        pass

    def source(self):
        return QUrl("file:///fixture.wav")

    def status(self):
        return 1

    def play(self):
        pass  # Model asynchronous device startup.

    def stop(self):
        self.playing = False
        self.playingChanged.emit()

    def isPlaying(self):
        return self.playing


class HomepageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.addCleanup(self.flush_widgets)

    def flush_widgets(self):
        # Dispose GUI fixtures on the GUI thread before later acquisition tests
        # start Python workers that can trigger cyclic garbage collection.
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()

    def close_overlay(self, overlay):
        if isValid(overlay):
            overlay.close()
            overlay.deleteLater()

    def test_homepage_waits_for_playback_and_reveals_once(self):
        reveals = []
        with patch("event_studio.boot.QSoundEffect", Sound):
            overlay = show_boot(self.app, on_done=lambda: reveals.append("shown"))
            self.addCleanup(self.close_overlay, overlay)
            overlay.player.playingChanged.emit()  # False while loading is not completion.
            self.assertEqual(reveals, [])
            self.assertTrue(overlay.isVisible())
            overlay.player.playing = True
            overlay.player.playingChanged.emit()
            self.assertEqual(reveals, [])
            overlay.player.stop()
            self.assertEqual(reveals, ["shown"])
            self.assertFalse(overlay.isVisible())
            overlay.player.playingChanged.emit()
            self.assertEqual(reveals, ["shown"])

    def test_audio_fallback_still_reveals_homepage(self):
        reveals = []
        with patch("event_studio.boot.QSoundEffect", Sound):
            overlay = show_boot(self.app, on_done=lambda: reveals.append(True))
            self.addCleanup(self.close_overlay, overlay)
            overlay._fallback.timeout.emit()
            self.assertEqual(reveals, [True])
            self.assertTrue(overlay.finished)

    def test_real_steps_run_in_order_and_audio_cannot_reveal_early(self):
        ran = []
        reveals = []
        with patch("event_studio.boot.QSoundEffect", Sound):
            overlay = show_boot(
                self.app,
                steps=[
                    (
                        "First task",
                        lambda: ran.append(("first", overlay.step_label.text())),
                    ),
                    (
                        "Second task",
                        lambda: ran.append(("second", overlay.step_label.text())),
                    ),
                ],
                on_done=lambda: reveals.append(list(overlay.completed_steps)),
            )
            self.addCleanup(self.close_overlay, overlay)
            overlay.player.playing = True
            overlay.player.playingChanged.emit()
            overlay.player.stop()
            self.assertEqual(reveals, [])
            QTest.qWait(1100)
            self.assertEqual(
                ran, [("first", "First task…"), ("second", "Second task…")]
            )
            self.assertEqual(reveals, [["First task", "Second task"]])

    def test_failed_startup_step_is_not_reported_as_complete(self):
        reveals = []
        errors = []

        def fail():
            raise OSError("fixture storage failure")

        with patch("event_studio.boot.QSoundEffect", Sound):
            overlay = show_boot(
                self.app,
                steps=[("Prepare storage", fail)],
                on_done=lambda: reveals.append(True),
                on_error=errors.append,
            )
            self.addCleanup(self.close_overlay, overlay)
            for _ in range(4):
                self.app.processEvents()
            self.assertEqual(reveals, [])
            self.assertEqual(overlay.completed_steps, [])
            self.assertIn("fixture storage failure", overlay.step_label.text())
            self.assertEqual(len(errors), 1)

    def test_project_views_search_sort_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            for name in ("Zebra", "Alpha"):
                project = create_project_dir(root, name)
                rename_project(project, name)
            settings = QSettings(
                str(Path(directory) / "settings.ini"), QSettings.IniFormat
            )
            opened = []
            browser = ProjectBrowser(root, opened.append, settings=settings)
            self.addCleanup(browser.close)
            browser.show()
            self.app.processEvents()
            browser.sort_combo.setCurrentIndex(1)
            self.assertEqual(
                browser.grid.itemAt(0).widget().project_info["project_name"], "Alpha"
            )
            for mode in ("rows", "text", "cards"):
                browser.view_combo.setCurrentIndex(browser.view_combo.findData(mode))
                self.app.processEvents()
                self.assertEqual(browser.grid.count(), 2)
                tile = browser.grid.itemAt(0).widget()
                self.assertIsInstance(tile, ProjectTile)
                self.assertEqual(tile.image_label.isHidden(), mode == "text")
            QTest.keyClick(tile, Qt.Key_Return)
            self.assertEqual(opened, [tile.project_dir])
            browser.search.setText("zEbRa")
            self.assertEqual(browser.grid.count(), 1)
            self.assertEqual(
                browser.grid.itemAt(0).widget().project_info["project_name"], "Zebra"
            )
            browser.search.setText("missing")
            self.assertIn(
                "No matching projects", browser.grid.itemAt(0).widget().text()
            )
            reopened = ProjectBrowser(root, opened.append, settings=settings)
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.view_combo.currentData(), "cards")

    def test_project_deletion_requires_confirmation_and_removes_local_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            project = create_project_dir(root, "Delete me")
            (project / "session.json").write_text("{}")
            external = Path(directory) / "recording.csv"
            external.write_text("recording")
            browser = ProjectBrowser(root, lambda _: None)
            self.addCleanup(browser.close)
            with patch("event_studio.project_browser.QMessageBox.question", return_value=QMessageBox.No):
                browser._delete_project(str(project))
            self.assertTrue(project.exists())
            with patch("event_studio.project_browser.QMessageBox.question", return_value=QMessageBox.Yes):
                browser._delete_project(str(project))
            self.assertFalse(project.exists())
            self.assertTrue(external.exists())
            self.assertEqual(browser.projects, [])

    def test_rename_project_moves_folder_and_preserves_session_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            project = create_project_dir(root, "Before")
            rename_project(project, "Before")
            recording = project / "recording.csv"
            recording.write_text("events")
            (project / "session.json").write_text(json.dumps({
                "project_name": "Before", "source": {"csv_path": str(recording)}
            }))
            browser = ProjectBrowser(root, lambda _: None)
            self.addCleanup(browser.close)
            with patch("event_studio.project_browser.QInputDialog.getText", return_value=("After", True)):
                browser._rename_project(str(project))
            renamed = root / "After"
            self.assertFalse(project.exists())
            self.assertEqual((renamed / "recording.csv").read_text(), "events")
            session = json.loads((renamed / "session.json").read_text())
            self.assertEqual(Path(session["source"]["csv_path"]).resolve(), (renamed / "recording.csv").resolve())
            self.assertEqual(session["project_name"], "After")
            self.assertEqual(browser.projects[0]["project_name"], "After")
            create_project_dir(root, "Taken")
            with self.assertRaises(ValueError):
                rename_project_folder(root, renamed, "Taken")
            self.assertTrue(renamed.exists())

    def test_project_deletion_rejects_outside_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "projects"
            outside = Path(directory) / "outside"
            outside.mkdir()
            browser = ProjectBrowser(root, lambda _: None)
            self.addCleanup(browser.close)
            with patch("event_studio.project_browser.QMessageBox.critical") as error, \
                    patch("event_studio.project_browser.QMessageBox.question") as confirm:
                browser._delete_project(str(outside))
            error.assert_called_once()
            confirm.assert_not_called()
            self.assertTrue(outside.exists())

    def test_analysis_graphs_are_closable_windows_and_reopen(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        for graph_type in (ActivityPlotWindow, SpatialPlotWindow):
            graph = graph_type(parent)
            self.assertTrue(graph.isWindow())
            self.assertTrue(graph.windowFlags() & Qt.WindowCloseButtonHint)
            graph.show()
            graph.btn_close.click()
            self.assertFalse(graph.isVisible())
            graph.show()
            self.assertTrue(graph.isVisible())
            graph.close()
            self.assertFalse(graph.isVisible())


if __name__ == "__main__":
    unittest.main()
