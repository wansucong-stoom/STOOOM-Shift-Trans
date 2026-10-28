import sys,pathlib,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import clipboard_lease as c
state={'seq':1,'text':'previous','restored':0}
class U:
 def GetClipboardSequenceNumber(self):return state['seq']
class O:
 def OleInitialize(self):pass
 def OleUninitialize(self):pass
 def OleGetClipboard(self):return 'original'
 def OleSetClipboard(self,x):state['restored']+=1;state['text']='previous';state['seq']+=1
 def OleFlushClipboard(self):pass
class W:
 CF_UNICODETEXT=13
 def OpenClipboard(self):pass
 def CloseClipboard(self):pass
 def CountClipboardFormats(self):return 1
 def EmptyClipboard(self):state['seq']+=1;state['text']=''
 def SetClipboardText(self,t,f):state['seq']+=1;state['text']=t
 def IsClipboardFormatAvailable(self,f):return True
 def GetClipboardData(self,f):return state['text']
c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=U()));c.pythoncom=O();c.win32clipboard=W()
a=c.ClipboardLease();a.put('translated');assert a.confirm_selection_and_put('original','translated')=='pending'
state.update(seq=state['seq']+1,text='original')
assert a.confirm_selection_and_put('original','translated')=='matched' and state['text']=='translated'
assert a.restore() and state['text']=='previous'
b=c.ClipboardLease();b.put('translated');state.update(seq=state['seq']+1,text='someone else')
assert b.confirm_selection_and_put('original','translated')=='mismatch'
assert not b.restore() and state['text']=='someone else'
print('copied selection checked before paste; mismatched clipboard not overwritten: PASS')
