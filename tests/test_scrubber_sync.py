import gc
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QPoint, Qt, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyle, QStyleOptionSlider

from event_studio.app import MainWindow, Slice
from event_studio.theme import appearance_controller
from event_studio.viewer import load_events_from_csv


class ScrubberSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = dict(os.environ)
        os.environ['EVENT_STUDIO_HOME'] = str(self.root)
        source = self.root / 'events.csv'
        self.origin = 2**53 + 20
        source.write_text('t,x,y,p\n' + ''.join(f'{self.origin+i*1000},{i%4},{i%3},{i%2}\n' for i in range(2001)))
        self.window = MainWindow()
        self.window.resize(1800, 1000)
        self.window._load_csv_into_app(source, 'Sync test', prepared_events=load_events_from_csv(source))
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.window = None
        gc.collect()
        os.environ.clear(); os.environ.update(self.env)
        self.temp.cleanup()

    def assert_aligned(self):
        w = self.window
        self.app.processEvents()
        self.assertEqual(w.recording_overview.time_range(), (w.zoom_start, w.zoom_end))
        self.assertEqual(w.recording_overview.interval[0], w.position_us)
        option = QStyleOptionSlider(); w.timeline.initStyleOption(option)
        handle = w.timeline.style().subControlRect(QStyle.CC_Slider, option, QStyle.SC_SliderHandle, w.timeline)
        slider_x = w.timeline.mapTo(w, handle.center()).x()
        activity_x = w.recording_overview.mapTo(w, QPoint(round(w.recording_overview.time_to_x(w.position_us)), 0)).x()
        self.assertLessEqual(abs(slider_x - activity_x), 1,
                             (slider_x, activity_x, w.timeline.width(), w.timeline.track_bounds(),
                              w.timeline.value(), option.sliderPosition, w.position_us, w.zoom_start, w.zoom_end))

    def test_shared_range_and_pixel_alignment_across_zoom_resize_and_themes(self):
        w = self.window
        for mode in ('classic', 'glass'):
            appearance_controller().set_mode(mode, persist=False)
            self.assertFalse(w.step_back_button.icon().isNull())
            self.assertFalse(w.step_forward_button.icon().isNull())
            for width in (1280, 1660):
                w.resize(width, 1000)
                self.app.processEvents()
                w._zoom_full()
                w._seek(self.origin + 1100000)
                self.assert_aligned()
                w.duration_us = 200000
                w._zoom_interval()
                self.assert_aligned()
                overview = w.recording_overview
                point = QPoint(round(overview.time_to_x(w.zoom_start + 80000)), 25)
                expected = overview.timestamp(point.x())
                QTest.mouseClick(overview, Qt.LeftButton, pos=point)
                self.assertEqual(w.position_us, expected)
                self.assertEqual(w.duration_us, 200000)
                self.assert_aligned()
                # A seek beyond a zoomed range must pan both controls together.
                w._seek(self.origin + 1800000)
                self.assertLessEqual(w.zoom_start, w.position_us)
                self.assertGreater(w.zoom_end, w.position_us)
                self.assert_aligned()

    def test_overview_has_no_interval_overlay_and_short_frame_reset(self):
        w = self.window
        overview = w.recording_overview
        overview.set_interval(self.origin, self.origin + 10000)
        before = overview.grab().toImage()
        overview.set_interval(self.origin, self.origin + 1900000)
        self.assertEqual(overview.grab().toImage(), before)
        w._seek(self.origin + 700000)
        after = overview.grab().toImage()
        self.assertNotEqual(after, before)
        x = round(overview.time_to_x(w.position_us))
        self.assertEqual(after.pixelColor(x, 2).name(), '#fff2fc')
        self.assert_aligned()
        w.window_ms.setValue(1946.952)
        QTest.mouseClick(w.short_frame_btn, Qt.LeftButton)
        self.assertEqual(w.duration_us, 20000)

    def test_timeline_comments_and_read_only_notes_overview(self):
        w = self.window
        panel = w.timeline_notes
        w._seek(self.origin + 300000)
        panel.editor.setPlainText('Person enters the image')
        QTest.mouseClick(panel.add_button, Qt.LeftButton)
        self.assertEqual(len(w.annotations), 1)
        note = w.annotations[0]
        self.assertEqual((note['t0'], note['t1']), (self.origin + 300000,) * 2)
        # Legacy interval notes remain intact, and appear in time order.
        w.annotations.append({'name': 'Earlier note', 'text': 'Existing interval',
                              't0': self.origin + 100000, 't1': self.origin + 200000})
        w._open_analysis_workspace()
        overview = w._workspace
        self.assertEqual(overview.notes.count(), 2)
        self.assertTrue(overview.note_detail.isReadOnly())
        self.assertIn('0.100–0.200 s', overview.notes.item(0).text())
        duration = w.duration_us
        overview.notes.setCurrentRow(0)
        overview.jump_annotation()
        self.assertEqual(w.position_us, self.origin + 100000)
        self.assertEqual(w.duration_us, duration)
        panel.editor.setPlainText('Updated interval comment')
        panel.save_edit()
        self.assertEqual(w.annotations[1]['t1'], self.origin + 200000)
        self.assertIn('Updated interval comment', overview.note_detail.toPlainText())
        panel.clear_selection()
        w._seek(self.origin + 900000)
        self.app.processEvents()
        x = next(x for i, x in panel.markers.positions() if i == 0)
        QTest.mouseClick(panel.markers, Qt.LeftButton, pos=QPoint(x, 15))
        self.assertEqual(w.position_us, note['t0'])
        self.assertEqual(w.duration_us, duration)
        self.assertEqual(panel.editor.toPlainText(), note['text'])
        panel.delete_note()
        self.assertEqual(len(w.annotations), 1)
        self.assertEqual(overview.notes.count(), 1)
        overview.close()

    def test_long_multiline_note_is_saved_without_truncation(self):
        from event_studio.app import MainWindow
        panel = self.window.timeline_notes
        panel.editor.setFocus()
        panel.editor.setPlainText('First paragraph')
        QTest.keyClick(panel.editor, Qt.Key_Return)
        self.assertIn('\n', panel.editor.toPlainText())
        self.assertEqual(self.window.annotations, [])
        text = 'First paragraph\n\n' + ('Detailed observation. ' * 2000) + '\nFinal paragraph'
        panel.editor.setPlainText(text)
        panel.add_note()
        self.assertEqual(self.window.annotations[0]['text'], text)
        panel.select_note(0)
        self.assertEqual(panel.editor.toPlainText(), text)
        restored = MainWindow()
        try:
            restored._restore_session(self.window._build_session_dict(), self.window.events)
            restored.timeline_notes.select_note(0)
            self.assertEqual(restored.timeline_notes.editor.toPlainText(), text)
        finally:
            restored.close()

    def test_refresh_view_preserves_project_and_undo_history(self):
        import numpy as np
        from event_studio.app import NamedROI
        from event_studio.roi_label import Roi
        w = self.window
        original = w.edit_history.snapshot()
        w.rois = [NamedROI('Keep me', Roi(0, 0, 2, 2))]
        w.active_roi_index = 0
        w.slices = [Slice('Keep slice', self.origin, self.origin + 300000)]
        w.annotations = [{'name': 'Keep note', 't0': self.origin, 't1': self.origin + 10}]
        w._rebuild_roi_list()
        w._rebuild_slice_list()
        w.edit_history.commit('Add test selections', original)
        w._seek(self.origin + 700000)
        w._zoom_interval()
        events = w.events
        before = w._build_session_dict()
        frame = w.current_frame.copy()
        history = w.edit_history
        w.current_frame[:] = 0
        w._reset_view()
        after = w._build_session_dict()
        self.assertIs(w.events, events)
        self.assertIs(w.edit_history, history)
        self.assertEqual(len(history.undo_stack), 1)
        for key in ('rois', 'slices', 'annotations', 'filters'):
            self.assertEqual(after[key], before[key])
        self.assertEqual(w.position_us, self.origin + 700000)
        self.assertEqual(w.duration_us, before['view']['duration_us'])
        self.assertEqual((w.zoom_start, w.zoom_end), (w.t_min, w.t_max + 1))
        np.testing.assert_array_equal(w.current_frame, frame)
        history.undo()
        self.assertEqual(w.rois, [])
        self.assertEqual(w.slices, [])

    def test_analysis_defaults_to_full_recording_and_slice_menu_uses_slice_bounds(self):
        w = self.window
        w._seek(self.origin + 700000)
        before = (w.position_us, w.duration_us)
        w._open_analysis_workspace()
        analysis = w._workspace
        self.app.processEvents()
        self.assertEqual((int(analysis.start.text()), int(analysis.end.text())),
                         (w.t_min, w.t_max + 1))
        self.assertTrue(hasattr(analysis, 'studio_header'))
        self.assertTrue(analysis.isVisible())
        w.slices = [Slice('Probe interval', self.origin + 100000, self.origin + 500000)]
        w._rebuild_slice_list()
        w.slice_list.setCurrentRow(0)
        menu = w._build_slice_context_menu()
        action = next(a for a in menu.actions() if a.text() == 'Advanced analysis for this slice')
        action.trigger()
        self.assertEqual((int(analysis.start.text()), int(analysis.end.text())),
                         (w.slices[0].t0, w.slices[0].t1))
        self.assertEqual((w.position_us, w.duration_us), before)
        for i in range(analysis.tabs.count()):
            analysis.tabs.setCurrentIndex(i)
            self.assertNotIn('Choose settings, then', analysis.tab_help.text())
        w._open_analysis_workspace()
        self.assertEqual((int(analysis.start.text()), int(analysis.end.text())),
                         (w.t_min, w.t_max + 1))
        analysis.close()
        menu.deleteLater()

    def test_secondary_dialog_headers_and_spin_arrow_contrast(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QStyleOptionSpinBox
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import QRect
        from event_studio.window_chrome import StudioHeader
        for mode in ('classic', 'glass'):
            appearance_controller().set_mode(mode, persist=False)
            dialog = QDialog(self.window)
            dialog.setWindowTitle('Test dialog')
            QVBoxLayout(dialog).addWidget(QLabel('Content'))
            dialog.show()
            self.app.processEvents()
            self.assertTrue(dialog.isVisible())
            self.assertIsNotNone(dialog.findChild(StudioHeader))
            self.assertTrue(dialog.findChild(StudioHeader).appearance.isHidden())
            self.assertFalse(self.window.studio_header.appearance.isHidden())
            image = QImage(20, 20, QImage.Format_RGB32)
            image.fill(Qt.black)
            painter = QPainter(image)
            option = QStyleOptionSpinBox()
            option.rect = QRect(0, 0, 20, 20)
            option.state = QStyle.State_Enabled
            self.app.style().drawPrimitive(QStyle.PE_IndicatorSpinUp, option, painter)
            painter.end()
            self.assertGreater(image.pixelColor(9, 9).lightness(), 200)
            dialog.close()
            dialog.deleteLater()

    def test_scrubbing_still_works_with_overlapping_slices_and_after_edits(self):
        w = self.window
        w.duration_us = 10000
        w.slices = [Slice('Overlapping', self.origin + 300000, self.origin + 1500000),
                    Slice('Whole recording', self.origin, self.origin + 2000001)]
        w._rebuild_slice_list(); w._update_timeline_slice_regions()
        saved = [(s.t0, s.t1) for s in w.slices]
        # The middle playback lane must seek even under a full-length slice.
        slider = w.timeline
        QTest.mouseClick(slider, Qt.LeftButton, pos=QPoint(slider._value_to_x(700000), slider.height() // 2))
        self.assertGreater(w.position_us, self.origin + 1300000)
        self.assertEqual([(s.t0, s.t1) for s in w.slices], saved)
        self.assert_aligned()
        # Resizing uses the separate slice lane and does not move playback.
        region = slider._slice_regions[-1]; rect = slider._region_rect(region)
        position, duration = w.position_us, w.duration_us
        QTest.mousePress(slider, Qt.LeftButton, pos=QPoint(rect.right(), rect.center().y()))
        QTest.mouseMove(slider, QPoint(rect.right() - 60, rect.center().y()))
        QTest.mouseRelease(slider, Qt.LeftButton, pos=QPoint(rect.right() - 60, rect.center().y()))
        self.assertLess(w.slices[-1].t1, saved[-1][1])
        self.assertEqual((w.position_us, w.duration_us), (position, duration))
        self.assertIsNone(slider._drag_mode)
        w._delete_selected_slice()
        w.edit_history.undo()
        overview = w.recording_overview
        point = QPoint(round(overview.time_to_x(self.origin + 600000)), 25)
        expected = overview.timestamp(point.x())
        QTest.mousePress(overview, Qt.LeftButton, pos=QPoint(point.x() - 30, 25))
        QTest.mouseMove(overview, point)
        QTest.mouseRelease(overview, Qt.LeftButton, pos=point)
        self.assertEqual(w.position_us, expected)
        self.assertEqual(w.duration_us, duration)
        self.assert_aligned()
