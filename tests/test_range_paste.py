import sys,pathlib,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import main
pending=[];main.QTimer=types.SimpleNamespace(singleShot=lambda delay,fn:pending.append(fn))
main.focus_guard.unchanged=lambda focus:True
class U:
 def GetForegroundWindow(self):return 7
 def GetAsyncKeyState(self,k):return 0
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()))
class Range:
 def __init__(self,stale=False):self.stale=stale
 def Select(self):state['selected']+=1
 def GetText(self,n):
  if self.stale:raise RuntimeError('saved live range is stale')
  return state['source']
class OldRange(Range):
 def Select(self):raise AssertionError('must select fresh range, not saved live range')
r=OldRange(True);pattern=types.SimpleNamespace()
main.focused_element=lambda:((1,2),None,types.SimpleNamespace(iface_text=pattern))
state={'selected':0,'keys':[],'restore':0,'valid':True,'copy_result':'matched','source':'original','captures':0,'source_checks':0,'late_change':False}
main.range_access.unchanged=lambda *a:state['valid']
def fresh_capture(rid,text_pattern,document_mode):
 assert rid==(1,2) and text_pattern is pattern and document_mode
 state['captures']+=1
 return types.SimpleNamespace(target=Range(),text=state['source'])
def fresh_source_matches(snapshot,rid,text_pattern):
 assert text_pattern is pattern
 state['source_checks']+=1
 if state['late_change'] and state['source_checks']>1:state['source']='changed'
 return rid==(1,2) and state['source']==snapshot.text
main.range_access.capture=fresh_capture
main.range_access.after_selection_source_matches=fresh_source_matches
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
state.update(selected=0,keys=[],valid=True,copy_result='matched',captures=0,source_checks=0);app.errors=[];app.busy=True;snap.document_mode=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['c','v'] and state['selected']==1 and state['captures']==1 and not app.errors
state.update(selected=0,keys=[],valid=False);app.busy=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
assert not state['keys'] and state['selected']==0 and app.errors

# A provider source change detected after Ctrl+C blocks Ctrl+V.
state.update(selected=0,keys=[],valid=True,source='changed',source_checks=0);app.errors=[];app.busy=True;snap.document_mode=False
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['a','c'] and app.errors and not app.busy

# Source is checked again immediately before pasting, even after the copy matched.
state.update(selected=0,keys=[],valid=True,source='original',source_checks=0,late_change=True);app.errors=[];app.busy=True
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['a','c'] and app.errors and not app.busy
print('fresh document selection once, copied source, stale handles and late source edits: PASS')

# A temporarily stale provider can settle after our selection.
state.update(selected=0,keys=[],valid=True,source='original',source_checks=0,late_change=False);app.errors=[];app.busy=True
def delayed(snapshot,rid,text_pattern):
 state['source_checks']+=1
 return state['source_checks']>=3 and state['source']==snapshot.text
main.range_access.after_selection_source_matches=delayed
app.paste_range(7,(1,2),snap,'translated',20,'focus')
while pending:pending.pop(0)()
assert state['keys']==['a','c','a','v'] and not app.errors and not app.busy
print('temporary provider lag is retried safely: PASS')
