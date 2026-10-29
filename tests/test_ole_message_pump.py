"""Verify real Windows STA message delivery without using the clipboard."""
import pathlib,queue,sys,threading,uuid
from unittest import mock
import pythoncom,win32api,win32con,win32gui
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_lease

ready=queue.SimpleQueue()
received=threading.Event()
local=threading.local()
original_init=pythoncom.OleInitialize
original_uninit=clipboard_lease._ole_uninitialize
original_queue=queue.Queue
window_message=win32con.WM_APP+41
def wndproc(hwnd,msg,wp,lp):
    if msg==window_message:
        received.set();return 0
    return win32gui.DefWindowProc(hwnd,msg,wp,lp)
def init():
    original_init()
    name='STOOM.PumpTest.'+uuid.uuid4().hex
    wc=win32gui.WNDCLASS();wc.lpszClassName=name;wc.lpfnWndProc=wndproc
    wc.hInstance=win32api.GetModuleHandle(None)
    atom=win32gui.RegisterClass(wc)
    hwnd=win32gui.CreateWindowEx(0,atom,'',0,0,0,0,0,-3,0,wc.hInstance,None)
    local.hwnd=hwnd;local.name=name;local.instance=wc.hInstance
    ready.put(hwnd)
def uninit():
    win32gui.DestroyWindow(local.hwnd)
    win32gui.UnregisterClass(local.name,local.instance)
    original_uninit()
class OldBlockingQueue(original_queue):
    # Recreate the original implementation's queue.get() without a timeout.
    def get(self,block=True,timeout=None):return super().get(block=True,timeout=None)

with mock.patch.object(pythoncom,'OleInitialize',init),mock.patch.object(clipboard_lease,'_ole_uninitialize',uninit):
    with mock.patch.object(clipboard_lease.queue,'Queue',OldBlockingQueue):
        old=clipboard_lease.ClipboardLease()
    hwnd=ready.get(timeout=3)
    win32gui.PostMessage(hwnd,window_message,0,0)
    assert not received.wait(.2),'old blocking wait unexpectedly processed Windows messages'
    old.restore();old._thread.join(3)
    assert not old._thread.is_alive()
    received.clear()

    current=clipboard_lease.ClipboardLease()
    hwnd=ready.get(timeout=3)
    win32gui.PostMessage(hwnd,window_message,0,0)
    assert received.wait(1),'clipboard STA failed to dispatch its own Windows message'
    current.restore();current._thread.join(3)
    assert not current._thread.is_alive()
print('Real Windows STA: old blocking queue fails to dispatch; fixed clipboard worker dispatches; no clipboard used: PASS')
