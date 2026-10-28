import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));import main
pending=[];main.QTimer=types.SimpleNamespace(singleShot=lambda delay,fn:pending.append(fn))
class U:
 def GetForegroundWindow(self):return 7
 def GetAsyncKeyState(self,k):return 0
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()))
class Range:
 def Select(self): state['selected']=True
 def CompareEndpoints(self,a,t,b):return 0
 def GetText(self,n):return 'original'
r=Range(); selection=types.SimpleNamespace(Length=1,GetElement=lambda i:r)
pattern=types.SimpleNamespace(GetSelection=lambda:selection)
main.focused_element=lambda:((1,2),None,types.SimpleNamespace(iface_text=pattern))
state={'selected':False,'paste':False,'restore':False,'valid':True}
main.range_access.unchanged=lambda *a:state['valid']
class Lease:
 def put(self,t):assert t=='translated'
 def restore(self):state['restore']=True
main.clipboard_lease.ClipboardLease=Lease
class Context:
 def __enter__(self):pass
 def __exit__(self,*a):pass
class KB:
 def pressed(self,k):return Context()
 def press(self,k):assert k=='v';state['paste']=True
 def release(self,k):pass
main.keyboard.Controller=KB
class App:
 busy=True; errors=[]
 def error(self,e):self.errors.append(e);self.busy=False
 paste_range=main.App.paste_range
 finish_range_paste=main.App.finish_range_paste
app=App();snap=types.SimpleNamespace(target=r,text='original')
app.paste_range(7,(1,2),snap,'translated',20)
while pending:pending.pop(0)()
assert state['selected'] and state['paste'] and state['restore'] and not app.errors and not app.busy
state.update(selected=False,paste=False,valid=False);app.busy=True
app.paste_range(7,(1,2),snap,'translated',20)
assert not state['selected'] and not state['paste'] and app.errors
print('range paste and refusal when source changes: PASS')

