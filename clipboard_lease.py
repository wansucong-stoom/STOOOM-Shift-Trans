"""Temporarily write plain text while preserving the original OLE clipboard.

All OLE calls run on a dedicated STA thread. Qt/COM may already have initialized
its GUI thread in a different apartment; changing that thread's mode is unsafe.
"""
import ctypes
import queue
import threading
import time
import unicodedata
import uuid
import pythoncom
import win32clipboard

TIMEOUT_SECONDS=10
BUSY_SECONDS=.30
OWNER_WINDOW=0  # Set only by the isolated helper's native message window.

class ClipboardBusy(RuntimeError):
 pass

def _retry_clipboard(operation, *, opening=False, guard=None):
 """Retry only clipboard contention, without replaying writes or pastes.

 pywintypes.error/com_error do not inherit OSError. Check their numeric code
 rather than catching unrelated COM failures. A restore guard runs again after
 every wait so a newer user copy always wins.
 """
 deadline=time.monotonic()+BUSY_SECONDS
 while True:
  if guard is not None and not guard():return False
  try:return operation()
  except Exception as error:
   code=getattr(error,'hresult',getattr(error,'winerror',None))
   if code is None and error.args:code=error.args[0]
   busy=isinstance(code,int) and (code&0xffffffff)==0x800401d0
   if opening and code==5:busy=True
   if not busy:raise
   if time.monotonic()>=deadline:
    raise ClipboardBusy('다른 프로그램이 클립보드를 사용 중입니다. 잠시 후 다시 시도하세요.') from error
   pump=getattr(pythoncom,'PumpWaitingMessages',None)
   if pump:pump()
   time.sleep(min(.015,max(0,deadline-time.monotonic())))

def _open_clipboard():
 operation=(lambda:win32clipboard.OpenClipboard(OWNER_WINDOW)) if OWNER_WINDOW else win32clipboard.OpenClipboard
 return _retry_clipboard(operation,opening=True)

def _ole_uninitialize():
 # pywin32 exposes OleInitialize but commonly does not expose its matching
 # OleUninitialize. It must be called on the same STA that initialized OLE.
 if hasattr(pythoncom,'OleUninitialize'):
  pythoncom.OleUninitialize()
 else:
  ole=ctypes.OleDLL('ole32')
  ole.OleUninitialize.argtypes=()
  ole.OleUninitialize.restype=None
  ole.OleUninitialize()

class ClipboardLease:
 def __init__(self):
  self.original=None; self.original_empty=False; self.ours=None
  self._requests=queue.Queue(); self._ready=threading.Event(); self._init_error=None
  self._thread=threading.Thread(target=self._run,name='STOOM-clipboard-STA',daemon=True)
  self._thread.start()
  if not self._ready.wait(TIMEOUT_SECONDS): raise TimeoutError('클립보드 준비 시간이 초과되었습니다.')
  if self._init_error: raise self._init_error
 def _run(self):
  try: pythoncom.OleInitialize()
  except Exception as e:
   self._init_error=e; self._ready.set(); return
  self._ready.set()
  try:
   while True:
    # OLE creates hidden windows on the STA. A blocking Queue.get prevents
    # Windows from delivering COM/clipboard callbacks while the lease is idle.
    try:op,arg,event,state=self._requests.get(timeout=.02)
    except queue.Empty:
     pump=getattr(pythoncom,'PumpWaitingMessages',None)
     if pump and pump():break
     continue
    if op=='stop': event.set(); break
    try:
     if op=='put':value=self._put(arg)
     elif op=='confirm':value=self._confirm_and_put(*arg)
     elif op=='arm_copy':value=self._arm_copy()
     elif op=='read_copy':value=self._read_copy(arg)
     elif op=='replace_owned':value=self._replace_owned(*arg)
     else:value=self._restore()
     outcome=(True,value)
    except Exception as e:
     if op in ('put','arm_copy','replace_owned'):
      try:self._restore()
      except Exception:pass
     outcome=(False,e)
    with state['lock']:
     cancelled=state['cancelled']
     if not cancelled:
      state['result']=outcome
      event.set()
    if cancelled and op in ('put','confirm','arm_copy','replace_owned'):
     try:self._restore()
     except Exception:pass
    pump=getattr(pythoncom,'PumpWaitingMessages',None)
    if pump and pump():break
  finally:
   self.original=None
   _ole_uninitialize()
 def _call(self,op,arg=None):
  if not self._thread.is_alive(): raise RuntimeError('클립보드 작업이 종료되었습니다.')
  event=threading.Event();state={'lock':threading.Lock(),'cancelled':False,'result':None}
  self._requests.put((op,arg,event,state))
  if not event.wait(TIMEOUT_SECONDS):
   with state['lock']:
    if not event.is_set():
     state['cancelled']=True
     raise TimeoutError('클립보드 작업 시간이 초과되었습니다.')
  if op=='stop':return None
  ok,value=state['result']
  if not ok:raise value
  return value
 def put(self,text):
  try:self._call('put',text)
  except Exception:
   try:self._call('stop')
   except Exception:pass
   raise
 def _put(self,text):
  _open_clipboard()
  try:
   before=ctypes.windll.user32.GetClipboardSequenceNumber()
   self.original_empty=(win32clipboard.CountClipboardFormats()==0)
  finally:win32clipboard.CloseClipboard()
  if not self.original_empty:self.original=_retry_clipboard(pythoncom.OleGetClipboard)
  _open_clipboard()
  try:
   if ctypes.windll.user32.GetClipboardSequenceNumber()!=before:
    raise RuntimeError('클립보드가 바뀌어 번역을 중단했습니다.')
   win32clipboard.EmptyClipboard()
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   win32clipboard.SetClipboardText(text,win32clipboard.CF_UNICODETEXT)
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
  finally:win32clipboard.CloseClipboard()
 def confirm_selection_and_put(self,expected,translation):
  """Verify the result of Ctrl+C before replacing our clipboard text."""
  return self._call('confirm',(expected,translation))
 def arm_copy(self):
  """Replace only our own temporary clipboard with an unpredictable marker."""
  return self._call('arm_copy')
 def read_copy(self,owner_pids):
  """Return only new clipboard text owned by the target application."""
  return self._call('read_copy',tuple(owner_pids))
 def _arm_copy(self):
  marker='\u2063STOOM-COPY-'+uuid.uuid4().hex+'\u2063'
  if self.ours is None:
   self._put(marker)
  else:
   _open_clipboard()
   try:
    if ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:
     raise RuntimeError('클립보드가 바뀌어 번역을 중단했습니다.')
    win32clipboard.EmptyClipboard()
    self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
    win32clipboard.SetClipboardText(marker,win32clipboard.CF_UNICODETEXT)
    self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   finally:win32clipboard.CloseClipboard()
 def _read_copy(self,owner_pids):
  _open_clipboard()
  try:
   seq=ctypes.windll.user32.GetClipboardSequenceNumber()
   if seq==self.ours:return None
   # pywin32 treats a legitimate NULL owner as an exception. The native API
   # returns NULL for an ownerless clipboard without reporting a failure.
   from ctypes import wintypes
   user=ctypes.WinDLL('user32',use_last_error=True)
   user.GetClipboardOwner.argtypes=[];user.GetClipboardOwner.restype=wintypes.HWND
   owner=user.GetClipboardOwner()
   pid=ctypes.c_ulong()
   if owner:
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowThreadProcessId.restype=wintypes.DWORD
    user.GetWindowThreadProcessId(owner,ctypes.byref(pid))
   if owner and pid.value not in owner_pids:
    raise RuntimeError('다른 프로그램이 클립보드를 변경해 번역을 중단했습니다.')
   # This is the copy we requested from the focused application. Keep it in
   # our lease so failure also restores the user's original rich clipboard.
   self.ours=seq
   if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
    raise ValueError('선택한 영역에 복사할 텍스트가 없습니다.')
   return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
  finally:win32clipboard.CloseClipboard()
 def replace_owned(self,expected,text):
  """Replace the verified copy without taking a new clipboard backup."""
  return self._call('replace_owned',(expected,text))
 def _replace_owned(self,expected,text):
  _open_clipboard()
  try:
   if ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:
    raise RuntimeError('클립보드가 바뀌어 번역을 중단했습니다.')
   if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT) or win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)!=expected:
    raise RuntimeError('복사한 원문이 바뀌어 번역을 중단했습니다.')
   win32clipboard.EmptyClipboard()
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   win32clipboard.SetClipboardText(text,win32clipboard.CF_UNICODETEXT)
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
  finally:win32clipboard.CloseClipboard()
 def _confirm_and_put(self,expected,translation):
  _open_clipboard()
  try:
   seq=ctypes.windll.user32.GetClipboardSequenceNumber()
   if seq==self.ours:return 'pending'
   if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):return 'mismatch'
   actual=win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
   def norm(text):return unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n'))
   if norm(actual)!=norm(expected):return 'mismatch'
   # We have observed the copy of exactly our expected selection. If another
   # application changes the clipboard after this, restore() will not clobber it.
   self.ours=seq
   win32clipboard.EmptyClipboard()
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   win32clipboard.SetClipboardText(translation,win32clipboard.CF_UNICODETEXT)
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   return 'matched'
  finally:win32clipboard.CloseClipboard()
 def _restore(self):
  if self.ours is None or ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:return False
  if self.original_empty:
   _open_clipboard()
   try:
    if ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:return False
    win32clipboard.EmptyClipboard()
   finally:win32clipboard.CloseClipboard()
  else:
   owned=lambda:ctypes.windll.user32.GetClipboardSequenceNumber()==self.ours
   if _retry_clipboard(lambda:pythoncom.OleSetClipboard(self.original),guard=owned) is False:return False
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   if _retry_clipboard(pythoncom.OleFlushClipboard,guard=owned) is False:return False
  return True
 def restore(self):
  try:return self._call('restore')
  finally:
   try:self._call('stop')
   except Exception:pass
