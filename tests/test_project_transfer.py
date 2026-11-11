import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from event_studio.project_transfer import export_project, import_project
from event_studio.project_utils import save_project_bundle, list_projects, save_json, rename_project_folder
from event_studio.recovery import (AUTOSAVE, PREVIOUS, write_recovery, read_recovery,
    clear_recovery, resolve_session_source, session_digest)
from event_studio.science import fingerprint
from event_studio.viewer import load_events_from_csv


class ProjectTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "original" / "Experiment"
        self.project.mkdir(parents=True)
        self.csv = self.root / "source data.csv"
        self.csv.write_text("t,x,y,p\n9007199254741000,0,0,1\n9007199254741001,1,1,0\n", encoding="utf-8")
        self.events = load_events_from_csv(self.csv)
        self.session = {"format_version": 8, "project_name": "Experiment",
            "source": {"csv_path": str(self.csv), "metadata": self.events.metadata},
            "view": {"position_us": int(self.events.t[0]), "duration_us": 2},
            "filters": {"refractory_us": 0}, "analysis_settings": {"bin_us": 1000},
            "annotations": [{"name": "Observation", "text": "Check this", "t0": 9007199254741000,
                             "t1": 9007199254741001, "labels": ["trial"]}],
            "rois": [{"id": "probe", "name": "Probe", "x": 0, "y": 0, "w": 2, "h": 2}],
            "slices": [{"id": "slice", "name": "Interval", "t0": 9007199254741000,
                        "t1": 9007199254741002, "roi_id": "probe", "source_sha256": fingerprint(self.csv)}]}
        save_project_bundle(self.project, "Experiment", self.session, np.zeros((2, 2), dtype=np.uint8),
                            [np.zeros((2, 2), dtype=np.uint8)])
        self.archive = self.root / "transfer.ebs"
        self.imports = self.root / "another computer"

    def export(self, **kwargs):
        return export_project(self.archive, self.session, self.project, **kwargs)

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        mutate(files)
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)

    def assert_no_import(self):
        self.assertEqual(list_projects(self.imports), [])
        self.assertFalse(any(self.imports.glob(".bundle-import-*")))

    def test_recording_and_analysis_survive_transfer_and_folder_move(self):
        sidecar = {"csv_sha256": fingerprint(self.csv), "sensor_resolution": {"width": 4, "height": 4}}
        save_json(self.csv.with_suffix(".json"), sidecar)
        self.export()
        original = self.csv.read_bytes()
        imported = import_project(self.archive, self.imports)
        moved = self.root / "moved again"
        imported.rename(moved)
        saved = json.loads((moved / "session.json").read_text())
        self.assertEqual(saved["source"]["csv_path"], "recording/events.csv")
        session = resolve_session_source(saved, moved)
        recovered = load_events_from_csv(session["source"]["csv_path"])
        np.testing.assert_array_equal(recovered.t, self.events.t)
        np.testing.assert_array_equal(recovered.p, self.events.p)
        self.assertEqual(recovered.metadata["resolution"], [4, 4])
        self.assertEqual(saved["annotations"], self.session["annotations"])
        self.assertEqual(saved["rois"], self.session["rois"])
        self.assertEqual(saved["slices"], self.session["slices"])
        self.assertEqual(saved["analysis_settings"], self.session["analysis_settings"])
        self.assertEqual(saved["filters"], self.session["filters"])
        self.assertTrue((moved / "thumbnail.png").is_file())
        self.assertTrue((moved / "preview_frames/frame_00.png").is_file())
        self.assertEqual(self.csv.read_bytes(), original)

    def test_lightweight_bundle_does_not_copy_recording(self):
        self.export(include_recording=False)
        with zipfile.ZipFile(self.archive) as archive:
            self.assertNotIn("recording/events.csv", archive.namelist())
        imported = import_project(self.archive, self.imports)
        saved = json.loads((imported / "session.json").read_text())
        self.assertEqual(saved["source"]["metadata"]["sha256"], fingerprint(self.csv))
        self.assertFalse((imported / saved["source"]["csv_path"]).exists())

    def test_existing_project_is_not_overwritten(self):
        self.export()
        first = import_project(self.archive, self.imports)
        (first / "keep.txt").write_text("Keep me")
        second = import_project(self.archive, self.imports)
        self.assertNotEqual(first, second)
        self.assertEqual((first / "keep.txt").read_text(), "Keep me")

    def test_changed_source_cannot_be_exported_with_old_measurements(self):
        self.archive.write_bytes(b"previous bundle")
        self.csv.write_text("t,x,y,p\n1,0,0,1\n")
        for included in (True, False):
            with self.subTest(included=included), self.assertRaisesRegex(ValueError, "changed"):
                self.export(include_recording=included)
            self.assertEqual(self.archive.read_bytes(), b"previous bundle")

    def test_cancelled_export_preserves_existing_destination(self):
        from event_studio.filters import CancelledError
        self.archive.write_bytes(b"previous bundle")
        with self.assertRaises(CancelledError):
            self.export(cancel=lambda: True)
        self.assertEqual(self.archive.read_bytes(), b"previous bundle")
        self.assertFalse(any(self.root.glob(".bundle-*.tmp")))

    def test_cancelled_import_does_not_publish_partial_project(self):
        from event_studio.filters import CancelledError
        self.export()
        with self.assertRaises(CancelledError):
            import_project(self.archive, self.imports, cancel=lambda: True)
        self.assert_no_import()

    def test_cancelling_after_copy_has_started_preserves_outputs(self):
        from event_studio.filters import CancelledError
        cancelled = [False]
        def progress(*_):
            cancelled[0] = True
        self.archive.write_bytes(b"previous bundle")
        with self.assertRaises(CancelledError):
            self.export(cancel=lambda: cancelled[0], progress=progress)
        self.assertEqual(self.archive.read_bytes(), b"previous bundle")
        self.export()
        cancelled[0] = False
        with self.assertRaises(CancelledError):
            import_project(self.archive, self.imports, cancel=lambda: cancelled[0], progress=progress)
        self.assert_no_import()

    def test_modified_payload_rejected_without_partial_project(self):
        self.export()
        self.rewrite(lambda files: files.__setitem__("recording/events.csv", b"changed"))
        with self.assertRaises(ValueError):
            import_project(self.archive, self.imports)
        self.assert_no_import()

    def test_unsafe_and_unexpected_entries_are_rejected(self):
        for name in ("../outside.txt", "/absolute.txt", "C:/outside.txt", "..\\outside.txt", "script.py", "recording/../../outside"):
            with self.subTest(name=name):
                self.export()
                with zipfile.ZipFile(self.archive, "a") as archive:
                    archive.writestr(name, b"bad")
                with self.assertRaises(ValueError):
                    import_project(self.archive, self.imports)
                self.assert_no_import()
        self.assertFalse((self.root / "outside.txt").exists())

    def test_symlink_and_case_collisions_rejected(self):
        self.export()
        with zipfile.ZipFile(self.archive, "a") as archive:
            link = zipfile.ZipInfo("recording/events.json")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../outside")
        with self.assertRaises(ValueError):
            import_project(self.archive, self.imports)
        self.assert_no_import()
        self.export()
        with zipfile.ZipFile(self.archive, "a") as archive:
            archive.writestr("SESSION.JSON", "{}")
        with self.assertRaises(ValueError):
            import_project(self.archive, self.imports)

    def test_import_size_limit_enforced_before_extraction(self):
        self.export()
        with self.assertRaisesRegex(ValueError, "size limit"):
            import_project(self.archive, self.imports, max_bytes=1)
        self.assert_no_import()

    def test_session_source_cannot_escape_its_project(self):
        session = {"source": {"csv_path": "../outside.csv"}}
        with self.assertRaisesRegex(ValueError, "escapes"):
            resolve_session_source(session, self.project)

    def test_autosave_preserves_manual_save_and_previous_valid_snapshot(self):
        manual = (self.project / "session.json").read_bytes()
        self.session["annotations"][0]["text"] = "First unsaved edit"
        write_recovery(self.project, self.session)
        self.session["annotations"][0]["text"] = "Second edit"
        write_recovery(self.project, self.session)
        self.assertEqual((self.project / "session.json").read_bytes(), manual)
        self.assertEqual(read_recovery(self.project)["session"]["annotations"][0]["text"], "Second edit")
        (self.project / AUTOSAVE).write_text("broken json")
        self.assertEqual(read_recovery(self.project)["session"]["annotations"][0]["text"], "First unsaved edit")
        self.assertTrue((self.project / PREVIOUS).exists())

    def test_failed_autosave_keeps_latest_valid_snapshot(self):
        self.session["annotations"][0]["text"] = "Protected"
        write_recovery(self.project, self.session)
        self.session["annotations"][0]["text"] = "Newer edit"
        original_replace = __import__("os").replace
        def fail(source, target):
            if Path(target).name == AUTOSAVE:
                raise OSError("Disk full")
            return original_replace(source, target)
        with patch("event_studio.project_utils.os.replace", side_effect=fail), self.assertRaises(OSError):
            write_recovery(self.project, self.session)
        self.assertEqual(read_recovery(self.project)["session"]["annotations"][0]["text"], "Protected")

    def test_recovery_for_renamed_project_keeps_name_and_relative_recording(self):
        internal = self.project / "recording.csv"
        internal.write_bytes(self.csv.read_bytes())
        self.session["source"]["csv_path"] = str(internal)
        self.session["annotations"][0]["text"] = "Unsaved"
        write_recovery(self.project, self.session)
        renamed = rename_project_folder(self.project.parent, self.project, "Renamed")
        recovery = read_recovery(renamed)["session"]
        self.assertEqual(recovery["project_name"], "Renamed")
        self.assertEqual(recovery["source"]["csv_path"], "recording.csv")
        self.assertTrue(Path(resolve_session_source(recovery, renamed)["source"]["csv_path"]).exists())

    def test_timestamp_and_playback_do_not_make_identical_content_dirty(self):
        first = session_digest(self.session, self.project)
        self.session["saved_at"] = "later"
        self.session["view"]["is_playing"] = True
        self.assertEqual(first, session_digest(self.session, self.project))
        write_recovery(self.project, self.session)
        self.assertIsNone(read_recovery(self.project))
        clear_recovery(self.project)
        self.assertFalse((self.project / AUTOSAVE).exists())

    def test_another_window_cannot_overwrite_or_delete_a_newer_snapshot(self):
        self.session["annotations"][0]["text"] = "Window A"
        revision = write_recovery(self.project, self.session, expected_revision=None)
        self.session["annotations"][0]["text"] = "Window B"
        with self.assertRaisesRegex(ValueError, "another window"):
            write_recovery(self.project, self.session, expected_revision=None)
        with self.assertRaisesRegex(ValueError, "another window"):
            clear_recovery(self.project, expected_revision=None)
        self.assertEqual(read_recovery(self.project)["session"]["annotations"][0]["text"], "Window A")
        write_recovery(self.project, self.session, expected_revision=revision)
        self.assertEqual(read_recovery(self.project)["session"]["annotations"][0]["text"], "Window B")


if __name__ == "__main__":
    unittest.main()
