"""Regression checks for release acceptance failures and real video output."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import json
from fractions import Fraction
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from PySide6.QtWidgets import QApplication
from event_studio.viewer import EventBatch
from event_studio.io_utils import commit_pair, CommitRecoveryError
from event_studio.visual_export import export_sequence, find_ffmpeg


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_failed_restore_retains_previous_files_and_recovery_journal(self):
        import shutil

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination, sidecar = root / "events.csv", root / "events.json"
            stage, info = root / "stage.csv", root / "stage.json"
            for path, content in (
                (destination, b"previous data"),
                (sidecar, b"previous metadata"),
                (stage, b"new data"),
                (info, b"new metadata"),
            ):
                path.write_bytes(content)
            replace, copy = os.replace, shutil.copyfile

            def fail_commit(source, target):
                if Path(target) == sidecar:
                    raise OSError("simulated metadata commit failure")
                return replace(source, target)

            def fail_restore(source, target):
                if Path(target) == destination:
                    raise OSError("simulated restore failure")
                return copy(source, target)

            with patch(
                "event_studio.io_utils.os.replace", side_effect=fail_commit
            ), patch("event_studio.io_utils.shutil.copyfile", side_effect=fail_restore):
                with self.assertRaises(CommitRecoveryError) as caught:
                    commit_pair(stage, info, destination, sidecar)
            recovery = caught.exception.recovery_directory
            self.assertEqual(recovery.parent, root.resolve())
            self.assertEqual((recovery / "0.previous").read_bytes(), b"previous data")
            self.assertEqual(
                (recovery / "1.previous").read_bytes(), b"previous metadata"
            )
            self.assertEqual(sidecar.read_bytes(), b"previous metadata")
            journal = json.loads((recovery / "recovery.json").read_text())
            self.assertEqual(
                journal["rollback_failures"][0]["target"], str(destination.resolve())
            )

    @unittest.skipUnless(find_ffmpeg(), "Optional FFmpeg backend is not installed")
    def test_real_mp4_rational_frame_rate_padding_and_decode(self):
        t = np.arange(22, dtype=np.int64) * 10000 + 1000000
        events = EventBatch(
            t,
            np.arange(22, dtype=np.int32) % 8,
            np.arange(22, dtype=np.int32) % 6,
            np.ones(22, dtype=np.int8),
            {},
        )
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "video with spaces"
            manifest = export_sequence(
                output,
                events,
                (6, 8),
                1000000,
                1200201,
                "RAW",
                {},
                fps=Fraction(30000, 1001),
                width=65,
                height=49,
                timestamps=False,
                mp4=True,
            )
            self.assertEqual(manifest["status"], "complete")
            self.assertEqual(len(manifest["frames"]), 7)
            self.assertEqual(manifest["fps"], "30000/1001")
            self.assertAlmostEqual(manifest["video_duration_seconds"], 7 * 1001 / 30000)
            decoded = subprocess.run(
                [
                    find_ffmpeg(),
                    "-hide_banner",
                    "-i",
                    str(output / "visualization.mp4"),
                    "-vf",
                    "showinfo",
                    "-f",
                    "null",
                    "-",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(decoded.returncode, 0, decoded.stderr)
            frames = re.findall(
                r"n:\s*\d+.*?pts_time:([\d.]+).*?s:(\d+x\d+)", decoded.stderr
            )
            self.assertEqual(len(frames), 7, decoded.stderr)
            for index, (timestamp, dimensions) in enumerate(frames):
                self.assertEqual(dimensions, "66x50")
                self.assertAlmostEqual(float(timestamp), index * 1001 / 30000, places=5)


if __name__ == "__main__":
    unittest.main()
