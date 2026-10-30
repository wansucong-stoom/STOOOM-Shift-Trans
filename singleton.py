"""Single-instance guard scoped to the current Windows logon session."""
import ctypes
import time
from ctypes import wintypes

NAME = r'Local\STOOMShiftTranslator05.SingleInstance'
SETTINGS_TITLE = 'STOOM Shift Translator — 설정'
ERROR_ALREADY_EXISTS = 183
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel.CloseHandle.restype = wintypes.BOOL

user = ctypes.WinDLL('user32', use_last_error=True)
user.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
user.RegisterWindowMessageW.restype = wintypes.UINT
SHOW_SETTINGS_MESSAGE = user.RegisterWindowMessageW('STOOMShiftTranslator05.ShowSettings.v1')
if not SHOW_SETTINGS_MESSAGE:
    raise ctypes.WinError(ctypes.get_last_error())
user.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
user.FindWindowW.restype = wintypes.HWND
user.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user.PostMessageW.restype = wintypes.BOOL
user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user.GetWindowThreadProcessId.restype = wintypes.DWORD
user.AllowSetForegroundWindow.argtypes = (wintypes.DWORD,)
user.AllowSetForegroundWindow.restype = wintypes.BOOL

def acquire():
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel.CloseHandle(handle)
        return None
    return handle

def acquire_when_available(timeout=15.0, interval=.05):
    """Wait briefly for a retiring instance, without activating or killing it.

    Intended only for an explicitly requested post-update restart. Ordinary
    launches keep acquire()'s immediate duplicate-instance behavior. Each
    unsuccessful acquire closes its temporary handle before the next attempt.
    """
    if interval <= 0:
        raise ValueError('The singleton retry interval must be positive.')
    deadline = time.monotonic() + max(0, timeout)
    while True:
        handle = acquire()
        if handle:
            return handle
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(interval, remaining))


def release(handle):
    if handle:
        kernel.CloseHandle(handle)

def show_existing(*, title=None, timeout=1.5, allow_foreground=True):
    """Ask the existing GUI thread to show its Qt widgets; never show its HWND.

    A native ShowWindow bypasses QWidget's hidden state and can expose an empty
    window. Posting also avoids waiting on another process's GUI thread. The
    bounded lookup covers a second launch while the first is building its UI.
    """
    deadline = time.monotonic() + max(0, timeout)
    while True:
        window = user.FindWindowW(None, title or SETTINGS_TITLE)
        if window:
            if allow_foreground:
                pid = wintypes.DWORD()
                if user.GetWindowThreadProcessId(window, ctypes.byref(pid)) and pid.value:
                    # Grant only this process, never ASFW_ANY. Windows may deny
                    # foreground activation; that must not prevent Qt painting.
                    user.AllowSetForegroundWindow(pid.value)
            return bool(user.PostMessageW(window, SHOW_SETTINGS_MESSAGE, 0, 0))
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(.025, remaining))


def is_show_request(event_type, message):
    """Inspect the MSG pointer supplied by QWidget.nativeEvent on Windows."""
    if bytes(event_type) != b'windows_generic_MSG' or message is None:
        return False
    address = int(message)  # Shiboken VoidPtr can be falsey despite a valid address.
    if not address:
        return False
    native = wintypes.MSG.from_address(address)
    return native.message == SHOW_SETTINGS_MESSAGE and native.wParam == 0 and native.lParam == 0
