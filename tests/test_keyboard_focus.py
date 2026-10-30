"""Changed child/caret metadata must not block the common keyboard route.

All focus/caret values below are synthetic; no live Windows UI is read.
"""
import pathlib
import sys
from types import SimpleNamespace as NS
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import keyboard_access as k
import focus_guard as f

native=k.Windows.__new__(k.Windows)
native.focus=f.Focus(10,11,12)
current=[f.Focus(10,21,22)]
native.current_focus=lambda:current[0]
threads=[]
def info(thread,pointer):
    threads.append(thread)
    value=pointer._obj;value.hwndCaret=21
    value.rcCaret.left=5;value.rcCaret.top=8
    value.rcCaret.right=6;value.rcCaret.bottom=20
    return True
native.u=NS(GetGUIThreadInfo=info)
assert native.anchor()==(21,5,8,6,20)
assert threads==[22]  # Current editing thread, never stale original thread12.
current[0]=None
assert native.anchor() is None and threads==[22]
current[0]=f.Focus(30,31,32)
assert native.anchor() is None and threads==[22]

# Same top-level detection has no dependency on a temporarily missing child.
foreground=[10]
class Call:
    def __call__(self):return foreground[0]
user=NS(GetForegroundWindow=Call())
f.ctypes.WinDLL=lambda *a,**kw:user
assert f.same_foreground(native.focus)
foreground[0]=0
assert not f.same_foreground(native.focus)
foreground[0]=30
assert not f.same_foreground(native.focus)
print('Keyboard focus: current-thread optional caret, same-window identity, missing/different foreground: PASS')
