import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from event_studio import rendering
from event_studio.app import (MainWindow, NamedROI, Slice, VIEW_MODE_RAW, VIEW_MODE_HEATMAP,
                              VIEW_MODE_TRAIL, VIEW_MODE_PERSISTENCE, VIEW_MODE_GLOW,
                              VIEW_MODE_MOTION_ARROWS)
from event_studio.project_utils import save_project_bundle
from event_studio.roi_label import Roi
from event_studio.science import export_csv, select
from event_studio.viewer import load_events_from_csv, infer_hw, accumulate_frame


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # Window close now captures recovery state. Keep its project directory
        # alive until the window cleanup has run (unittest cleanups are LIFO).
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "events.csv"
        self.path.write_text("t,x,y,p\n10000000,0,0,1\n10000001,1,0,0\n10000002,0,1,-1\n10000003,1,1,1\n", encoding="utf-8")
        self.events = load_events_from_csv(self.path)

    def window(self):
        window = MainWindow()
        window._load_csv_into_app(self.path, "test", prepared_events=self.events)
        self.addCleanup(window.close)
        return window

    def wait_worker(self, window):
        deadline = monotonic() + 10
        while window._task is not None and monotonic() < deadline:
            QTest.qWait(10)
        self.assertIsNone(window._task, "Background operation did not finish")

    def test_roi_context_actions_and_candidate_preservation(self):
        window = self.window()
        menu = window._build_roi_context_menu()
        self.addCleanup(menu.deleteLater)
        self.assertFalse(window.btn_rename_roi.isEnabled())
        self.assertFalse(window.btn_add_roi.isEnabled())
        window._on_candidate_roi_changed(Roi(0, 0, 1, 1))
        QTest.mouseClick(window.view, Qt.RightButton, pos=QPoint(1, 1))
        self.assertIsNotNone(window._candidate_roi)
        window.rois = [NamedROI(name="Layer", roi=Roi(0, 0, 1, 1), color="#ff0000")]
        window.active_roi_index = 0
        window._rebuild_roi_list()
        menu = window._build_roi_context_menu()
        self.addCleanup(menu.deleteLater)
        self.assertTrue(window.btn_add_roi.isEnabled())
        self.assertTrue(window.btn_rename_roi.isEnabled())
        visible = next(action for action in menu.actions() if action.text() == "Visible")
        visible.trigger()
        self.assertFalse(window.rois[0].visible)
        window.btn_duplicate_roi.trigger()
        self.assertEqual(len(window.rois), 2)

    def test_image_context_selects_roi_under_pointer(self):
        window = self.window()
        window.rois = [NamedROI(name="Layer", roi=Roi(0, 0, 1, 1), color="#ff0000")]
        window._rebuild_roi_list()
        QTimer.singleShot(0, lambda: QApplication.activePopupWidget().close())
        with patch.object(window.view, "_widget_to_image", return_value=(0, 0)):
            window._show_roi_context_menu(window.view, QPoint(1, 1))
        self.assertEqual(window.active_roi_index, 0)

    def test_slice_context_menu_actions_and_timeline_selection(self):
        window = self.window()
        menu = window._build_slice_context_menu()
        self.addCleanup(menu.deleteLater)
        self.assertTrue(window.btn_add_slice.isEnabled())
        self.assertFalse(window.btn_delete_slice.isEnabled())
        with patch("event_studio.app.QInputDialog.getText", return_value=("Section", True)):
            window.btn_add_slice.trigger()
        self.assertEqual(len(window.slices), 1)
        window.slice_list.setCurrentRow(-1)
        QTimer.singleShot(0, lambda: QApplication.activePopupWidget().close())
        with patch.object(window.timeline, "_hit_test_slice", return_value=(0, "move")):
            window._show_slice_context_menu(window.timeline, QPoint(10, 10))
        self.assertEqual(window.slice_list.currentRow(), 0)
        self.assertTrue(window.btn_delete_slice.isEnabled())
        window.btn_loop_slice.trigger()
        self.assertEqual(window.loop_slice_index, 0)
        self.assertEqual(window.btn_loop_slice.text(), "Stop Loop")
        window.btn_delete_slice.trigger()
        self.assertEqual(window.slices, [])
        self.assertIsNone(window.loop_slice_index)

    def test_file_actions_follow_empty_loaded_and_reset_state(self):
        window = MainWindow()
        self.addCleanup(window.close)
        self.assertTrue(all(not action.isEnabled() for action in window._recording_file_actions))

        self.assertFalse(window._rename_project_action.isEnabled())
        window.current_project_dir = self.root
        window._update_file_menu_actions()
        self.assertTrue(window._rename_project_action.isEnabled())
        window._load_csv_into_app(self.path, "test", prepared_events=self.events)
        window._update_file_menu_actions()
        self.assertTrue(all(action.isEnabled() for action in window._recording_file_actions))
        window._reset_view()
        self.assertTrue(all(action.isEnabled() for action in window._recording_file_actions))
        window._clear_recording()
        self.assertTrue(all(not action.isEnabled() for action in window._recording_file_actions))


    def test_studio_header_tracks_title_and_window_controls(self):
        window = self.window()
        window.show()
        self.assertTrue(window.windowFlags() & Qt.FramelessWindowHint)
        self.assertIs(window.menuWidget(), window.studio_header)
        window.setWindowTitle("Studio title")
        self.assertEqual(window.studio_header.title.text(), "Studio title")
        window.studio_header.maximize.click()
        self.assertTrue(window.isMaximized())
        window.studio_header.maximize.click()
        self.assertFalse(window.isMaximized())
        window.studio_header.close_button.click()
        self.assertFalse(window.isVisible())

    def test_exact_integer_csv_and_headerless_first_row(self):
        self.path.write_text("1,0,-1,9007199254740993\n0,1,1,9007199254740994\n", encoding="utf-8")
        events = load_events_from_csv(self.path)
        self.assertEqual(events.t.tolist(), [9007199254740993, 9007199254740994])
        self.assertFalse(events.t.flags.writeable)

    def test_preview_detection_and_export_guard(self):
        events = load_events_from_csv(self.path, max_events=2)
        self.assertFalse(events.metadata["complete"])
        with self.assertRaisesRegex(ValueError, "limited preview"):
            export_csv(self.root / "preview.csv", events, (2, 2))
        self.assertTrue(load_events_from_csv(self.path, max_events=4).metadata["complete"])

    def test_source_cannot_be_overwritten_by_export(self):
        original = self.path.read_bytes()
        with self.assertRaisesRegex(ValueError, "source recording"):
            export_csv(self.path, self.events, (2, 2))
        self.assertEqual(self.path.read_bytes(), original)

    def test_export_cannot_collide_with_its_metadata(self):
        with self.assertRaisesRegex(ValueError, "must end in .csv"):
            export_csv(self.root / "wrong.json", self.events, (2, 2))
        self.assertFalse((self.root / "wrong.json").exists())

    def test_positive_only_ratio_is_not_fabricated(self):
        from event_studio.viewer import compute_roi_stats
        batch = select(self.events, polarity="pos")
        stats = compute_roi_stats(batch, (2, 2), Roi(0, 0, 2, 2), 10000000, 4)
        self.assertEqual(stats.polarity_ratio, float("inf"))

    def test_invalid_inputs_rejected(self):
        for body in ("t,x,y,p\n2,0,0,1\n1,0,0,0", "t,x,y,p\n0,-1,0,1",
                     "t,x,y,p\n0,0,0,2", "t,x,y,p\n0.5,0,0,1", "t,x,y,p\n"):
            self.path.write_text(body, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_events_from_csv(self.path)

    def test_half_open_query_and_lossless_export(self):
        chosen = select(self.events, 10000001, 10000003, Roi(0, 0, 2, 2), "neg")
        self.assertEqual(chosen.t.tolist(), [10000001, 10000002])
        self.assertTrue(np.shares_memory(select(self.events, 10000001, 10000003).t, self.events.t))
        out = self.root / "export.csv"
        self.assertEqual(export_csv(out, self.events, (2, 2), t0=10000001, t1=10000003, polarity="neg"), 2)
        restored = load_events_from_csv(out)
        for name in ("t", "x", "y", "p"):
            np.testing.assert_array_equal(getattr(chosen, name), getattr(restored, name))
        self.assertEqual(json.loads(out.with_suffix(".json").read_text())["source"]["sha256"], self.events.metadata["sha256"])

    def test_rendering_does_not_modify_events_and_polarities_differ(self):
        before = [a.copy() for a in (self.events.t, self.events.x, self.events.y, self.events.p)]
        raw = rendering.raw(self.events, (2, 2), 10000000, 10000004)
        self.assertFalse(np.array_equal(raw[0, 0], raw[0, 1]))
        for image in (rendering.heatmap(self.events, (2, 2), 10000000, 10000004)[0],
                      rendering.persistence(self.events, (2, 2), 10000004, 4),
                      rendering.glow(self.events, (2, 2), 10000000, 10000004)):
            self.assertEqual(image.shape, (2, 2, 3))
        for expected, actual in zip(before, (self.events.t, self.events.x, self.events.y, self.events.p)):
            np.testing.assert_array_equal(expected, actual)
        earlier = rendering.persistence(self.events, (2, 2), 10000004, 10)
        later = rendering.persistence(self.events, (2, 2), 10000008, 10)
        self.assertLess(int(later.sum()), int(earlier.sum()))

    def test_accumulation_does_not_wrap_at_65536(self):
        from event_studio.viewer import EventBatch
        count = 65536
        events = EventBatch(np.zeros(count, dtype=np.int64), np.zeros(count, dtype=np.int32),
                            np.zeros(count, dtype=np.int32), np.ones(count, dtype=np.int8))
        self.assertEqual(int(accumulate_frame(events, (1, 1), 1)[0, 0]), 255)

    def test_all_modes_save_rgb_project_images(self):
        window = self.window()
        for mode in (VIEW_MODE_RAW, VIEW_MODE_HEATMAP, VIEW_MODE_TRAIL, VIEW_MODE_PERSISTENCE,
                     VIEW_MODE_GLOW, VIEW_MODE_MOTION_ARROWS):
            window.current_view_mode = mode
            window._render_from_ui()
            project = self.root / mode
            save_project_bundle(project, mode, window._build_session_dict(), window.current_frame,
                                window._generate_preview_frames(2))
            self.assertFalse(QImage(str(project / "thumbnail.png")).isNull())
            self.assertTrue((project / "session.json").exists())

    def test_exact_slice_jump_playback_zoom_and_roundtrip(self):
        window = self.window()
        window.slices = [Slice("exact", 10000001, 10000003, polarity="neg")]
        window._rebuild_slice_list()
        window.slice_list.setCurrentRow(0)
        window.duration_us = 1
        window._jump_to_selected_slice()
        self.assertEqual(window._current_window(), (10000001, 10000002))
        window._zoom_interval()
        self.assertEqual((window.zoom_start, window.zoom_end), (10000001, 10000002))
        window.step_us.setValue(1)
        window.is_playing = True
        window._on_tick()
        window.is_playing = False
        self.assertEqual(window.position_us, 10000002)
        session = window._build_session_dict()
        restored = MainWindow()
        self.addCleanup(restored.close)
        restored._restore_session(session, self.events)
        self.assertEqual(restored._current_window(), window._current_window())
        self.assertEqual(restored.polarity_combo.currentText(), "neg")
        self.assertEqual(restored.slices[0].id, window.slices[0].id)

    def test_slice_keeps_spatial_selection_after_roi_deletion(self):
        window = self.window()
        roi = NamedROI("probe", Roi(0, 0, 1, 2))
        window.rois = [roi]
        window.active_roi_index = 0
        window._rebuild_roi_list()
        with patch("event_studio.app.QInputDialog.getText", return_value=("slice", True)):
            window._add_slice_from_current_view()
        snapshot = window.slices[0].roi_snapshot.copy()
        roi.roi = Roi(0, 0, 2, 2)
        window._delete_selected_roi()
        self.assertEqual(window.slices[0].roi_snapshot, snapshot)
        self.assertEqual(len(select(self.events, roi=Roi(**snapshot)).t), 2)

    def test_source_change_rejected(self):
        window = self.window()
        session = window._build_session_dict()
        session["source"]["metadata"] = {"sha256": "changed"}
        with self.assertRaisesRegex(ValueError, "content has changed"):
            window._restore_session(session, self.events)

    def test_legacy_session_preserves_position_and_migrates_roi(self):
        window = self.window()
        session = {"format_version": 2, "source": {"csv_path": str(self.path)},
                   "view": {"timeline_value": 500, "window_ms": 1},
                   "rois": [{"name": "old", "x": 0, "y": 0, "w": 1, "h": 2}],
                   "slices": [{"name": "old slice", "t0": 10000000, "t1": 10000003, "roi_index": 0}]}
        window._restore_session(session, self.events)
        self.assertEqual(window.position_us, 10000001)
        self.assertEqual(window.slices[0].roi_id, window.rois[0].id)
        self.assertEqual(window.slices[0].roi_snapshot, {"x": 0, "y": 0, "w": 1, "h": 2})

    def test_opening_replacement_recording_refreshes_existing_project_preview(self):
        from unittest.mock import Mock
        window = self.window()
        window.current_project_dir = self.root / 'project'
        window.save_project()
        self.wait_worker(window)
        project = window.current_project_dir
        saved_session = (project / 'session.json').read_bytes()
        old_thumb = (project / 'thumbnail.png').read_bytes()
        old_preview = (project / 'preview_frames' / 'frame_00.png').read_bytes()
        replacement = self.root / 'replacement.csv'
        replacement.write_text('t,x,y,p\n1,3,3,1\n2,3,3,1\n', encoding='utf-8')
        window.browser_ref = Mock()
        window._open_recording_path(replacement)
        self.wait_worker(window)
        self.assertEqual(Path(window.loaded_csv_path), replacement.resolve())
        self.assertNotEqual((project / 'thumbnail.png').read_bytes(), old_thumb)
        self.assertNotEqual((project / 'preview_frames' / 'frame_00.png').read_bytes(), old_preview)
        self.assertEqual(len(list((project / 'preview_frames').glob('*.png'))), 10)
        self.assertEqual((project / 'session.json').read_bytes(), saved_session)
        window.browser_ref.refresh_projects.assert_called()
        # Saving afterwards must keep the replacement artwork and source.
        window.save_project()
        self.wait_worker(window)
        self.assertEqual(json.loads((project / 'session.json').read_text())['source']['loaded_name'], replacement.stem)

    def test_background_open_save_and_restore(self):
        window = MainWindow()
        self.addCleanup(window.close)
        with patch("event_studio.app.QFileDialog.getOpenFileName", return_value=(str(self.path), "")):
            window._open_recording()
        self.wait_worker(window)
        self.assertEqual(len(window.events.t), 4)
        window.current_project_dir = self.root / "project"
        window.view_mode_combo.setCurrentText(VIEW_MODE_GLOW)
        window.save_project()
        self.wait_worker(window)
        session_path = window.current_project_dir / "session.json"
        self.assertTrue(session_path.exists())
        window._reset_view()
        with patch("event_studio.app.QFileDialog.getOpenFileName", return_value=(str(session_path), "")):
            window._load_session_dialog()
        self.wait_worker(window)
        self.assertEqual(window.current_view_mode, VIEW_MODE_GLOW)
        self.assertEqual(len(window.events.t), 4)

    def test_background_export_and_failure_cleanup(self):
        window = self.window()
        output = self.root / "full.csv"
        with patch("event_studio.app.QFileDialog.getSaveFileName", return_value=(str(output), "")):
            window._export_full()
        self.wait_worker(window)
        self.assertEqual(len(load_events_from_csv(output).t), 4)
        with patch("event_studio.app.QMessageBox.critical") as error:
            def fail():
                raise ValueError("expected failure")
            window._run_task(fail, lambda result: self.fail("Unexpected success"))
            self.wait_worker(window)
            error.assert_called_once()
        self.assertTrue(window.centralWidget().isEnabled())

    def test_malformed_session_is_rejected_before_replacing_state(self):
        window = self.window()
        session = window._build_session_dict()
        session["slices"] = [{"t0": 2, "t1": 1}]
        with self.assertRaisesRegex(ValueError, "invalid slice"):
            window._restore_session(session, self.events)
        self.assertFalse(window._restoring)

    def test_sensor_dimensions_and_parameters_survive_session(self):
        window = self.window()
        with patch("event_studio.app.QInputDialog.getText", return_value=("640x480", True)):
            window._set_sensor_resolution()
        window.persistence_ms.setValue(123.456)
        window.glow_intensity.setValue(1.4)
        window.heat_scale.setCurrentIndex(2)
        window.compare_check.setChecked(True)
        session = window._build_session_dict()
        restored = MainWindow()
        self.addCleanup(restored.close)
        restored._restore_session(session, self.events)
        self.assertEqual(restored.hw, (480, 640))
        self.assertEqual(restored.persistence_ms.value(), 123.456)
        self.assertEqual(restored.glow_intensity.value(), 1.4)
        self.assertTrue(restored.compare_check.isChecked())
        self.assertEqual(restored.heat_scale.currentIndex(), 2)

    def test_polarity_filter_preserves_unfiltered_comparison(self):
        window = self.window()
        window.compare_check.setChecked(True)
        window.polarity_combo.setCurrentText("pos")
        self.assertEqual(int(window.current_frame[0, 1].sum()), 0)
        reference = window.compare_view._pix.toImage()
        self.assertGreater(reference.pixelColor(1, 0).blue(), 0)
        self.assertEqual(len(window.events.t), 4)

    def test_roi_edge_clamping(self):
        from event_studio.roi_label import ROILabel
        viewer = ROILabel()
        viewer.set_image_size(2, 2)
        self.assertEqual(viewer._normalize_roi(Roi(1, 1, 5, 5)), Roi(1, 1, 1, 1))

    def test_dat_sensor_header(self):
        from event_studio.science import dat_resolution
        dat = self.root / "source.dat"
        dat.write_bytes(b"% Width 640\n% Height 480\n\x00\x01\x02")
        self.assertEqual(dat_resolution(dat), {"width": 640, "height": 480})

    def test_converter_paths_are_literal_and_existing_outputs_are_protected(self):
        import shlex
        from event_studio.convert import _shell_path, h5_to_csv_windows
        filename = "/mnt/c/a folder/$(unexpected)`name`.h5"
        self.assertEqual(shlex.split(_shell_path(filename)), [filename])
        source = self.root / "source.h5"
        source.write_bytes(b"test")
        with self.assertRaises(FileExistsError):
            h5_to_csv_windows(source, self.path)

    def test_invalid_preview_generation_keeps_existing_frames(self):
        from event_studio.project_utils import save_preview_frames
        project = self.root / "project"
        save_preview_frames(project, [np.zeros((2, 2), dtype=np.uint8)])
        frame = project / "preview_frames" / "frame_00.png"
        original = frame.read_bytes()
        with self.assertRaises(ValueError):
            save_preview_frames(project, [np.zeros((2, 2, 4), dtype=np.uint8)])
        self.assertEqual(frame.read_bytes(), original)

    def test_boot_overlay_is_retained_by_application(self):
        from event_studio.app import _try_show_boot
        with patch("event_studio.boot.show_boot", return_value=object()) as show:
            _try_show_boot(self.app)
            self.assertIs(self.app.boot_overlay, show.return_value)

    def test_legacy_headerless_session_accounts_for_skipped_first_event(self):
        self.path.write_text("0,0,1,1\n0,0,1,100\n0,0,0,200\n", encoding="utf-8")
        events = load_events_from_csv(self.path)
        window = MainWindow()
        self.addCleanup(window.close)
        session = {"format_version": 6, "source": {"csv_path": str(self.path), "max_events": 2},
                   "view": {"timeline_value": 500}}
        window._restore_session(session, events)
        self.assertEqual(window.position_us, 150)

    def test_selected_slice_and_deleted_roi_snapshot_restore(self):
        window = self.window()
        window.slices = [Slice("saved", 10000000, 10000003, roi_id="deleted",
                               roi_snapshot={"x": 0, "y": 0, "w": 1, "h": 2})]
        window._rebuild_slice_list()
        window.slice_list.setCurrentRow(0)
        session = window._build_session_dict()
        restored = MainWindow()
        self.addCleanup(restored.close)
        restored._restore_session(session, self.events)
        self.assertEqual(restored.slice_list.currentRow(), 0)
        self.assertIn("Events: 2", restored.slice_stats.text())


if __name__ == "__main__":
    unittest.main()
