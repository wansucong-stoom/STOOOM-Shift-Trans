import sys,pathlib,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import focus_guard as f
state={'fg':10,'focus':11,'thread':12}
class Call:
 def __init__(self,fn):self.fn=fn
 def __call__(self,*a):return self.fn(*a)
class U:
 GetForegroundWindow=Call(lambda:state['fg'])
 GetWindowThreadProcessId=Call(lambda hwnd,pid:state['thread'] if hwnd!=state['fg'] else 99)
 GetGUIThreadInfo=Call(lambda tid,p:(setattr(p._obj,'hwndFocus',state['focus']) or True))
f.ctypes.WinDLL=lambda *a,**k:U()
a=f.capture();assert a==f.Focus(10,11,12);assert f.unchanged(a) and f.same_foreground(a)
state['focus']=13;assert not f.unchanged(a) and f.same_foreground(a)
state['thread']=14;assert f.same_foreground(a)
state['fg']=15;assert not f.same_foreground(a)
state['fg']=10
state['focus']=0
assert f.same_foreground(a)  # No child focus is required in the keyboard route.
try:f.capture();raise AssertionError('missing focus accepted')
except ValueError:pass
print('Strict provider identity and common keyboard foreground identity: child/thread changes allowed, other window refused: PASS')
