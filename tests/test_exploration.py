import csv
import gc
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from event_studio.app import MainWindow, NamedROI, Slice
from event_studio.viewer import EventBatch, load_events_from_csv
from event_studio.roi_label import Roi
from event_studio.recording_overview import overview_bins, RecordingOverview
from event_studio.quality_diagnostics import recording_quality
from event_studio.plot_navigation import PlotNavigation
from event_studio.filters import CancelledError
from event_studio.batch import analyze_batch


def events(t, x=None, y=None, p=None):
    n = len(t)
    return EventBatch(np.array(t, dtype=np.int64),
                      np.array(x if x is not None else [0]*n, dtype=np.int32),
                      np.array(y if y is not None else [0]*n, dtype=np.int32),
                      np.array(p if p is not None else [1]*n, dtype=np.int8),
                      {"sorted": True, "resolution": [4, 4], "complete": True})


class ExplorationNumericsTests(unittest.TestCase):
    def test_overview_keeps_all_events_at_large_integer_timestamps(self):
        origin = 2**53 + 10
        source = np.array([origin, origin, origin+1, origin+900, origin+999], dtype=np.int64)
        edges, counts = overview_bins(source, 10)
        self.assertEqual(int(edges[0]), origin)
        self.assertEqual(int(edges[-1]), origin+1000)
        self.assertEqual(counts.sum(), 5)
        self.assertLessEqual(len(counts), 10)
        for a, b, count in zip(edges[:-1], edges[1:], counts):
            self.assertEqual(count, np.count_nonzero((source >= a) & (source < b)))

    def test_overview_empty_and_same_timestamp(self):
        self.assertEqual(len(overview_bins(np.array([], dtype=np.int64))[0]), 0)
        edges, counts = overview_bins(np.array([10, 10, 10], dtype=np.int64))
        self.assertEqual(edges.tolist(), [10, 11])
        self.assertEqual(counts.tolist(), [3])

    def test_diagnostics_thresholds_gaps_polarity_and_neighbor_support(self):
        source = events([0, 10, 20, 10000], [0, 1, 0, 3], p=[1, -1, 0, 1])
        report = recording_quality(source, (4, 4), hot_rate=0.15, gap_us=9000, support_us=15)
        self.assertEqual(report["hot_pixel_count"], 1)
        self.assertEqual(report["hot_pixels"][0]["x"], 0)
        self.assertEqual(report["gap_count"], 1)
        self.assertEqual(report["largest_gaps"][0]["gap_us"], 9980)
        self.assertEqual(report["unsupported_events"], 2)
        self.assertEqual(report["positive_fraction"], 0.5)
        json.dumps(report)
        self.assertEqual(len(source.t), 4)

    def test_diagnostics_cancellation_and_invalid_thresholds(self):
        with self.assertRaises(CancelledError):
            recording_quality(events([0, 1]), (4, 4), cancelled=lambda: True)
        with self.assertRaises(ValueError):
            recording_quality(events([0]), (4, 4), hot_rate=0)

    def test_batch_exports_normalized_rates_and_current_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "events.csv"
            path.write_text("t,x,y,p\n0,0,0,1\n1000,1,1,-1\n2000,0,0,1\n")
            report = analyze_batch([path], root / "out", bin_us=1000, threshold=0,
                                   min_burst_us=1001, polarity="pos")
            row = report["results"][0]
            self.assertEqual(row["events"], 2)
            self.assertEqual(row["area_pixels"], 4)
            self.assertAlmostEqual(row["events_per_ms_per_pixel"], row["events_per_ms"] / 4)
            self.assertEqual(row["bursts"], 0)
            self.assertEqual(report["parameters"]["polarity"], "pos")
            self.assertEqual(report["parameters"]["min_burst_us"], 1001)
            with (root / "out" / "summary.csv").open(newline="") as stream:
                exported = list(csv.DictReader(stream))[0]
            self.assertEqual(exported["area_pixels"], "4")


class ExplorationUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "events.csv"
        self.path.write_text("t,x,y,p\n10000000,0,0,1\n10001000,1,0,0\n10002000,0,1,-1\n10003000,1,1,1\n")
        self.window = MainWindow()
        self.window._load_csv_into_app(self.path, "test", prepared_events=load_events_from_csv(self.path))

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        gc.collect()
        self.temp.cleanup()

    def wait_worker(self):
        for _ in range(1000):
            if self.window._task is None:
                return
            QTest.qWait(10)
        self.fail("Worker did not finish")

    def add_roi(self, name="Probe"):
        self.window._on_candidate_roi_changed(Roi(0, 0, 1, 1))
        with patch("event_studio.app.QInputDialog.getText", return_value=(name, True)):
            self.window._add_roi_from_candidate()

    def test_undo_redo_roi_add_color_visibility_and_branch(self):
        w = self.window
        self.add_roi()
        self.assertTrue(w.undo_action.isEnabled())
        roi_id = w.rois[0].id
        w.edit_history.undo()
        self.assertEqual(w.rois, [])
        w.edit_history.redo()
        self.assertEqual(w.rois[0].id, roi_id)
        w.roi_list.item(0).setCheckState(Qt.Unchecked)
        self.assertFalse(w.rois[0].visible)
        w.edit_history.undo()
        self.assertTrue(w.rois[0].visible)
        w._cycle_selected_roi_color()
        self.assertFalse(w.redo_action.isEnabled())
        w.edit_history.undo()
        self.assertEqual(w.rois[0].color, "#ff3b30")

    def test_undo_roi_drag_is_one_gesture(self):
        w = self.window
        self.add_roi()
        count = len(w.edit_history.undo_stack)
        w.edit_history.begin_gesture("Move ROI")
        w._on_active_roi_moved(Roi(1, 0, 1, 1))
        w._on_active_roi_moved(Roi(1, 1, 1, 1))
        w.edit_history.end_gesture()
        self.assertEqual(len(w.edit_history.undo_stack), count+1)
        w.edit_history.undo()
        self.assertEqual(w.rois[0].roi, Roi(0, 0, 1, 1))
        w.edit_history.redo()
        self.assertEqual(w.rois[0].roi, Roi(1, 1, 1, 1))

    def test_slice_graph_selection_and_delete_restore_exact_snapshot(self):
        w = self.window
        self.add_roi()
        duration = w.duration_us
        with patch("event_studio.app.QInputDialog.getText", return_value=("Graph section", True)):
            w._slice_from_plot(10000500, 10002500)
        saved = w.slices[0]
        self.assertEqual(w.duration_us, duration)
        self.assertEqual((saved.t0, saved.t1), (10000500, 10002500))
        self.assertEqual(saved.roi_snapshot, {"x": 0, "y": 0, "w": 1, "h": 1})
        w._delete_selected_slice()
        self.assertEqual(w.slices, [])
        w.edit_history.undo()
        self.assertEqual(w.slices[0], saved)
        w.edit_history.undo()
        self.assertEqual(w.slices, [])

    def test_cancelled_slice_dialog_does_not_add_history(self):
        w = self.window
        before = (w.position_us, w.duration_us)
        with patch("event_studio.app.QInputDialog.getText", return_value=("", False)):
            w._slice_from_plot(10000500, 10002500)
        self.assertEqual(w.slices, [])
        self.assertEqual(w.edit_history.undo_stack, [])
        self.assertEqual((w.position_us, w.duration_us), before)

    def test_slice_delete_action_and_timeline_zoom_keep_playback_window(self):
        from PySide6.QtWidgets import QPushButton
        w = self.window
        with patch("event_studio.app.QInputDialog.getText", return_value=("Saved interval", True)):
            w._add_slice_from_current_view()
        self.assertEqual(len(w.slices), 1)
        self.assertFalse(any(b.text() in ("Save slice", "Delete slice") for b in w.findChildren(QPushButton)))
        self.assertTrue(w.btn_delete_slice.isEnabled())
        w.btn_delete_slice.trigger()
        self.assertEqual(w.slices, [])
        w.edit_history.undo()
        self.assertEqual(len(w.slices), 1)
        before = (w.position_us, w.duration_us)
        w._zoom_interval()
        w._zoom_full()
        self.assertEqual((w.position_us, w.duration_us), before)
        self.assertEqual((w.zoom_start, w.zoom_end), (w.t_min, w.t_max + 1))

    def test_full_load_preserves_preview_slices_and_regions(self):
        from dataclasses import replace
        w = self.window
        full = w.events
        full.metadata.update(input_path=str(self.path), input_sha256=full.metadata['sha256'])
        partial = replace(full, t=full.t[:2], x=full.x[:2], y=full.y[:2], p=full.p[:2],
                          metadata={**full.metadata, 'complete': False, 'sha256': 'f' * 64, 'loaded_events': 2})
        w._load_csv_into_app(self.path, 'preview', prepared_events=partial)
        self.add_roi()
        with patch('event_studio.app.QInputDialog.getText', return_value=('Preview slice', True)):
            w._add_slice_from_current_view()
        session = w._build_session_dict()
        w._restore_session(session, partial)
        self.assertFalse(w.events.metadata['complete'])
        self.assertFalse(w.full_recording_button.isHidden())
        with patch('event_studio.recording_import.load_recording', return_value=(self.path, full)):
            w._load_full_recording()
            self.wait_worker()
        self.assertTrue(w.events.metadata['complete'])
        self.assertTrue(w.full_recording_button.isHidden())
        self.assertEqual(len(w.rois), 1)
        self.assertEqual(w.slices[0].name, 'Preview slice')
        self.assertEqual(w.slices[0].source_sha256, full.metadata['sha256'])

    def test_history_cleared_when_loading_another_recording(self):
        w = self.window
        self.add_roi()
        w._load_csv_into_app(self.path, "again", prepared_events=load_events_from_csv(self.path))
        self.assertEqual(w.edit_history.undo_stack, [])
        self.assertFalse(w.undo_action.isEnabled())

    def test_overlay_visibility_and_loop_can_be_undone(self):
        w = self.window
        w.chk_show_rois.setChecked(False)
        w.edit_history.undo()
        self.assertTrue(w.chk_show_rois.isChecked())
        with patch("event_studio.app.QInputDialog.getText", return_value=("Section", True)):
            w._add_slice_from_current_view()
        w._toggle_loop_selected_slice()
        self.assertEqual(w.loop_slice_index, 0)
        w.edit_history.undo()
        self.assertIsNone(w.loop_slice_index)

    def test_overview_click_and_drag_signals(self):
        overview = self.window.recording_overview
        self.window.resize(1600, 1000)
        self.window.show()
        QTest.qWait(1)
        left, right = overview.track_bounds()
        seek = []
        duration = self.window.duration_us
        overview.seekRequested.connect(seek.append)
        QTest.mouseClick(overview, Qt.LeftButton, pos=QPoint((left + right) // 2, 20))
        self.assertEqual(len(seek), 1)
        QTest.mousePress(overview, Qt.LeftButton, pos=QPoint(left, 20))
        QTest.mouseRelease(overview, Qt.LeftButton, pos=QPoint(right, 20))
        self.assertEqual(seek[-1], 10003001)
        self.assertEqual(self.window.duration_us, duration)
        self.assertEqual(self.window.slices, [])

    def test_plot_navigation_seeks_clicks_and_spans_without_double_action(self):
        from event_studio.analysis_window import ActivityPlotWindow
        plot = ActivityPlotWindow(self.window)
        seek, spans = [], []
        nav = PlotNavigation(plot.canvas, seek.append, lambda a,b: spans.append((a,b)), lambda: 2**53)
        axis = object()
        nav.press(SimpleNamespace(button=1, inaxes=axis, xdata=0.001, x=10))
        nav.release(SimpleNamespace(button=1, inaxes=axis, xdata=0.001, x=11))
        self.assertEqual(seek, [2**53+1])
        nav.press(SimpleNamespace(button=1, inaxes=axis, xdata=0.003, x=20))
        nav.release(SimpleNamespace(button=1, inaxes=axis, xdata=0.001, x=10))
        self.assertEqual(spans, [(2**53+1, 2**53+3)])
        self.assertEqual(len(seek), 1)

    def test_comparison_runs_all_rois_and_normalizes_export(self):
        w = self.window
        self.add_roi("Small")
        w._on_candidate_roi_changed(Roi(0, 0, 2, 2))
        with patch("event_studio.app.QInputDialog.getText", return_value=("Large", True)):
            w._add_roi_from_candidate()
        w._compare_roi_activity()
        self.wait_worker()
        workspace = w._workspace
        self.assertEqual(len(workspace.results["series"]), 2)
        self.assertTrue(workspace.results["config"]["normalize"])
        captured = []
        with patch.object(workspace, "save_measurement", side_effect=lambda title, columns, rows, metadata: captured.append((columns, list(rows)))):
            workspace.export_measurements()
        columns, rows = captured[0]
        rate = columns.index("events_per_ms")
        normalized = columns.index("events_per_ms_per_pixel")
        for row in rows:
            area = 1 if row[0] == "Small" else 4
            self.assertAlmostEqual(row[normalized], row[rate] / area)

    def test_roi_plot_histogram_includes_last_event_and_uses_relative_time(self):
        w = self.window
        source = events([2**53, 2**53+1, 2**53+2])
        payload = w.analysis_panel._build_activity_plot_payload(source, Roi(0,0,1,1), "Probe", "source", 2**53+2)
        self.assertEqual(payload["total_counts"].sum(), 3)
        self.assertEqual(payload["origin_us"], 2**53)
        self.assertAlmostEqual(payload["current_time_ms"], 0.002)

    def test_graph_slice_uses_graph_context_and_undo_redo_preserves_it(self):
        w = self.window
        self.add_roi()
        w.polarity_combo.setCurrentText("pos")
        context = {"source_sha256": w.events.metadata.get("sha256"), "polarity": "both",
                   "filters": {}, "roi_snapshot": {"x": 1, "y": 0, "w": 1, "h": 2}}
        with patch("event_studio.app.QInputDialog.getText", return_value=("Raw graph", True)):
            w._slice_from_plot(10000500, 10002500, context)
        self.assertEqual(w.slices[0].polarity, "both")
        self.assertEqual(w.slices[0].roi_snapshot, context["roi_snapshot"])
        self.assertIsNone(w.slices[0].roi_index)
        w.edit_history.undo()
        self.assertEqual(w.slices, [])
        w.edit_history.redo()
        self.assertEqual(w.slices[0].roi_snapshot, context["roi_snapshot"])

    def test_roi_delete_undo_restores_linked_slice_ids_and_bounds(self):
        w = self.window
        self.add_roi()
        with patch("event_studio.app.QInputDialog.getText", return_value=("Saved", True)):
            w._add_slice_from_current_view()
        roi_id, slice_id = w.rois[0].id, w.slices[0].id
        w._delete_selected_roi()
        self.assertEqual(w.rois, [])
        self.assertEqual(w.slices[0].roi_snapshot, {"x": 0, "y": 0, "w": 1, "h": 1})
        w.edit_history.undo()
        self.assertEqual(w.rois[0].id, roi_id)
        self.assertEqual(w.slices[0].id, slice_id)
        self.assertEqual(w.slices[0].roi_index, 0)

    def test_quality_dialog_background_report_and_export(self):
        from event_studio.quality_diagnostics import QualityDialog
        dialog = QualityDialog(self.window)
        dialog.run()
        self.wait_worker()
        self.assertEqual(dialog.report["events"], 4)
        self.assertTrue(dialog.export_button.isEnabled())
        output = self.root / "quality.json"
        with patch("event_studio.quality_diagnostics.QFileDialog.getSaveFileName", return_value=(str(output), "JSON")):
            dialog.export()
        self.assertEqual(json.loads(output.read_text())["events"], 4)
        dialog.close()


if __name__ == "__main__":
    unittest.main()
