"""Exercise live appearance changes without writing user preferences."""
import ast
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
from PySide6.QtCore import QSettings, QEvent
from PySide6.QtWidgets import QApplication
from event_studio.project_browser import ProjectBrowser, ProjectTile
from event_studio.theme import appearance_controller
from event_studio.ui_icons import icon, StudioButton
from event_studio import ui_icons


class AppearanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.controller = appearance_controller()
        self.previous_mode = self.controller.mode
        self.previous_settings = self.controller.settings
        self.controller.settings = QSettings(str(Path(self.directory.name) / "appearance.ini"), QSettings.IniFormat)
        self.controller.set_mode("glass", persist=False)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.controller.settings = self.previous_settings
        self.controller.set_mode(self.previous_mode, persist=False)
        self.directory.cleanup()

    def test_switch_restores_icons_and_preserves_browser_state(self):
        settings = QSettings(str(Path(self.directory.name) / "browser.ini"), QSettings.IniFormat)
        browser = ProjectBrowser(Path(self.directory.name) / "projects", lambda _: None, settings=settings)
        self.windows.append(browser)
        browser.projects = [{"project_name": "Test project", "project_dir": self.directory.name}]
        browser.view_combo.setCurrentIndex(browser.view_combo.findData("cards"))
        browser.search.setText("Test")
        browser.show()
        self.app.processEvents()
        self.assertTrue(browser.studio_header.appearance.isVisible())
        tile = browser.grid.itemAt(0).widget()
        self.assertIsInstance(tile, ProjectTile)
        self.assertFalse(browser.btn_new.icon().isNull())
        self.assertEqual(tile.menu_btn.text(), "")
        for mode in ("classic", "glass", "classic", "glass"):
            browser.studio_header.appearance.setCurrentIndex(browser.studio_header.appearance.findData(mode))
            self.app.processEvents()
            self.assertEqual(browser.search.text(), "Test")
            self.assertEqual(browser.view_combo.currentData(), "cards")
            tile = browser.grid.itemAt(0).widget()
            self.assertEqual(tile.project_dir, self.directory.name)
            self.assertEqual(self.controller.settings.value("mode"), mode)
            self.assertEqual(browser.btn_new.icon().isNull(), mode == "classic")
            self.assertEqual(tile.menu_btn.text(), "..." if mode == "classic" else "")
            self.assertEqual(browser.search_action.isVisible(), mode == "glass")

    def test_play_pause_icon_tracks_state_and_original_mode(self):
        button = StudioButton("Play")
        self.windows.append(button)
        button.show()
        self.app.processEvents()
        play = button.icon().cacheKey()
        button.setText("Pause")
        self.assertFalse(button.icon().isNull())
        self.assertNotEqual(button.icon().cacheKey(), play)
        self.controller.set_mode("classic", persist=False)
        self.assertTrue(button.icon().isNull())
        button.setText("Play")
        self.assertTrue(button.icon().isNull())
        self.controller.set_mode("glass", persist=False)
        self.assertEqual(button.icon().cacheKey(), play)

    def test_all_mapped_icons_exist_in_installed_font(self):
        tree = ast.parse(Path(ui_icons.__file__).read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                names.update(value.value for value in node.values if isinstance(value, ast.Constant) and isinstance(value.value, str))
            if isinstance(node, ast.Tuple) and len(node.elts) == 2 and all(isinstance(x, ast.Constant) and isinstance(x.value, str) for x in node.elts):
                names.add(node.elts[1].value)
        for name in names | {"squares-four", "rows", "list", "magnifying-glass", "x", "minus", "copy", "square"}:
            with self.subTest(icon=name):
                self.assertFalse(icon(name).isNull())


if __name__ == "__main__":
    unittest.main()
