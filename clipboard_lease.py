"""Temporarily write plain text while preserving the original OLE clipboard.

All OLE calls run on a dedicated STA thread. Qt/COM may already have initialized
its GUI thread in a different apartment; changing that thread's mode is unsafe.
"""
import ctypes
import queue
import threading
import unicodedata
import uuid
import pythoncom
import win32clipboard

TIMEOUT_SECONDS=10

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
    op,arg,event,state=self._requests.get()
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
  finally:
   self.original=None
   pythoncom.OleUninitialize()
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
  win32clipboard.OpenClipboard()
  try:self.original_empty=(win32clipboard.CountClipboardFormats()==0)
  finally:win32clipboard.CloseClipboard()
  if not self.original_empty:self.original=pythoncom.OleGetClipboard()
  win32clipboard.OpenClipboard()
  try:
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
   win32clipboard.OpenClipboard()
   try:
    if ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:
     raise RuntimeError('클립보드가 바뀌어 번역을 중단했습니다.')
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(marker,win32clipboard.CF_UNICODETEXT)
    self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
   finally:win32clipboard.CloseClipboard()
 def _read_copy(self,owner_pids):
  win32clipboard.OpenClipboard()
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
  win32clipboard.OpenClipboard()
  try:
   if ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:
    raise RuntimeError('클립보드가 바뀌어 번역을 중단했습니다.')
   if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT) or win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)!=expected:
    raise RuntimeError('복사한 원문이 바뀌어 번역을 중단했습니다.')
   win32clipboard.EmptyClipboard()
   win32clipboard.SetClipboardText(text,win32clipboard.CF_UNICODETEXT)
   self.ours=ctypes.windll.user32.GetClipboardSequenceNumber()
  finally:win32clipboard.CloseClipboard()
 def _confirm_and_put(self,expected,translation):
  win32clipboard.OpenClipboard()
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
   win32clipboard.OpenClipboard()
   try:win32clipboard.EmptyClipboard()
   finally:win32clipboard.CloseClipboard()
  else:
   pythoncom.OleSetClipboard(self.original)
   pythoncom.OleFlushClipboard()
  return True
 def restore(self):
  try:return self._call('restore')
  finally:
   try:self._call('stop')
   except Exception:pass
