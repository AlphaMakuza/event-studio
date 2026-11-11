import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from time import monotonic
from PySide6.QtCore import QEvent
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from event_studio.app import MainWindow
from event_studio.project_utils import create_project_dir, save_project_bundle, list_projects
from event_studio.recovery import AUTOSAVE, write_recovery, read_recovery
from event_studio.viewer import load_events_from_csv


class ProjectRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.project = create_project_dir(self.projects, "Experiment")
        self.csv = self.root / "events.csv"
        self.csv.write_text("t,x,y,p\n1000,0,0,1\n1001,1,1,0\n")
        self.events = load_events_from_csv(self.csv)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.temp.cleanup()

    def window(self):
        window = MainWindow()
        window.projects_root = self.projects
        window.current_project_dir = self.project
        window.project_name = self.project.name
        window._load_csv_into_app(self.csv, "events", prepared_events=self.events)
        self.windows.append(window)
        return window

    def wait_task(self, window):
        deadline = monotonic() + 10
        while window._task is not None and monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(window._task)

    def test_close_saves_real_session_and_preview_then_reopens_without_prompt(self):
        window = self.window()
        window.annotations = [{"name": "Note", "text": "Last edit", "t0": 1000, "t1": 1001}]
        window.close()
        saved = json.loads((self.project / "session.json").read_text())
        self.assertEqual(saved["annotations"][0]["text"], "Last edit")
        self.assertTrue((self.project / "thumbnail.png").is_file())
        self.assertEqual(len(list((self.project / "preview_frames").glob('*.png'))), 10)
        self.assertFalse((self.project / AUTOSAVE).exists())
        with patch.object(QMessageBox, "exec") as prompt:
            reopened = MainWindow(project_dir=str(self.project))
            self.windows.append(reopened)
            self.wait_task(reopened)
        prompt.assert_not_called()
        self.assertEqual(reopened.annotations[0]["text"], "Last edit")
        self.assertFalse(reopened.is_playing)
        from PySide6.QtGui import QAction
        actions = [a.text() for a in reopened.findChildren(QAction)]
        self.assertNotIn("Save recovery snapshot now", actions)
        self.assertFalse(hasattr(reopened, 'autosave_timer'))

    def test_legacy_unsaved_work_migrates_to_normal_save_on_close(self):
        window = self.window()
        session = window._build_session_dict()
        session['annotations'] = [{"name": "Note", "text": "Older unsaved work", "t0": 1000, "t1": 1001}]
        write_recovery(self.project, session)
        reopened = MainWindow(project_dir=str(self.project))
        self.windows.append(reopened)
        self.wait_task(reopened)
        self.assertEqual(reopened.annotations[0]['text'], 'Older unsaved work')
        reopened.close()
        self.assertFalse((self.project / AUTOSAVE).exists())
        self.assertEqual(json.loads((self.project / 'session.json').read_text())['annotations'][0]['text'], 'Older unsaved work')

    def test_wrong_relinked_recording_preserves_current_analysis(self):
        window = self.window()
        session = window._build_session_dict()
        session["source"]["csv_path"] = str(self.root / "missing.csv")
        wrong = self.root / "wrong.csv"
        wrong.write_text("t,x,y,p\n42,0,0,1\n")
        original = window.events
        with patch("event_studio.app.QFileDialog.getOpenFileName", return_value=(str(wrong), "")), patch(
            "event_studio.app.QMessageBox.critical"
        ) as error:
            window._restore_session(session)
            self.wait_task(window)
        error.assert_called_once()
        self.assertIs(window.events.t, original.t)
        self.assertEqual(window.events.metadata["sha256"], original.metadata["sha256"])
        self.assertEqual(window.loaded_csv_path, str(self.csv))

    def test_failed_save_blocks_close_and_preserves_previous_session(self):
        window = self.window()
        window._save_on_close()
        previous = (self.project / 'session.json').read_bytes()
        event = QCloseEvent()
        with patch('event_studio.app.save_project_bundle', side_effect=OSError('disk full')), patch.object(QMessageBox, 'critical') as error:
            window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        error.assert_called_once()
        self.assertEqual((self.project / 'session.json').read_bytes(), previous)

    def test_busy_project_does_not_save_or_close(self):
        window = self.window()
        window._task = object()
        event = QCloseEvent()
        try:
            with patch.object(window, '_save_on_close') as save:
                window.closeEvent(event)
            save.assert_not_called()
            self.assertFalse(event.isAccepted())
        finally:
            window._task = None

    def test_imported_bundle_opens_and_relinked_lightweight_bundle_can_be_saved(self):
        from event_studio.project_transfer import export_project, import_project
        window = self.window()
        for included in (True, False):
            archive = self.root / f"transfer-{included}.ebs"
            export_project(archive, window._build_session_dict(), self.project, include_recording=included)
            imported = import_project(archive, self.root / "other computer")
            with patch("event_studio.app.QFileDialog.getOpenFileName", return_value=(str(self.csv), "")) as locate:
                reopened = MainWindow(project_dir=str(imported))
                self.windows.append(reopened)
                self.wait_task(reopened)
            self.assertIsNotNone(reopened.events)
            self.assertEqual(reopened.events.metadata["sha256"], self.events.metadata["sha256"])
            self.assertEqual(locate.call_count, 0 if included else 1)
            reopened.save_project()
            self.wait_task(reopened)
            stored = json.loads((imported / "session.json").read_text())
            if included:
                self.assertEqual(stored["source"]["csv_path"], "recording/events.csv")
            else:
                self.assertEqual(Path(stored["source"]["csv_path"]).resolve(), self.csv.resolve())


if __name__ == "__main__":
    unittest.main()
