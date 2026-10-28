import sys,threading,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));import clipboard_lease as c
c.TIMEOUT_SECONDS=.03
released=threading.Event(); state={'seq':1,'restored':False}
class U:
 def GetClipboardSequenceNumber(self):return state['seq']
class O:
 def OleInitialize(self):pass
 def OleUninitialize(self):pass
 def OleGetClipboard(self):return 'original'
 def OleSetClipboard(self,x):assert x=='original';state['restored']=True;state['seq']+=1
 def OleFlushClipboard(self):pass
class W:
 CF_UNICODETEXT=13
 def OpenClipboard(self):pass
 def CloseClipboard(self):pass
 def CountClipboardFormats(self):return 1
 def EmptyClipboard(self):state['seq']+=1
 def SetClipboardText(self,t,f):released.wait(1);state['seq']+=1
c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()));c.pythoncom=O();c.win32clipboard=W()
x=c.ClipboardLease();threading.Timer(.15,released.set).start()
try:x.put('late');raise AssertionError('expected timeout')
except TimeoutError:pass
x._thread.join(1)
assert not x._thread.is_alive() and state['restored']
print('Late clipboard write after timeout is restored: PASS')

