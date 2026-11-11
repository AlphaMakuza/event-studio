"""Best-effort Windows 11 acrylic; other platforms keep the painted glass."""
import sys


def apply_backdrop(window, glass):
    if sys.platform != "win32":
        return False
    from PySide6.QtWidgets import QApplication
    if QApplication.platformName() != "windows" or not window.isVisible():
        return False
    if sys.getwindowsversion().build < 22621:
        return False
    import ctypes
    from ctypes import wintypes

    class Margins(ctypes.Structure):
        _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

    try:
        dwm = ctypes.WinDLL("dwmapi")
        attribute = dwm.DwmSetWindowAttribute
        attribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        attribute.restype = ctypes.c_long
        extend = dwm.DwmExtendFrameIntoClientArea
        extend.argtypes = [wintypes.HWND, ctypes.POINTER(Margins)]
        extend.restype = ctypes.c_long
        handle = wintypes.HWND(int(window.winId()))
        # DWMWCP_DONOTROUND keeps the outer window square too.
        corners = ctypes.c_int(1)
        attribute(handle, 33, ctypes.byref(corners), ctypes.sizeof(corners))
        # DWMSBT_TRANSIENTWINDOW requests the desktop acrylic material.
        backdrop = ctypes.c_int(3 if glass else 1)
        result = attribute(handle, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
        margins = Margins(*([-1] * 4 if glass else [0] * 4))
        return result == 0 and extend(handle, ctypes.byref(margins)) == 0
    except (OSError, AttributeError):
        return False
