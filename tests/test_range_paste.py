import sys,pathlib,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import main
pending=[];main.QTimer=types.SimpleNamespace(singleShot=lambda delay,fn:pending.append(fn))
main.focus_guard.unchanged=lambda focus:True
class U:
 def GetForegroundWindow(self):return 7
 def GetAsyncKeyState(self,k):return 0
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()))
class Range:
 def Select(self):state['selected']+=1
 def GetText(self,n):return 'original' if state['valid'] else 'changed'
r=Range();pattern=types.SimpleNamespace()
main.focused_element=lambda:((1,2),None,types.SimpleNamespace(iface_text=pattern))
state={'selected':0,'keys':[],'restore':0,'valid':True,'copy_result':'matched'}
main.range_access.unchanged=lambda *a:state['valid']
class Lease:
 def put(self,t):assert t=='translated'
 def confirm_selection_and_put(self,old,new):assert old=='original' and new=='translated';return state['copy_result']
 def restore(self):state['restore']+=1
main.clipboard_lease.ClipboardLease=Lease
class Context:
 def __enter__(self):pass
 def __exit__(self,*a):pass
class KB:
 def pressed(self,k):return Context()
 def press(self,k):state['keys'].append(k)
 def release(self,k):pass
main.keyboard.Controller=KB
class App:
 busy=True;errors=[];_clipboard_lease=None
 def error(self,e):self.errors.append(e);self.busy=False
 paste_range=main.App.paste_range
 confirm_range_copy=main.App.confirm_range_copy
 finish_range_paste=main.App.finish_range_paste
app=App();snap=types.SimpleNamespace(target=r,text='original',document_mode=False)
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['a','c','a','v'] and state['restore']==1 and not app.errors and not app.busy
state.update(selected=0,keys=[],valid=True,copy_result='mismatch');app.busy=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['a','c'] and app.errors and not app.busy
state.update(selected=0,keys=[],valid=True,copy_result='matched');app.errors=[];app.busy=True;snap.document_mode=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['c','v'] and state['selected']==2 and not app.errors
state.update(selected=0,keys=[],valid=False);app.busy=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
assert not state['keys'] and state['selected']==0 and app.errors
print('real-copy verification, reselection, document scope and stale text: PASS')
