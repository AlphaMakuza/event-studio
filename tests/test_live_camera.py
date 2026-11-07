import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from dataclasses import replace
from pathlib import Path
from threading import Event
from time import monotonic
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtWidgets import QApplication
from event_studio.acquisition import CameraWorker, EventBuffer
from event_studio.camera_discovery import CameraInfo, DiscoveryResult, discover_cameras
from event_studio.live_preview import (
    PreviewRequest,
    PreviewWorker,
    render_preview,
    LIVE_MODES,
)
from event_studio.live_window import LiveWindow
from event_studio.viewer import load_events_from_csv


def batch(start=0, count=32):
    data = np.zeros(count, dtype=[("t", "i8"), ("x", "i4"), ("y", "i4"), ("p", "i1")])
    data["t"] = start + np.arange(count)
    data["x"] = np.arange(count) % 8
    data["y"] = np.arange(count) // 8
    data["p"] = np.arange(count) % 2
    return data


class FakeCamera:
    def get_size(self):
        return (32, 32)

    def __iter__(self):
        for index in range(100000):
            QThread.msleep(5)
            yield batch(index * 10000)


class LiveCameraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def spin(self, predicate, timeout=4000):
        if predicate():
            return
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(5)
        deadline = monotonic() + timeout / 1000

        def check():
            if predicate() or monotonic() > deadline:
                loop.quit()

        timer.timeout.connect(check)
        timer.start()
        loop.exec()
        timer.stop()
        self.assertTrue(predicate(), "Timed out waiting for Qt operation")

    def close_window(self, window):
        window.close()
        self.spin(lambda: not window.is_busy())
        self.app.processEvents()

    def worker_factory(self, buffer, serial="", parent=None):
        return CameraWorker(buffer, serial, iterator_factory=FakeCamera, parent=parent)

    def test_discovery_lists_local_devices_without_opening_and_keeps_full_ids(self):
        class Discovery:
            @staticmethod
            def list_local():
                return ["Acme:USB:002", "Acme:USB:001", "Acme:USB:001"]

            @staticmethod
            def open(serial):
                raise AssertionError("Discovery must not open cameras")

        result = discover_cameras(Discovery)
        self.assertEqual(result.state, "ready")
        self.assertEqual(
            [c.serial for c in result.cameras], ["Acme:USB:001", "Acme:USB:002"]
        )
        self.assertIn("001", result.cameras[0].label)

    def test_missing_sdk_is_not_reported_as_no_connected_cameras(self):
        with patch("event_studio.camera_discovery.sdk_available", return_value=False):
            result = discover_cameras()
        self.assertEqual(result.state, "unavailable")
        self.assertIn("SDK", result.detail)
        window = LiveWindow(None)
        window.apply_discovery(result)
        self.assertEqual(
            window.camera_combo.currentText(), "Camera support unavailable"
        )
        self.assertFalse(window.start.isEnabled())
        self.close_window(window)

    def test_scan_failure_is_distinct_from_empty_success(self):
        class Broken:
            @staticmethod
            def list_local():
                raise RuntimeError("Driver could not load")

        self.assertEqual(discover_cameras(Broken).state, "error")
        window = LiveWindow(None)
        window.apply_discovery(DiscoveryResult("ready"))
        self.assertEqual(window.camera_combo.currentText(), "No event cameras detected")
        self.assertIn("No event cameras", window.status.text())
        self.assertFalse(window.start.isEnabled())
        self.close_window(window)

    def test_empty_then_hotplug_autostarts_without_a_serial_entry(self):
        window = LiveWindow(None)
        with patch(
            "event_studio.live_window.CameraWorker", side_effect=self.worker_factory
        ):
            window.apply_discovery(DiscoveryResult("ready"))
            window.apply_discovery(
                DiscoveryResult("ready", (CameraInfo("one", "Camera One"),))
            )
            self.spin(
                lambda: window.buffer is not None
                and window.buffer.received > 0
                and window.hw is not None
            )
            self.assertEqual(window._active_serial, "one")
            self.assertFalse(window.start.isEnabled())
            self.assertTrue(window.stop.isEnabled())
            window.stop_camera()
            self.spin(lambda: window.worker is None)
            window.apply_discovery(
                DiscoveryResult("ready", (CameraInfo("one", "Camera One"),))
            )
            self.assertIsNone(
                window.worker, "Manual stop must not immediately reconnect"
            )
            self.close_window(window)

    def test_dropdown_switches_exact_device_and_preserves_selection_on_refresh(self):
        window = LiveWindow(None)
        cameras = (CameraInfo("one", "One"), CameraInfo("two", "Two"))
        with patch(
            "event_studio.live_window.CameraWorker", side_effect=self.worker_factory
        ):
            window.apply_discovery(DiscoveryResult("ready", cameras))
            self.spin(lambda: window.hw is not None)
            previous_epoch = window._epoch
            window.camera_combo.setCurrentIndex(1)
            self.spin(lambda: window._active_serial == "two" and window.hw is not None)
            self.assertGreater(window._epoch, previous_epoch)
            window.apply_discovery(DiscoveryResult("ready", cameras))
            self.assertEqual(window.camera_combo.currentData(), "two")
            self.close_window(window)

    def test_failed_connection_does_not_retry_forever(self):
        class BadCamera:
            def get_size(self):
                raise RuntimeError("Camera busy")

        window = LiveWindow(None)

        def failed(buffer, serial, parent):
            return CameraWorker(
                buffer, serial, iterator_factory=BadCamera, parent=parent
            )

        with patch(
            "event_studio.live_window.CameraWorker", side_effect=failed
        ) as factory:
            result = DiscoveryResult("ready", (CameraInfo("busy", "Busy camera"),))
            window.apply_discovery(result)
            self.spin(lambda: window.worker is None)
            window.apply_discovery(result)
            self.app.processEvents()
            self.assertEqual(factory.call_count, 1)
            self.assertIn("busy", window.status.text().lower())
            self.close_window(window)

    def test_all_live_views_render_with_raw_reference_and_no_source_mutation(self):
        buffer = EventBuffer(10000)
        data = batch(1000, 64)
        original = data.copy()
        buffer.push(data)
        for mode in LIVE_MODES:
            request = PreviewRequest(
                1,
                2,
                buffer,
                (32, 32),
                mode,
                10000,
                {"polarity": "pos", "grid": 8},
                compare=True,
                live=False,
            )
            result = render_preview(request)
            self.assertEqual(result["image"].shape, (32, 32, 3))
            self.assertEqual(result["comparison"].shape, (32, 32, 3))
            self.assertEqual(result["events"], 32)
        np.testing.assert_array_equal(data, original)
        self.assertEqual(buffer.received, 64)

    def test_quiet_scene_events_expire_using_presentation_clock_only(self):
        buffer = EventBuffer(1000)
        buffer.push(batch(1000, 32))
        request = PreviewRequest(1, 0, buffer, (32, 32), "RAW", 10000, {}, live=True)
        result = render_preview(request, now=buffer.last_delivery + 0.1)
        self.assertEqual(result["events"], 0)
        self.assertEqual(int(result["image"].sum()), 0)
        self.assertEqual(result["latest_event_us"], 1031)
        self.assertEqual(buffer.snapshot((32, 32)).t.tolist(), list(range(1000, 1032)))

    def test_history_snapshot_is_time_bounded_and_reports_evictions(self):
        buffer = EventBuffer(16)
        buffer.push(batch(0, 32))
        buffer.push(batch(1000, 8))
        snapshot = buffer.snapshot((32, 32), lookback_us=4)
        self.assertEqual(snapshot.t.tolist(), [1004, 1005, 1006, 1007])
        self.assertEqual(snapshot.metadata["display_buffer_evicted_events"], 24)
        self.assertEqual(snapshot.metadata["buffer_start_us"], 24)

    def test_stale_preview_from_old_camera_or_controls_is_discarded(self):
        window = LiveWindow(None)
        window.apply_preview({"epoch": window._epoch - 1, "revision": window._revision})
        window.apply_preview({"epoch": window._epoch, "revision": window._revision - 1})
        self.assertIsNone(window._last_result)
        self.close_window(window)

    def test_preview_worker_keeps_only_latest_pending_request(self):
        entered = Event()
        release = Event()
        seen = []
        worker = PreviewWorker()
        request = PreviewRequest(1, 1, EventBuffer(100), (32, 32), "RAW", 1000, {})

        def renderer(req):
            if req.revision == 1:
                entered.set()
                release.wait(2)
            return {"revision": req.revision}

        with patch("event_studio.live_preview.render_preview", side_effect=renderer):
            worker.rendered.connect(lambda result: seen.append(result["revision"]))
            worker.start()
            worker.submit(request)
            self.spin(entered.is_set)
            worker.submit(replace(request, revision=2))
            worker.submit(replace(request, revision=3))
            release.set()
            self.spin(lambda: 3 in seen)
            worker.stop()
            self.assertTrue(worker.wait(2000))
        self.assertEqual(seen, [1, 3])
        self.assertGreaterEqual(worker.coalesced, 1)

    def test_recording_can_start_stop_without_stopping_camera(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.csv"
            buffer = EventBuffer(100)
            worker = None

            class Iterator:
                def get_size(self):
                    return (32, 32)

                def __iter__(self):
                    worker.request_recording(path)
                    yield batch(1000, 16)
                    worker.request_recording()
                    yield batch(2000, 16)
                    yield batch(3000, 16)

            worker = CameraWorker(buffer, "exact-device", iterator_factory=Iterator)
            errors = []
            worker.recording_failed.connect(errors.append)
            loop = QEventLoop()
            worker.finished.connect(loop.quit)
            worker.start()
            loop.exec()
            worker.wait()
            self.assertEqual(errors, [])
            self.assertEqual(buffer.received, 48)
            recorded = load_events_from_csv(path)
            self.assertEqual(recorded.t.tolist(), list(range(1000, 1016)))
            self.assertEqual(recorded.metadata["acquisition"]["serial"], "exact-device")
            self.assertFalse(recorded.metadata["acquisition"]["timestamps_rebased"])

    def test_bad_recording_target_does_not_stop_preview_or_overwrite_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "existing.csv"
            path.write_text("existing data")

            class Iterator:
                def get_size(self):
                    return (32, 32)

                def __iter__(self):
                    yield batch(1000)

            buffer = EventBuffer(100)
            worker = CameraWorker(buffer, record_path=path, iterator_factory=Iterator)
            errors = []
            worker.recording_failed.connect(errors.append)
            loop = QEventLoop()
            worker.finished.connect(loop.quit)
            worker.start()
            loop.exec()
            worker.wait()
            self.assertTrue(errors)
            self.assertEqual(buffer.received, 32)
            self.assertEqual(path.read_text(), "existing data")

    def test_closing_while_discovery_runs_waits_for_thread(self):
        entered = Event()
        release = Event()
        window = LiveWindow(None)

        def discovery():
            entered.set()
            release.wait(2)
            return DiscoveryResult("ready")

        with patch(
            "event_studio.camera_discovery.discover_cameras", side_effect=discovery
        ):
            window.scan_cameras()
            self.spin(entered.is_set)
            window.close()
            self.assertTrue(window._closing)
            self.assertIsNotNone(window.discovery_worker)
            release.set()
            self.spin(lambda: not window.is_busy())
        self.assertFalse(window.isVisible())

    def test_no_camera_state_invalidates_previous_preview(self):
        window = LiveWindow(None)
        window.hw = (32, 32)
        window.buffer = EventBuffer(100)
        window.buffer.push(batch(1000))
        previous_epoch = window._epoch
        window.apply_discovery(DiscoveryResult("ready"))
        self.assertGreater(window._epoch, previous_epoch)
        self.assertIsNone(window.buffer)
        self.assertIsNone(window.hw)
        window.apply_preview({"epoch": previous_epoch, "revision": window._revision})
        self.assertIsNone(window._last_result)
        self.close_window(window)

    def test_device_disappearing_during_record_dialog_does_not_record_wrong_source(
        self,
    ):
        window = LiveWindow(None)
        camera = MagicMock()
        window.worker = camera

        def choose(*args):
            window.worker = None
            return "/unused/capture.csv", ""

        with patch(
            "event_studio.live_window.QFileDialog.getSaveFileName", side_effect=choose
        ):
            window.choose_recording()
        camera.request_recording.assert_not_called()
        self.assertIn("Camera changed or stopped", window.status.text())
        self.close_window(window)

    def test_browser_and_project_share_independent_live_window(self):
        from event_studio.app import MainWindow
        from event_studio.project_browser import ProjectBrowser

        with tempfile.TemporaryDirectory() as directory, patch(
            "event_studio.camera_discovery.discover_cameras",
            return_value=DiscoveryResult("ready"),
        ):
            browser = ProjectBrowser(Path(directory), lambda path: None)
            project = MainWindow()
            browser._open_live_camera()
            window = browser._live_window
            self.spin(lambda: window.discovery_worker is None)
            project._open_live_window()
            self.assertIs(project._live_window, window)
            self.assertIsNone(window.parent())
            project.close()
            self.assertTrue(window.isVisible())
            self.close_window(window)
            browser.close()
            delattr(self.app, "_event_studio_live_window")

    def test_runtime_view_controls_render_through_worker(self):
        window = LiveWindow(None)
        window.buffer = EventBuffer(1000)
        window.hw = (32, 32)
        window.buffer.push(batch(1000, 64))
        for mode in LIVE_MODES:
            window.mode_combo.setCurrentIndex(window.mode_combo.findData(mode))
            window.compare_check.setChecked(True)
            window.refresh()
            self.spin(
                lambda: window._last_result is not None
                and window._last_result["revision"] == window._revision
            )
            self.assertEqual(window._last_result["mode"], mode)
            self.assertIsNotNone(window._last_result["comparison"])
        self.close_window(window)
