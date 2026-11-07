"""Read-only large-recording acceptance, using a normal Qt event loop."""

import argparse
import json
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication
from event_studio.app import MainWindow
from event_studio.viewer import load_events_from_csv, infer_hw
from event_studio.workers import Task
from event_studio.rendering import render_frame
from event_studio.live_preview import LIVE_MODES
from event_studio.project_utils import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    beats = []
    loaded = []
    errors = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: beats.append(time.monotonic()))
    worker = Task(lambda: load_events_from_csv(args.source))
    worker.succeeded.connect(loaded.append)
    worker.failed.connect(errors.append)
    worker.finished.connect(loop.quit)
    started = time.monotonic()
    timer.start()
    worker.start()
    loop.exec()
    timer.stop()
    worker.wait()
    if errors:
        raise RuntimeError(errors[0])
    events = loaded[0]
    hw = infer_hw(events)
    result = {
        "source": str(args.source.resolve()),
        "event_count": len(events.t),
        "load_seconds": round(time.monotonic() - started, 3),
        "loading_max_heartbeat_gap_ms": round(float(max(np.diff(beats))) * 1000, 3),
        "complete": events.metadata.get("complete"),
        "render_ms": {},
    }
    for mode in LIVE_MODES:
        started = time.monotonic()
        image = render_frame(events, hw, int(events.t[0]), 50000, mode, {})
        assert image.shape == (*hw, 3)
        result["render_ms"][mode] = round((time.monotonic() - started) * 1000, 3)
    window = MainWindow()
    restored = MainWindow()
    try:
        window._load_csv_into_app(args.source, args.source.name, prepared_events=events)
        session = window._build_session_dict()
        # Exercise the JSON representation, rather than sharing Python objects.
        restored._restore_session(json.loads(json.dumps(session)), events)
        assert restored._current_window() == window._current_window()
        for name in ("t", "x", "y", "p"):
            np.testing.assert_array_equal(
                getattr(restored.events, name), getattr(events, name)
            )
        result["session_round_trip"] = True
    finally:
        window.close()
        restored.close()
    result["passed"] = bool(result["complete"] and result["session_round_trip"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    save_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
