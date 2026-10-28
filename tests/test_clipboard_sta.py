import sys,threading
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
import clipboard_lease as c
main_thread=threading.get_ident(); ids=[]
class Ole:
 def OleInitialize(self):
  ids.append(threading.get_ident())
  if threading.get_ident()==main_thread:raise RuntimeError('RPC_E_CHANGED_MODE')
 def OleUninitialize(self):ids.append(threading.get_ident())
 def OleGetClipboard(self):ids.append(threading.get_ident());return object()
 def OleSetClipboard(self,obj):ids.append(threading.get_ident())
 def OleFlushClipboard(self):ids.append(threading.get_ident())
class W:
 CF_UNICODETEXT=13
 def OpenClipboard(self): pass
 def CloseClipboard(self): pass
 def CountClipboardFormats(self): return 1
 def EmptyClipboard(self): pass
 def SetClipboardText(self,x,fmt):pass
class U:
 def GetClipboardSequenceNumber(self):return 4
c.pythoncom=Ole();c.win32clipboard=W();c.ctypes=__import__('types').SimpleNamespace(windll=__import__('types').SimpleNamespace(user32=U()))
x=c.ClipboardLease();x.put('test');assert x.restore()
assert ids and all(i==ids[0] and i!=main_thread for i in ids),ids
print('OLE initialized and restored on one separate STA thread: PASS')

