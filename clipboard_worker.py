"""Materialized Win32 clipboard server; no Qt/UIA/hooks or OLE clipboard API."""
import ctypes
from ctypes import wintypes
import json
import os
import queue
import sys
import threading
import uuid

MAX_FRAME=262144

def _create_owner_window():
 # Use the OS STATIC window class, whose window procedure is entirely native.
 # This invisible message-only window never takes keyboard focus.
 user=ctypes.WinDLL('user32',use_last_error=True)
 user.CreateWindowExW.argtypes=[wintypes.DWORD,wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD,
   ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,wintypes.HMENU,
   wintypes.HINSTANCE,ctypes.c_void_p]
 user.CreateWindowExW.restype=wintypes.HWND
 user.DestroyWindow.argtypes=[wintypes.HWND];user.DestroyWindow.restype=wintypes.BOOL
 window=user.CreateWindowExW(0,'STATIC','STOOM Clipboard',0,0,0,0,0,-3,None,None,None)
 if not window:raise ctypes.WinError(ctypes.get_last_error())
 return user,window

def _stdio():
 # Frozen --windowed executables have sys.stdin/sys.stdout == None. Duplicate
 # inherited pipe handles before wrapping them; never depend on a console.
 import msvcrt
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.GetStdHandle.argtypes=[wintypes.DWORD];kernel.GetStdHandle.restype=wintypes.HANDLE
 kernel.GetCurrentProcess.restype=wintypes.HANDLE
 kernel.DuplicateHandle.argtypes=[wintypes.HANDLE,wintypes.HANDLE,wintypes.HANDLE,
    ctypes.POINTER(wintypes.HANDLE),wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
 kernel.DuplicateHandle.restype=wintypes.BOOL
 def wrap(identifier,flags,mode):
  handle=kernel.GetStdHandle(identifier&0xffffffff)
  if not handle or handle==ctypes.c_void_p(-1).value:raise OSError('missing inherited pipe')
  duplicate=wintypes.HANDLE();process=kernel.GetCurrentProcess()
  if not kernel.DuplicateHandle(process,handle,process,ctypes.byref(duplicate),0,False,2):
   raise ctypes.WinError(ctypes.get_last_error())
  descriptor=msvcrt.open_osfhandle(duplicate.value,flags|os.O_BINARY)
  return os.fdopen(descriptor,mode,buffering=65536)
 return wrap(-10,os.O_RDONLY,'rb'),wrap(-11,os.O_WRONLY,'wb')

def run():
 ctypes.windll.kernel32.SetErrorMode(0x0001|0x0002)
 source,sink=_stdio()
 import win32gui
 import clipboard_native as native
 import clipboard_lease as backend
 requests=queue.Queue()
 def read():
  try:
   while True:
    line=source.readline(MAX_FRAME+1)
    if not line:break
    if len(line)>MAX_FRAME or not line.endswith(b'\n'):break
    requests.put(json.loads(line.decode('utf-8')))
  except (OSError,ValueError):pass
  finally:requests.put(None)
 threading.Thread(target=read,name='STOOM-clipboard-commands',daemon=True).start()
 lease=None;token=None
 user,owner_window=_create_owner_window();backend.OWNER_WINDOW=owner_window
 try:
  while True:
   win32gui.PumpWaitingMessages()
   try:request=requests.get(timeout=.01)
   except queue.Empty:continue
   if request is None:break
   request_id=request.get('id') if isinstance(request,dict) else None
   try:
    if not isinstance(request_id,str) or len(request_id)!=32:raise ValueError('잘못된 클립보드 요청입니다.')
    operation=request.get('op');args=request.get('args',[])
    if not isinstance(args,list):raise ValueError('잘못된 클립보드 요청입니다.')
    if operation=='ping':value={'pid':os.getpid(),'sta':True,'native_snapshot':True,'stdio_none':sys.stdin is None and sys.stdout is None,
      'qt_widgets_loaded':'PySide6.QtWidgets' in sys.modules,'uia_loaded':'pywinauto' in sys.modules}
    elif operation=='begin':
     if lease is not None:
      lease._restore();lease=None;token=None
     lease=native.ClipboardState()
     token=uuid.uuid4().hex;value=token
    else:
     if lease is None or request.get('lease')!=token:raise ValueError('클립보드 작업이 만료되었습니다. 다시 시도하세요.')
     if operation=='keep':
      if args:raise ValueError('잘못된 클립보드 요청입니다.')
      if lease.ours is None or backend.ctypes.windll.user32.GetClipboardSequenceNumber()!=lease.ours:
       raise ValueError('클립보드가 바뀌어 번역을 중단했습니다.')
      # All data is already materialized. Drop the backup WITHOUT writing to
      # the clipboard, before the asynchronous paste command is delivered.
      sequence=lease.ours;lease=None;token=None
      result={'id':request_id,'ok':True,'value':sequence}
      sink.write(json.dumps(result,ensure_ascii=True).encode()+b'\n');sink.flush()
      continue
     allowed={'put':(lease._put,1),'arm_copy':(lease._arm_copy,0),
       'read_copy':(lease._read_copy,1),'replace_owned':(lease._replace_owned,2),
       'confirm':(lease._confirm_and_put,2),'end':(lease._restore,0)}
     if operation not in allowed:raise ValueError('잘못된 클립보드 작업입니다.')
     function,count=allowed[operation]
     if len(args)!=count:raise ValueError('잘못된 클립보드 요청입니다.')
     value=function(*args)
     if operation=='end':lease=None;token=None
    result={'id':request_id,'ok':True,'value':value}
   except Exception as error:
    result={'id':request_id,'ok':False,'kind':'busy' if isinstance(error,backend.ClipboardBusy) else 'error','error':str(error)}
   sink.write(json.dumps(result,ensure_ascii=True).encode()+b'\n');sink.flush()
 finally:
  if lease is not None:
   try:lease._restore()
   except Exception:pass
  lease=None
  backend.OWNER_WINDOW=0;user.DestroyWindow(owner_window)
  source.close();sink.close()
 return 0
