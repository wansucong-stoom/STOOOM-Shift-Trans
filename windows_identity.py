"""Stable Windows taskbar identity shared with installer shortcuts."""
import ctypes
import os


APP_USER_MODEL_ID = 'STOOM.ShiftTranslator'


def set_taskbar_identity():
    """Call before any application window; failure must not prevent startup."""
    if os.name != 'nt':
        return False
    try:
        set_id = ctypes.WinDLL('shell32').SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_long
        return set_id(APP_USER_MODEL_ID) >= 0
    except (AttributeError, OSError):
        return False
