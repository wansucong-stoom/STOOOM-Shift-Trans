"""Materialized Win32 clipboard backup; no live IDataObject is saved/restored.

Text, RTF/HTML, PNG/DIB, file lists and custom HGLOBAL formats are copied while
the clipboard is locked. GDI handles are duplicated by their documented type.
Unmaterializable data aborts before EmptyClipboard; a newer copy always wins.
"""
import ctypes as C
from ctypes import wintypes as W
import clipboard_lease as common
import win32clipboard

MAX_BYTES=64*1024*1024
MAX_FORMATS=256
INTERNAL_OLE={'dataobject','ole private data'}

class METAFILEPICT(C.Structure):
 _fields_=[('mm',W.LONG),('xExt',W.LONG),('yExt',W.LONG),('hMF',W.HANDLE)]

class BITMAP(C.Structure):
 _fields_=[('kind',W.LONG),('width',W.LONG),('height',W.LONG),('stride',W.LONG),
  ('planes',W.WORD),('depth',W.WORD),('bits',C.c_void_p)]

def _api():
 user=C.WinDLL('user32',use_last_error=True)
 kernel=C.WinDLL('kernel32',use_last_error=True)
 gdi=C.WinDLL('gdi32',use_last_error=True)
 def signature(dll,name,args,result):
  function=getattr(dll,name);function.argtypes=args;function.restype=result
 signature(user,'GetClipboardData',[W.UINT],W.HANDLE)
 signature(user,'GetClipboardOwner',[],W.HWND)
 signature(user,'GetClipboardSequenceNumber',[],W.DWORD)
 signature(user,'GetWindowThreadProcessId',[W.HWND,C.POINTER(W.DWORD)],W.DWORD)
 signature(user,'SetClipboardData',[W.UINT,W.HANDLE],W.HANDLE)
 signature(user,'CopyImage',[W.HANDLE,W.UINT,C.c_int,C.c_int,W.UINT],W.HANDLE)
 signature(kernel,'GlobalSize',[W.HANDLE],C.c_size_t)
 signature(kernel,'GlobalLock',[W.HANDLE],C.c_void_p)
 signature(kernel,'GlobalUnlock',[W.HANDLE],W.BOOL)
 signature(kernel,'GlobalAlloc',[W.UINT,C.c_size_t],W.HANDLE)
 signature(kernel,'GlobalFree',[W.HANDLE],W.HANDLE)
 signature(gdi,'DeleteObject',[W.HANDLE],W.BOOL)
 signature(gdi,'GetObjectW',[W.HANDLE,C.c_int,C.c_void_p],C.c_int)
 signature(gdi,'GetMetaFileBitsEx',[W.HANDLE,W.UINT,C.c_void_p],W.UINT)
 signature(gdi,'GetEnhMetaFileBits',[W.HANDLE,W.UINT,C.c_void_p],W.UINT)
 signature(gdi,'SetEnhMetaFileBits',[W.UINT,C.c_void_p],W.HANDLE)
 signature(gdi,'DeleteEnhMetaFile',[W.HANDLE],W.BOOL)
 signature(gdi,'CopyMetaFileW',[W.HANDLE,W.LPCWSTR],W.HANDLE)
 signature(gdi,'DeleteMetaFile',[W.HANDLE],W.BOOL)
 signature(gdi,'GetPaletteEntries',[W.HANDLE,W.UINT,W.UINT,C.c_void_p],W.UINT)
 signature(gdi,'CreatePalette',[C.c_void_p],W.HANDLE)
 return user,kernel,gdi

class Snapshot:
 def __init__(self):
  self.items=[];self.size=0;self.api=_api()
 def _account(self,size):
  self.size+=size
  if self.size>MAX_BYTES:raise RuntimeError('기존 클립보드 데이터가 너무 커서 안전하게 보관하지 못했습니다.')
 def _global_bytes(self,handle):
  kernel=self.api[1];size=kernel.GlobalSize(handle)
  if not size:raise RuntimeError('기존 클립보드의 일부 서식 데이터를 보관하지 못했습니다.')
  self._account(size)
  pointer=kernel.GlobalLock(handle)
  if not pointer:raise C.WinError(C.get_last_error())
  try:return C.string_at(pointer,size)
  finally:kernel.GlobalUnlock(handle)
 @classmethod
 def capture(cls):
  value=cls();user,kernel,gdi=value.api
  try:
   formats=[];fmt=0
   while True:
    fmt=win32clipboard.EnumClipboardFormats(fmt)
    if not fmt:break
    formats.append(fmt)
    if len(formats)>MAX_FORMATS:raise RuntimeError('기존 클립보드의 서식이 너무 많아 보관하지 못했습니다.')
   for fmt in formats:
    if fmt>=0xc000:
     name=win32clipboard.GetClipboardFormatName(fmt).casefold()
     if name in INTERNAL_OLE:continue
    if fmt==0x80:raise RuntimeError('기존 클립보드의 전용 표시 서식을 보관하지 못했습니다.')
    if 0x200<=fmt<=0x3ff:raise RuntimeError('기존 클립보드의 전용 소유 서식을 보관하지 못했습니다.')
    if fmt==2 and (8 in formats or 17 in formats):continue
    handle=user.GetClipboardData(fmt)
    if not handle:raise RuntimeError('기존 클립보드의 일부 데이터를 읽지 못했습니다.')
    if fmt in (2,0x82):
     # DIB/DIBV5 preserve the image and Windows synthesizes CF_BITMAP from it.
     bitmap=BITMAP()
     if gdi.GetObjectW(handle,C.sizeof(bitmap),C.byref(bitmap))!=C.sizeof(bitmap):raise C.WinError(C.get_last_error())
     value._account(abs(bitmap.stride)*abs(bitmap.height))
     copy=user.CopyImage(handle,0,0,0,0x2000)
     if not copy:raise C.WinError(C.get_last_error())
     value.items.append((fmt,'bitmap',copy))
    elif fmt in (14,0x8e):
     size=gdi.GetEnhMetaFileBits(handle,0,None);value._account(size)
     if not size:raise C.WinError(C.get_last_error())
     data=C.create_string_buffer(size)
     if gdi.GetEnhMetaFileBits(handle,size,data)!=size:raise C.WinError(C.get_last_error())
     value.items.append((fmt,'enhmetafile',data.raw))
    elif fmt in (3,0x83):
     data=value._global_bytes(handle)
     if len(data)<C.sizeof(METAFILEPICT):raise RuntimeError('잘못된 메타파일 서식입니다.')
     meta=METAFILEPICT.from_buffer_copy(data)
     value._account(gdi.GetMetaFileBitsEx(meta.hMF,0,None))
     copy=gdi.CopyMetaFileW(meta.hMF,None)
     if not copy:raise C.WinError(C.get_last_error())
     value.items.append((fmt,'metafile',(meta.mm,meta.xExt,meta.yExt,copy)))
    elif fmt==9:
     count=gdi.GetPaletteEntries(handle,0,0,None)
     if not count or count>65535:raise RuntimeError('팔레트 서식을 읽지 못했습니다.')
     data=C.create_string_buffer(count*4);value._account(count*4)
     if gdi.GetPaletteEntries(handle,0,count,data)!=count:raise C.WinError(C.get_last_error())
     value.items.append((fmt,'palette',data.raw))
    else:value.items.append((fmt,'global',value._global_bytes(handle)))
   if formats and not value.items:raise RuntimeError('기존 클립보드 데이터를 보관하지 못했습니다.')
   return value
  except Exception:
   value.close();raise
 def _allocate(self,data):
  kernel=self.api[1];handle=kernel.GlobalAlloc(0x42,max(1,len(data)))
  if not handle:raise MemoryError('클립보드 복원 메모리를 준비하지 못했습니다.')
  pointer=kernel.GlobalLock(handle)
  if not pointer:kernel.GlobalFree(handle);raise C.WinError(C.get_last_error())
  try:C.memmove(pointer,data,len(data))
  finally:kernel.GlobalUnlock(handle)
  return handle
 def _prepare(self):
  user,kernel,gdi=self.api
  prepared=[]
  try:
   for fmt,kind,data in self.items:
    if kind=='global':handle=self._allocate(data);cleanup=lambda h=handle:kernel.GlobalFree(h)
    elif kind=='bitmap':
     handle=user.CopyImage(data,0,0,0,0x2000);cleanup=lambda h=handle:gdi.DeleteObject(h)
    elif kind=='enhmetafile':
     buffer=C.create_string_buffer(data);handle=gdi.SetEnhMetaFileBits(len(data),buffer)
     cleanup=lambda h=handle:gdi.DeleteEnhMetaFile(h)
    elif kind=='palette':
     import struct
     buffer=C.create_string_buffer(struct.pack('<HH',0x300,len(data)//4)+data)
     handle=gdi.CreatePalette(buffer);cleanup=lambda h=handle:gdi.DeleteObject(h)
    else:
     mm,x,y,source=data;copy=gdi.CopyMetaFileW(source,None)
     if not copy:raise C.WinError(C.get_last_error())
     meta=METAFILEPICT(mm,x,y,copy)
     try:handle=self._allocate(bytes(meta))
     except Exception:gdi.DeleteMetaFile(copy);raise
     def cleanup(h=handle,m=copy):kernel.GlobalFree(h);gdi.DeleteMetaFile(m)
    if not handle:raise C.WinError(C.get_last_error())
    prepared.append([fmt,handle,cleanup])
   return prepared
  except Exception:
   for fmt,handle,cleanup in prepared:cleanup()
   raise
 def write(self,changed):
  user=self.api[0];prepared=self._prepare()
  try:
   win32clipboard.EmptyClipboard();changed()
   for item in prepared:
    fmt,handle,cleanup=item
    if not user.SetClipboardData(fmt,handle):raise C.WinError(C.get_last_error())
    item[2]=None  # Windows owns the handle after successful transfer.
    changed()
  finally:
   for fmt,handle,cleanup in prepared:
    if cleanup:cleanup()
 def close(self):
  for fmt,kind,data in self.items:
   if kind=='bitmap':self.api[2].DeleteObject(data)
   elif kind=='metafile':self.api[2].DeleteMetaFile(data[3])
  self.items=[]
 def __del__(self):self.close()

class ClipboardState(common.ClipboardLease):
 """Private operations run only on the helper's single Windows thread."""
 def __init__(self):self.original=None;self.original_empty=False;self.ours=None;self.api=_api()
 def _sequence(self):self.ours=common.ctypes.windll.user32.GetClipboardSequenceNumber()
 def _after_write(self):
  user=self.api[0];before=user.GetClipboardSequenceNumber();owner=user.GetClipboardOwner();after=user.GetClipboardSequenceNumber()
  if owner==common.OWNER_WINDOW and before==after:self.ours=after
 def _put(self,text):
  changed=False
  common._open_clipboard()
  try:
   self.original=Snapshot.capture()
   self.original_empty=not self.original.items
   win32clipboard.EmptyClipboard();changed=True;self._sequence()
   win32clipboard.SetClipboardText(text,win32clipboard.CF_UNICODETEXT);self._sequence()
  finally:
   win32clipboard.CloseClipboard()
   if changed:self._after_write()
 def _restore(self):
  if self.ours is None or common.ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:return False
  common._open_clipboard()
  changed=False
  try:
   if common.ctypes.windll.user32.GetClipboardSequenceNumber()!=self.ours:return False
   def track():
    nonlocal changed
    changed=True;self._sequence()
   self.original.write(track)
   return True
  finally:
   win32clipboard.CloseClipboard()
   if changed:self._after_write()
 def _arm_copy(self):
  try:return super()._arm_copy()
  finally:self._after_write()
 def _replace_owned(self,expected,text):
  try:return super()._replace_owned(expected,text)
  finally:self._after_write()
 def _confirm_and_put(self,expected,translation):
  try:return super()._confirm_and_put(expected,translation)
  finally:self._after_write()
 def _read_copy(self,owner_pids):
  user=self.api[0];owner=None;accepted=False
  common._open_clipboard()
  try:
   seq=user.GetClipboardSequenceNumber()
   if seq==self.ours:return None
   owner=user.GetClipboardOwner();pid=W.DWORD()
   if owner:user.GetWindowThreadProcessId(owner,C.byref(pid))
   if owner and pid.value not in owner_pids:raise RuntimeError('다른 프로그램이 클립보드를 변경해 번역을 중단했습니다.')
   accepted=True;self.ours=seq
   if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
    raise ValueError('선택한 영역에 복사할 텍스트가 없습니다.')
   return win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
  finally:
   win32clipboard.CloseClipboard()
   if accepted:
    before=user.GetClipboardSequenceNumber();current=user.GetClipboardOwner();after=user.GetClipboardSequenceNumber()
    if current==owner and before==after:self.ours=after
