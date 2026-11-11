"""Windows folder bundle: retain only the Qt components this app uses."""
import os
from pathlib import Path

root = Path(SPECPATH).parent
datas = [(str(root / "build" / "release-docs"), "release-docs")]
if os.environ.get("EVENT_STUDIO_BUILD_ASSETS") == "1":
    datas.append((str(root / "event_studio" / "assets"), "event_studio/assets"))

a = Analysis([str(root / "scripts" / "desktop_entry.py")], pathex=[str(root)],
             binaries=[], datas=datas, hiddenimports=["event_studio.convert"], hookspath=[],
             hooksconfig={"matplotlib": {"backends": ["QtAgg"]}}, runtime_hooks=[],
             excludes=["imageio_ffmpeg", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
                       "PySide6.QtDataVisualization", "qtpy.QtDataVisualization",
                       "PySide6.QtMultimediaWidgets", "PySide6.QtPdf", "PySide6.QtVirtualKeyboard"],
             noarchive=False)

qt_libraries = {"qt6core.dll", "qt6gui.dll", "qt6widgets.dll", "qt6network.dll",
                "qt6multimedia.dll", "qt6opengl.dll", "qt6openglwidgets.dll", "qt6svg.dll"}
image_plugins = {"qgif.dll", "qico.dll", "qjpeg.dll", "qsvg.dll"}


def retain(entry):
    name = entry[0].replace("\\", "/").lower()
    filename = name.rsplit("/", 1)[-1]
    if filename.startswith("qt6") and filename.endswith(".dll"):
        return filename in qt_libraries
    if "/plugins/" in name:
        if "/platforminputcontexts/" in name:
            return False  # Qt Virtual Keyboard is unused and GPL/commercial.
        if "/imageformats/" in name:
            return filename in image_plugins
        if "/multimedia/" in name:
            return filename == "windowsmediaplugin.dll"
    if filename.startswith(("avcodec-", "avformat-", "avutil-", "swscale-", "swresample-")):
        return False  # Not used by QSoundEffect/native Windows backend.
    if filename == "opengl32sw.dll":
        return False  # QtAgg and the application render with raster widgets.
    if filename.startswith(("msvcp", "vcruntime", "concrt")) and filename.endswith(".dll"):
        return False  # Users install Microsoft's official x64 runtime separately.
    if name.startswith("pyside6/qml/"):
        return False
    return True


a.binaries = [entry for entry in a.binaries if retain(entry)]
a.datas = [entry for entry in a.datas if retain(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Event-Based-Studio",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Event-Based-Studio")
