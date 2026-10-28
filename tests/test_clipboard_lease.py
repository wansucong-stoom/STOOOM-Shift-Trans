import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));import clipboard_lease as c
class U:
 seq=1
 def GetClipboardSequenceNumber(self):return self.seq
u=U(); c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=u))
class W:
 CF_UNICODETEXT=13
 def OpenClipboard(self):pass
 def CloseClipboard(self):pass
 def CountClipboardFormats(self):return 1
 def EmptyClipboard(self):u.seq+=1
 def SetClipboardText(self,t,kind):u.seq+=1
class P:
 restores=0; uninits=0
 def OleInitialize(self):pass
 def OleUninitialize(self):self.uninits+=1
 def OleGetClipboard(self):return 'original object'
 def OleSetClipboard(self,v):assert v=='original object';self.restores+=1;u.seq+=1
 def OleFlushClipboard(self):pass
w=W();p=P();c.win32clipboard=w;c.pythoncom=p
x=c.ClipboardLease();x.put('translation');assert x.restore() and p.restores==1 and p.uninits==1
x=c.ClipboardLease();x.put('translation');u.seq+=1;assert x.restore() is False and p.restores==1 and p.uninits==2
print('clipboard restore and preservation of newer clipboard: PASS')

