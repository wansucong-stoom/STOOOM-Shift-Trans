"""Real, isolated Windows mutex checks for post-update singleton handoff.

Only this test's unique mutex is accessed. No production app, GUI, installer,
document, clipboard or global input hook is used.
"""
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import singleton as s


s.NAME=r'Local\STOOM.Test.Restart.'+uuid.uuid4().hex
source=str(Path(__file__).resolve().parents[1])
script='''
import sys
sys.path.insert(0,sys.argv[1])
import singleton as s
s.NAME=sys.argv[2]
handle=s.acquire()
assert handle
print('held',flush=True)
sys.stdin.readline()
s.release(handle)
print('released',flush=True)
'''
child=subprocess.Popen([sys.executable,'-c',script,source,s.NAME],
                       stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE,text=True)
try:
    assert child.stdout.readline().strip()=='held'
    assert s.acquire() is None  # Ordinary duplicate launch still returns now.
    start=time.monotonic()
    assert s.acquire_when_available(timeout=.12,interval=.02) is None
    elapsed=time.monotonic()-start
    assert .10 <= elapsed < 2.0,elapsed

    # Repeated failed attempts must close their temporary CreateMutex handles.
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=wintypes.HANDLE
    kernel.GetProcessHandleCount.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
    kernel.GetProcessHandleCount.restype=wintypes.BOOL
    def handles():
        result=wintypes.DWORD()
        assert kernel.GetProcessHandleCount(kernel.GetCurrentProcess(),ctypes.byref(result))
        return result.value
    before=handles()
    for _ in range(200):assert s.acquire_when_available(timeout=0) is None
    assert handles()==before,'timed-out retries leaked mutex handles'

    # A separate process releases naturally; the new instance must retain its
    # acquired handle rather than merely observe a transient available state.
    def retire():
        time.sleep(.15)
        child.stdin.write('exit\n');child.stdin.flush()
    retiring=threading.Thread(target=retire);retiring.start()
    start=time.monotonic();owned=s.acquire_when_available(timeout=3,interval=.02)
    try:
        assert owned and time.monotonic()-start >= .10
        assert s.acquire() is None
        retiring.join(timeout=2);assert not retiring.is_alive()
        child.wait(timeout=3);assert child.returncode==0,child.stderr.read()
    finally:s.release(owned)
finally:
    if child.poll() is None:
        child.stdin.write('exit\n');child.stdin.flush()
        child.wait(timeout=3)
    child.stdin.close();child.stdout.close();child.stderr.close()

# Concurrent restart attempts compete atomically at CreateMutex. The winner
# keeps its handle until every other attempt has timed out.
barrier=threading.Barrier(4)
results=[];errors=[]
def compete():
    try:
        barrier.wait(timeout=3)
        results.append(s.acquire_when_available(timeout=.15,interval=.01))
    except BaseException as error:errors.append(error)
threads=[threading.Thread(target=compete) for _ in range(3)]
for thread in threads:thread.start()
barrier.wait(timeout=3)
for thread in threads:thread.join(timeout=3)
try:
    assert not errors,errors
    assert all(not thread.is_alive() for thread in threads)
    assert len(results)==3 and sum(bool(handle) for handle in results)==1,results
finally:
    for handle in results:s.release(handle)

# API failures remain failures; they must not become an endless duplicate
# wait or an activation request to an old application.
failure=OSError('synthetic mutex failure')
with patch.object(s,'acquire',side_effect=failure),patch.object(s.time,'sleep',side_effect=AssertionError('slept after failure')):
    try:s.acquire_when_available()
    except OSError as error:assert error is failure
    else:raise AssertionError('mutex failure was swallowed')

handle=s.acquire_when_available(timeout=0)
assert handle
s.release(handle)
print('post-update mutex handoff: separate-process release, bounded timeout, no handle leak, one concurrent winner and error propagation: PASS')
