"""Inject real pywin32 exception types; never access the user's clipboard."""
import pathlib,sys,types
import pywintypes
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_lease as c

class Clock:
 value=0
 def monotonic(self):return self.value
 def sleep(self,delay):self.value+=delay

def fixture():
 clock=Clock();c.time=clock
 state={'seq':1,'text':'original','opens':0,'empty':0,'get':0,'set':0,'flush':0,'pumps':0}
 class User:
  def GetClipboardSequenceNumber(self):return state['seq']
 class Clip:
  CF_UNICODETEXT=13
  def OpenClipboard(self):state['opens']+=1
  def CloseClipboard(self):pass
  def CountClipboardFormats(self):return 2
  def EmptyClipboard(self):state['seq']+=1;state['empty']+=1;state['text']=''
  def SetClipboardText(self,text,kind):state['seq']+=1;state['text']=text
 class Ole:
  def PumpWaitingMessages(self):state['pumps']+=1
  def OleGetClipboard(self):state['get']+=1;return ('original','rich')
  def OleSetClipboard(self,value):
   assert value==('original','rich');state['set']+=1;state['seq']+=1;state['text']='original'
  def OleFlushClipboard(self):state['flush']+=1
 clip=Clip();ole=Ole();c.win32clipboard=clip;c.pythoncom=ole
 c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=User()))
 lease=c.ClipboardLease.__new__(c.ClipboardLease)
 lease.original=None;lease.original_empty=False;lease.ours=None
 return lease,state,clock,clip,ole

# Access denied from OpenClipboard is pywintypes.error, not OSError.
lease,s,clock,clip,ole=fixture();original=clip.OpenClipboard
def busy_open():
 original()
 if s['opens']<=2:raise pywintypes.error(5,'OpenClipboard','busy')
clip.OpenClipboard=busy_open
lease._put('translated')
assert s['empty']==1 and s['text']=='translated' and clock.value==.03
assert lease._restore() and s['text']=='original' and s['set']==1

# The screenshot's exact HRESULT is a com_error, including during backup.
lease,s,clock,clip,ole=fixture();original=ole.OleGetClipboard
def busy_get():
 s['get']+=1
 if s['get']<=2:raise pywintypes.com_error(-2147221040,'OpenClipboard failed',None,None)
 return ('original','rich')
ole.OleGetClipboard=busy_get
lease._put('translated');assert s['get']==3 and s['empty']==1

# A user copy while backup is waiting must never be overwritten.
lease,s,clock,clip,ole=fixture()
def changed_get():
 s['get']+=1
 if s['get']==1:
  s.update(seq=2,text='new user copy')
  raise pywintypes.com_error(-2147221040,'busy',None,None)
 return ('new user copy','rich')
ole.OleGetClipboard=changed_get
try:lease._put('translated')
except RuntimeError:pass
else:raise AssertionError('foreign copy during backup overwritten')
assert s['text']=='new user copy' and s['empty']==0

# Restore retries must re-check ownership, including before a delayed flush.
for stage in ('set','flush'):
 lease,s,clock,clip,ole=fixture();lease._put('translated')
 def changed():
  s.update(seq=s['seq']+1,text='new user copy')
  raise pywintypes.com_error(-2147221040,'busy',None,None)
 if stage=='set':ole.OleSetClipboard=lambda value:changed()
 else:ole.OleFlushClipboard=changed
 assert lease._restore() is False
 assert s['text']=='new user copy' and s['set']==(1 if stage=='flush' else 0)

lease,s,clock,clip,ole=fixture();lease.original_empty=True;lease.ours=s['seq']
def changed_open():
 s['opens']+=1
 if s['opens']==1:
  s.update(seq=s['seq']+1,text='new user copy')
  raise pywintypes.error(5,'OpenClipboard','busy')
clip.OpenClipboard=changed_open
assert lease._restore() is False and s['text']=='new user copy' and s['empty']==0

# Permanent contention is bounded, pumps messages, and performs no writes.
lease,s,clock,clip,ole=fixture()
def locked():raise pywintypes.com_error(-2147221040,'busy',None,None)
ole.OleGetClipboard=locked
try:lease._put('translated')
except c.ClipboardBusy:pass
else:raise AssertionError('permanent lock did not time out')
assert .30<=clock.value<=.301 and s['pumps']>0 and s['empty']==0

lease,s,clock,clip,ole=fixture()
def unrelated():
 s['get']+=1;raise pywintypes.com_error(-2147024809,'invalid argument',None,None)
ole.OleGetClipboard=unrelated
try:lease._put('translated')
except pywintypes.com_error:pass
else:raise AssertionError('unrelated error hidden')
assert s['get']==1 and clock.value==0
print('Clipboard contention: real exception types, bounded retries, one write, and newer-copy preservation during backup/restore/flush: PASS')
