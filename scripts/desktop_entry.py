"""Windowed executable entry point with persistent crash diagnostics."""
import logging
from logging.handlers import RotatingFileHandler
import sys
import multiprocessing

from event_studio.paths import storage_root


def main():
    multiprocessing.freeze_support()
    log_dir = storage_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "application.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler])

    def report(kind, value, tb):
        logging.critical("Unhandled application error", exc_info=(kind, value, tb))
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance():
            QMessageBox.critical(None, "Event-Based Studio error", f"An unexpected error occurred.\nDetails: {log_dir / 'application.log'}")

    sys.excepthook = report
    try:
        if "--smoke-test" in sys.argv:
            smoke_test()
            return
        from event_studio.app import main as run
        run()
    except Exception:
        report(*sys.exc_info())
        raise SystemExit(1)


def smoke_test():
    """Exercise the packaged GUI and plotting backend without a persistent session."""
    import json
    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from event_studio.app import MainWindow
    from event_studio.project_browser import ProjectBrowser
    from event_studio.theme import configure_application, appearance_controller
    from event_studio.viewer import load_events_from_csv
    from event_studio.project_utils import create_project_dir
    from event_studio.project_transfer import export_project, import_project

    root = storage_root()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(root / "settings"))
    app = QApplication([])
    configure_application(app)
    browser = ProjectBrowser(projects_root=root / "projects", open_project_callback=lambda _: None)
    editor = MainWindow()
    project = create_project_dir(root / "projects", "Release check")
    source = root / "sample events.csv"
    source.write_text("t,x,y,p\n1000,0,0,1\n1001,1,1,0\n1002,2,2,1\n", encoding="utf-8")
    editor.current_project_dir = project
    editor.project_name = project.name
    editor._load_csv_into_app(source, "release check", prepared_events=load_events_from_csv(source))
    editor.annotations = [{"name": "Release check", "text": "Persist this note", "t0": 1000, "t1": 1002}]

    def finish():
        try:
            assert not browser.grab().isNull(), "Browser did not render"
            assert not editor.grab().isNull(), "Editor did not render"
            import numpy as np
            np.testing.assert_allclose(np.fft.rfft([1.0, 0.0]), [1.0, 1.0])
            smoke_native_import(root)
            for mode in ("classic", "glass"):
                appearance_controller().set_mode(mode, persist=False)
                assert not editor.grab().isNull(), f"Failed to render {mode} appearance"
            assert editor.close(), "Save on close failed"
            stored = json.loads((project / "session.json").read_text(encoding="utf-8"))
            assert stored["annotations"][0]["text"] == "Persist this note"
            session = editor._build_session_dict()
            export_project(root / "transfer.ebs", session, project)
            imported = import_project(root / "transfer.ebs", root / "imported")
            assert (imported / "recording" / "events.csv").read_bytes() == source.read_bytes()
            assert editor.grab().save(str(root / "export.png")), "PNG write failed"
            checks = ["startup overlay/audio completion or fallback", "browser", "editor", "both appearances", "NumPy FFT runtime", "CSV load", "native DAT/HDF5/ECF import without external processes", "save on close", "ebs roundtrip", "PNG write"]
            (root / "smoke-test.json").write_text(json.dumps({"passed": True, "frozen": bool(getattr(sys, "frozen", False)), "checks": checks}), encoding="utf-8")
            app.exit(0)
        except Exception:
            logging.exception("Packaged smoke test failed")
            app.exit(1)

    def ready():
        browser.show()
        editor.show()
        QTimer.singleShot(1500, finish)

    from event_studio.boot import show_boot
    overlay = show_boot(app, on_done=ready, on_error=lambda exc: app.exit(1))
    QTimer.singleShot(30000, lambda: app.exit(1))
    raise SystemExit(app.exec())


def smoke_native_import(root):
    """Verify the bundled HDF5 library and all three supported extensions."""
    import os
    import struct
    import subprocess
    import h5py
    import numpy as np
    from event_studio.recording_import import load_recording
    dat = root / 'portable sample (1).dat'
    dat.write_bytes(b'% Version 2\n% Width 16\n% Height 8\n\x00\x08' +
                    b''.join(struct.pack('<II', t, x | (3 << 14) | (p << 28))
                             for t, x, p in [(100,5,0),(100,6,1),(115,7,0),(116,8,1)]))
    dtype = np.dtype({'names':['x','y','p','t'], 'formats':['<u2','<u2','<i2','<i8'],
                      'offsets':[0,2,4,8], 'itemsize':16})
    hdf5 = root / 'portable sample.hdf5'
    with h5py.File(hdf5, 'w') as h:
        h.attrs['geometry'] = '16x8'
        h.create_dataset('CD/events', data=np.array([(5,3,0,100),(6,3,1,100),(7,3,0,115),(8,3,1,116)], dtype=dtype), compression='gzip')
    ecf = root / 'portable ECF sample.h5'
    with h5py.File(ecf, 'w') as h:
        h.attrs['geometry'] = '16x8'
        d = h.create_dataset('CD/events', (4,), dtype=dtype, chunks=(4,), compression=36559, allow_unknown_filter=True)
        d.id.write_direct_chunk((0,), struct.pack('<IQ', 18, 100) + bytes([2,255,1,17]) + struct.pack('<III',3148301,3158030,12305), filter_mask=0)
    def forbidden(*args, **kwargs):
        raise AssertionError('Portable file import attempted an external process.')
    previous = subprocess.run, subprocess.Popen
    plugin_path = os.environ.get('HDF5_PLUGIN_PATH')
    try:
        os.environ['HDF5_PLUGIN_PATH'] = str(root / 'no-external-hdf5-plugins')
        subprocess.run = subprocess.Popen = forbidden
        for source in (dat, hdf5, ecf):
            _, events = load_recording(source, root / 'portable-imports')
            for name, expected in [('t',[100,100,115,116]),('x',[5,6,7,8]),('y',[3,3,3,3]),('p',[0,1,0,1])]:
                np.testing.assert_array_equal(getattr(events, name), expected)
            assert events.metadata['resolution'] == [16,8]
    finally:
        subprocess.run, subprocess.Popen = previous
        if plugin_path is None:
            os.environ.pop('HDF5_PLUGIN_PATH', None)
        else:
            os.environ['HDF5_PLUGIN_PATH'] = plugin_path


if __name__ == "__main__":
    main()
