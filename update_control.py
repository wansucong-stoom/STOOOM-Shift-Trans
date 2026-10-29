"""Cooperative installer handoff; never terminates another process.

The app owns the event and polls it on its UI thread. While translation or a
model installation is busy, the app keeps working; Setup may cancel the request
after its bounded wait. Setup owns SETUP_MUTEX for its lifetime so a second app
launch cannot race file replacement.
"""
import ctypes
from ctypes import wintypes

UPDATE_EVENT = r'Local\STOOMShiftTranslator05.UpdateRequested'
SETUP_MUTEX = r'Local\STOOMShiftTranslator05.Setup'
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258

kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.CreateEventW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
kernel.CreateEventW.restype = wintypes.HANDLE
kernel.OpenMutexW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
kernel.OpenMutexW.restype = wintypes.HANDLE
kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
kernel.WaitForSingleObject.restype = wintypes.DWORD
kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
kernel.CloseHandle.restype = wintypes.BOOL


def installation_active(name=SETUP_MUTEX):
    """A setup owned mutex is a launch guard, not an application singleton."""
    handle = kernel.OpenMutexW(SYNCHRONIZE, False, name)
    if handle:
        kernel.CloseHandle(handle)
        return True
    error = ctypes.get_last_error()
    if error == 2:  # ERROR_FILE_NOT_FOUND
        return False
    # An inaccessible named mutex must not be mistaken for a safe install gap.
    raise ctypes.WinError(error)


class UpdateRequest:
    def __init__(self, name=UPDATE_EVENT):
        self.handle = kernel.CreateEventW(None, True, False, name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def requested(self):
        if not self.handle:
            return False
        status = kernel.WaitForSingleObject(self.handle, 0)
        if status == WAIT_OBJECT_0:
            return True
        if status == WAIT_TIMEOUT:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            kernel.CloseHandle(self.handle)
            self.handle = None

