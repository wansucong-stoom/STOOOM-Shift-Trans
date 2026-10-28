"""Single-instance guard scoped to the current Windows logon session."""
import ctypes
from ctypes import wintypes

NAME = r'Local\STOOMShiftTranslator05.SingleInstance'
ERROR_ALREADY_EXISTS = 183
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
kernel.CreateMutexW.restype = wintypes.HANDLE
kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel.CloseHandle.restype = wintypes.BOOL

def acquire():
    ctypes.set_last_error(0)
    handle = kernel.CreateMutexW(None, False, NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        kernel.CloseHandle(handle)
        return None
    return handle

def release(handle):
    if handle:
        kernel.CloseHandle(handle)
