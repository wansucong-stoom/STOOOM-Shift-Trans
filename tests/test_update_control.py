"""Real Windows IPC test using unique names; no running STOOM instance touched."""
import ctypes
import pathlib
import subprocess
import sys
import uuid
from ctypes import wintypes

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import update_control

event_name = 'Local\\STOOM.Test.Update.' + uuid.uuid4().hex
mutex_name = 'Local\\STOOM.Test.Setup.' + uuid.uuid4().hex
request = update_control.UpdateRequest(event_name)
assert not request.requested()
script = '''
import ctypes,sys
from ctypes import wintypes
k=ctypes.WinDLL('kernel32',use_last_error=True)
k.OpenEventW.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR)
k.OpenEventW.restype=wintypes.HANDLE
k.SetEvent.argtypes=(wintypes.HANDLE,)
k.ResetEvent.argtypes=(wintypes.HANDLE,)
k.CloseHandle.argtypes=(wintypes.HANDLE,)
h=k.OpenEventW(2,False,sys.argv[1])
assert h,ctypes.get_last_error()
assert (k.SetEvent if sys.argv[2]=='set' else k.ResetEvent)(h)
k.CloseHandle(h)
'''
subprocess.run([sys.executable, '-c', script, event_name, 'set'], check=True)
assert request.requested(), 'request from separate setup process was not observed'
assert request.requested(), 'poll must not consume a pending busy-app request'
subprocess.run([sys.executable, '-c', script, event_name, 'reset'], check=True)
assert not request.requested(), 'cancelled setup must not cause a delayed app exit'
request.close()
request.close()
assert not request.requested()

assert not update_control.installation_active(mutex_name)
k = ctypes.WinDLL('kernel32', use_last_error=True)
k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
k.CreateMutexW.restype = wintypes.HANDLE
k.CloseHandle.argtypes = (wintypes.HANDLE,)
handle = k.CreateMutexW(None, False, mutex_name)
assert handle
try:
    assert update_control.installation_active(mutex_name)
finally:
    k.CloseHandle(handle)
assert not update_control.installation_active(mutex_name)
print('Cooperative update event, cancellation and install launch guard: PASS')
