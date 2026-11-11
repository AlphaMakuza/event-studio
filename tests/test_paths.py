import os
from pathlib import Path
import unittest
from unittest.mock import patch

from event_studio.paths import storage_root


class StorageTests(unittest.TestCase):
    def test_test_process_storage_is_separate_from_real_project_library(self):
        workspace = Path(__file__).resolve().parents[1]
        self.assertTrue(storage_root().is_relative_to(workspace / 'artifacts' / 'test-storage'))
        self.assertNotEqual(storage_root() / 'projects', workspace / 'projects')

    def test_packaged_storage_is_outside_installation(self):
        with patch.dict(os.environ, {"EVENT_STUDIO_HOME": ""}), patch("sys.frozen", True, create=True), patch(
            "PySide6.QtCore.QStandardPaths.writableLocation", return_value="C:/Users/Example/AppData/Local"
        ):
            self.assertEqual(storage_root(), Path("C:/Users/Example/AppData/Local/Event-Based Studio"))

    def test_explicit_storage_overrides_packaged_default(self):
        with patch.dict(os.environ, {"EVENT_STUDIO_HOME": "custom-storage"}), patch("sys.frozen", True, create=True):
            self.assertEqual(storage_root(), Path("custom-storage").resolve())
