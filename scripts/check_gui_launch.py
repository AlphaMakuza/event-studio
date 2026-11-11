"""Check native paint callbacks and clean process exit, optionally with real boot.

python -m scripts.check_gui_launch --native --boot
"""
import argparse
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--boot", action="store_true")
    args = parser.parse_args()
    # Only this diagnostic process disables Windows' modal crash dialog.
    # Faults still produce a failing exit code and faulthandler output.
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0002)
    faulthandler.enable()
    os.environ["QT_QPA_PLATFORM"] = "windows" if args.native else "offscreen"
    from PySide6.QtCore import QEvent, QSettings, QTimer
    from PySide6.QtWidgets import QApplication
    from event_studio.app import MainWindow
    from event_studio.project_browser import ProjectBrowser
    from event_studio.theme import appearance_controller, configure_application

    errors = []
    windows = []

    def exception_hook(kind, value, tb):
        errors.append(str(value))
        traceback.print_exception(kind, value, tb)
        QApplication.instance().exit(1)

    sys.excepthook = exception_hook
    with tempfile.TemporaryDirectory() as directory:
        def exercise(app, browser):
            browser.settings = QSettings(str(Path(directory) / "browser.ini"), QSettings.IniFormat)
            controller = appearance_controller()
            controller.settings = QSettings(str(Path(directory) / "appearance.ini"), QSettings.IniFormat)
            editor = MainWindow()
            editor.resize(1400, 900)
            windows.extend([browser, editor])

            def steps():
                for _ in range(3):
                    for mode in ("glass", "classic"):
                        controller.set_mode(mode, persist=False)
                        browser.show()
                        for index in range(browser.view_combo.count()):
                            browser.view_combo.setCurrentIndex(index)
                            browser.view_combo.showPopup()
                            yield
                            browser.view_combo.hidePopup()
                            assert not browser.view_combo.grab().isNull()
                            yield
                        editor.show()
                        editor.play_btn.setText("Pause")
                        editor.play_btn.setText("Play")
                        editor.studio_header.appearance.showPopup()
                        yield
                        editor.studio_header.appearance.hidePopup()
                        menu = editor._studio_menu_bar.actions()[0].menu()
                        menu.popup(editor.mapToGlobal(editor.rect().center()))
                        yield
                        menu.hide()
                        assert not editor.grab().isNull()
                        editor.hide()
                        yield
                print("PASS: browser/editor, all view icons, popups, playback icons, and live themes", flush=True)

            iterator = steps()

            def advance():
                try:
                    next(iterator)
                except StopIteration:
                    for window in windows:
                        window.close()
                        window.deleteLater()
                    app.sendPostedEvents(None, QEvent.DeferredDelete)
                    app.exit(1 if errors else 0)
                    return
                QTimer.singleShot(20, advance)

            QTimer.singleShot(50, advance)

        def watchdog():
            errors.append("Startup/GUI probe timed out")
            print(errors[-1], file=sys.stderr, flush=True)
            QApplication.instance().exit(1)

        if args.boot:
            import event_studio.app as studio
            original_boot = studio._try_show_boot

            def boot(app, on_done=None, **kwargs):
                def ready():
                    on_done()
                    browser = next(w for w in app.topLevelWidgets() if isinstance(w, ProjectBrowser))
                    print("PASS: real startup reached project browser", flush=True)
                    exercise(app, browser)
                QTimer.singleShot(20000, watchdog)
                original_boot(app, on_done=ready, **kwargs)

            studio._try_show_boot = boot
            try:
                studio.main()
            except SystemExit as result:
                code = result.code
        else:
            app = QApplication([])
            configure_application(app)
            settings = QSettings(str(Path(directory) / "browser.ini"), QSettings.IniFormat)
            browser = ProjectBrowser(Path(directory) / "projects", lambda _: None, settings=settings)
            QTimer.singleShot(15000, watchdog)
            exercise(app, browser)
            code = app.exec()
    print(f"GUI event loop exited with code {code}", flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
