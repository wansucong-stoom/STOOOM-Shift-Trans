"""A target reads after 650ms, long after the old 200ms restore deadline."""
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import keyboard_access as k

class Lease:
 def __init__(self,env):self.env=env;self.closed=False
 def arm_copy(self):self.env.clipboard='marker';self.env.sequence+=1
 def read_copy(self,pids):return self.env.selected
 def replace_owned(self,expected,text):
  assert expected==self.env.selected
  self.env.clipboard=text;self.env.sequence+=1
 def keep_translation(self):
  self.closed=True;self.env.kept+=1
  return self.env.sequence
 def restore(self):
  if not self.closed:
   self.env.clipboard='IMAGE FROM OLD CLIPBOARD';self.env.restored+=1
  self.closed=True

class Env:
 def __init__(self):
  self.focus=object();self.owner_pids=[1];self.selected='번역할 문장'
  self.clipboard='IMAGE FROM OLD CLIPBOARD';self.sequence=1;self.kept=0;self.restored=0
  self.clock=0;self.pending=None;self.pasted=[];self.fail_send=False;self.foreign=False
 def activity(self):return 7,0
 def current(self):return True
 def safe(self):pass
 def modifiers(self):return False
 def anchor(self):return None
 def now(self):return self.clock
 def sleep(self,seconds):
  self.clock+=seconds
  if self.pending is not None and self.clock>=self.pending:
   self.pasted.append(self.clipboard);self.pending=None
 def clipboard_sequence(self):return self.sequence+(1 if self.foreign else 0)
 def chord(self,*keys):
  if keys==(k.CTRL,ord('C')):return
  assert keys==(k.CTRL,ord('V'))
  if self.fail_send:raise k.KeyboardError('input rejected')
  self.pending=self.clock+.65

e=Env();d=k.Driver(e,lambda:Lease(e));snapshot=k.Snapshot(e.selected,e.focus,7,None,False)
d.apply(snapshot,'Translated text')
assert not e.pasted and e.clipboard=='Translated text'
e.sleep(.70)
assert e.pasted==['Translated text'] and e.kept==1 and e.restored==0

# A rejected SendInput must still leave text, never put the old image back.
e=Env();e.fail_send=True;d=k.Driver(e,lambda:Lease(e))
try:d.apply(k.Snapshot(e.selected,e.focus,7,None,False),'Translated text')
except k.KeyboardError:pass
else:raise AssertionError('input rejection hidden')
assert e.clipboard=='Translated text' and e.restored==0 and not e.pasted

# A new clipboard revision before Ctrl+V cancels rather than pasting a foreign item.
e=Env();e.foreign=True;d=k.Driver(e,lambda:Lease(e))
try:d.apply(k.Snapshot(e.selected,e.focus,7,None,False),'Translated text')
except k.Cancelled:pass
else:raise AssertionError('foreign clipboard was pasted')
assert not e.pasted and e.pending is None
print('Delayed paste: 650ms reader receives translation, no timed image restoration, rejected input retains text, and foreign clipboard cancels: PASS')
