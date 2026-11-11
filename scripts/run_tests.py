"""Run each test module in a fresh process and retain native crash diagnostics.

python -m scripts.run_tests
python -m scripts.run_tests tests.test_appearance tests.test_gui_launch --repeat 2
"""
import argparse
from datetime import datetime, timezone
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import tempfile
import sys
import time
import traceback
import unittest

ROOT = Path(__file__).resolve().parents[1]


def configure_diagnostics():
    if sys.platform == "win32":
        import ctypes
        # Test processes only: record faults instead of opening a modal dialog.
        # This does not handle exceptions, change their exit codes, or affect
        # the normal application process.
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)
    faulthandler.enable(all_threads=True)


def run_worker(module):
    configure_diagnostics()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    # Save-on-close must never publish test fixtures into the user's library.
    storage = ROOT / "artifacts" / "test-storage"
    storage.mkdir(parents=True, exist_ok=True)
    os.environ["EVENT_STUDIO_HOME"] = tempfile.mkdtemp(prefix="worker-", dir=storage)
    os.environ["EVENT_STUDIO_TEST_STORAGE"] = "1"
    callback_errors = []

    def exception_hook(kind, value, tb):
        callback_errors.append(str(value))
        traceback.print_exception(kind, value, tb)

    sys.excepthook = exception_hook
    suite = unittest.defaultTestLoader.loadTestsFromName(module)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if callback_errors:
        print(f"FAILED: {len(callback_errors)} unhandled Qt/Python callbacks", file=sys.stderr)
    return 0 if result.wasSuccessful() and not callback_errors else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", nargs="*")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--worker", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return run_worker(args.worker)
    if args.repeat < 1 or args.timeout <= 0:
        parser.error("repeat and timeout must be positive")
    configure_diagnostics()
    modules = args.modules or [f"tests.{path.stem}" for path in sorted((ROOT / "tests").glob("test_*.py"))]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = ROOT / "artifacts" / "test-runs" / stamp
    output.mkdir(parents=True)
    results = []
    for repetition in range(1, args.repeat + 1):
        for index, module in enumerate(modules, 1):
            start = time.monotonic()
            log = output / f"{repetition}-{index}-{module.rsplit('.', 1)[-1]}.log"
            timeout = False
            with log.open("w", encoding="utf-8") as stream:
                try:
                    process = subprocess.run(
                        [sys.executable, "-X", "faulthandler", "-u", "-m", "scripts.run_tests", "--worker", module],
                        cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, timeout=args.timeout,
                    )
                    code = process.returncode
                except subprocess.TimeoutExpired:
                    timeout = True
                    code = None
                    stream.write(f"\nFAILED: exceeded {args.timeout} seconds\n")
            text = log.read_text(encoding="utf-8", errors="replace")
            native_error = any(marker in text for marker in (
                "Windows fatal exception", "Fatal Python error", "Error calling Python override",
            ))
            passed = code == 0 and not timeout and not native_error
            result = {"module": module, "repeat": repetition, "passed": passed,
                      "returncode": code, "timeout": timeout, "native_error": native_error,
                      "seconds": round(time.monotonic() - start, 3), "log": log.name}
            results.append(result)
            print(f"{'PASS' if passed else 'FAIL'} {module} ({result['seconds']:.1f}s, exit {code})", flush=True)
            if not passed:
                print(text, flush=True)
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Logs: {output}", flush=True)
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
