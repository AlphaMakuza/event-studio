import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
import gc
from unittest.mock import patch
from PySide6.QtCore import QObject, QSettings, QUrl, Signal, Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from event_studio.project_browser import ProjectBrowser, ProjectTile
from event_studio.project_utils import create_project_dir, rename_project
from event_studio.boot import show_boot


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

    def test_homepage_waits_for_playback_and_reveals_once(self):
        reveals = []
        with patch("event_studio.boot.QSoundEffect", Sound):
            overlay = show_boot(self.app, on_done=lambda: reveals.append("shown"))
            self.addCleanup(overlay.close)
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
            self.addCleanup(overlay.close)
            overlay._fallback.timeout.emit()
            self.assertEqual(reveals, [True])
            self.assertTrue(overlay.finished)

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


if __name__ == "__main__":
    unittest.main()
