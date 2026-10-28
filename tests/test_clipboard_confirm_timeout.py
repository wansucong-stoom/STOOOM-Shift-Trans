import sys,pathlib,threading,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import clipboard_lease as c
c.TIMEOUT_SECONDS=.03;ready=threading.Event();release=threading.Event();state={'seq':1,'text':'previous','restored':False}
class U:
 def GetClipboardSequenceNumber(self):return state['seq']
class O:
 def OleInitialize(self):pass
 def OleUninitialize(self):pass
 def OleGetClipboard(self):return 'original'
 def OleSetClipboard(self,x):state.update(restored=True,text='previous',seq=state['seq']+1)
 def OleFlushClipboard(self):pass
class W:
 CF_UNICODETEXT=13
 def OpenClipboard(self):pass
 def CloseClipboard(self):pass
 def CountClipboardFormats(self):return 1
 def EmptyClipboard(self):state.update(text='',seq=state['seq']+1)
 def SetClipboardText(self,t,f):state.update(text=t,seq=state['seq']+1)
 def IsClipboardFormatAvailable(self,f):return True
 def GetClipboardData(self,f):ready.set();release.wait(1);return state['text']
c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()));c.pythoncom=O();c.win32clipboard=W()
x=c.ClipboardLease();x.put('translation');state.update(text='original',seq=state['seq']+1)
threading.Timer(.15,release.set).start()
try:x.confirm_selection_and_put('original','translation');raise AssertionError('expected timeout')
except TimeoutError:pass
try:x.restore()
except TimeoutError:pass
x._thread.join(1)
assert not x._thread.is_alive() and state['restored'] and state['text']=='previous'
print('Late selection verification restores clipboard on timeout: PASS')
