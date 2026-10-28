"""Temporarily write plain text while preserving the original OLE clipboard.

All OLE calls run on a dedicated STA thread. Qt/COM may already have initialized
its GUI thread in a different apartment; changing that thread's mode is unsafe.
"""
import ctypes
import queue
import threading
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
     value=self._put(arg) if op=='put' else self._restore()
     outcome=(True,value)
    except Exception as e:
     if op=='put':
      try:self._restore()
      except Exception:pass
     outcome=(False,e)
    with state['lock']:
     cancelled=state['cancelled']
     if not cancelled:
      state['result']=outcome
      event.set()
    if cancelled and op=='put':
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
