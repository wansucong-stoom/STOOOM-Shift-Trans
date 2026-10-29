"""Copy leases preserve rich original data and reject unrelated clipboard owners."""
import pathlib,sys,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_lease as c
real_ctypes=c.ctypes
state={'seq':1,'text':'original','owner':0,'restores':0}
class User:
    def GetClipboardSequenceNumber(self):return state['seq']
    def GetWindowThreadProcessId(self,owner,out):out._obj.value=owner
user=User()
class Function:
    def __call__(self,*args):return user.GetWindowThreadProcessId(*args)
native=types.SimpleNamespace(GetWindowThreadProcessId=Function())
class Clipboard:
    CF_UNICODETEXT=13
    def OpenClipboard(self):pass
    def CloseClipboard(self):pass
    def CountClipboardFormats(self):return 2
    def EmptyClipboard(self):state.update(seq=state['seq']+1,text='',owner=0)
    def SetClipboardText(self,text,kind):state.update(seq=state['seq']+1,text=text)
    def GetClipboardData(self,kind):return state['text']
    def IsClipboardFormatAvailable(self,kind):return True
    def GetClipboardOwner(self):return state['owner']
class Ole:
    def OleInitialize(self):pass
    def OleUninitialize(self):pass
    def OleGetClipboard(self):return ('original','rich-format-sentinel')
    def OleSetClipboard(self,value):
        assert value==('original','rich-format-sentinel')
        state.update(seq=state['seq']+1,text='original',restores=state['restores']+1)
    def OleFlushClipboard(self):pass
c.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=user),c_ulong=real_ctypes.c_ulong,WinDLL=lambda *a,**kw:native,POINTER=real_ctypes.POINTER,byref=real_ctypes.byref)
c.win32clipboard=Clipboard();c.pythoncom=Ole()
a=c.ClipboardLease();a.arm_copy();marker=state['text'];assert 'STOOM-COPY-' in marker and a.read_copy([42]) is None
state.update(seq=state['seq']+1,text='원문',owner=42)
assert a.read_copy([42])=='원문'
a.arm_copy();assert state['text']!=marker
state.update(seq=state['seq']+1,text='원문',owner=42)
assert a.read_copy([42])=='원문'
a.replace_owned('원문','Hello');assert state['text']=='Hello'
assert a.restore() and state['restores']==1 and state['text']=='original'

a=c.ClipboardLease();a.arm_copy();state.update(seq=state['seq']+1,text='user copy',owner=99)
try:a.read_copy([42])
except RuntimeError:pass
else:raise AssertionError('foreign owner accepted')
assert not a.restore() and state['text']=='user copy'
print('Keyboard clipboard: unique markers, fresh target-owned copies, one rich backup, owned replacement and preservation of foreign user copy: PASS')
