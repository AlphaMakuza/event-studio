"""A native Qt fault must fail a subprocess test, not escape widget assertions."""
from pathlib import Path
import subprocess
import sys
import unittest


class GuiLaunchTests(unittest.TestCase):
    def test_late_appearance_initialization_after_splash_cleanup(self):
        # This precise order used to corrupt the native heap during gc.collect:
        # destroy a splash before the first browser initializes appearance.
        # Run fresh so another test cannot initialize the controller first.
        code = """
from scripts.run_tests import configure_diagnostics
configure_diagnostics()
import sys
import unittest
from tests.test_homepage import HomepageTests
suite = unittest.TestSuite(HomepageTests(name) for name in (
    'test_audio_fallback_still_reveals_homepage',
    'test_project_deletion_rejects_outside_folder',
))
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-u", "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=20,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("Ran 2 tests", output)
        self.assertNotIn("Windows fatal exception", output)

    def test_render_popups_switch_themes_and_exit_cleanly(self):
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-m", "scripts.check_gui_launch"],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=25,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertIn("PASS: browser/editor", output)
        self.assertIn("GUI event loop exited with code 0", output)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("Error calling Python override", output)


if __name__ == "__main__":
    unittest.main()
