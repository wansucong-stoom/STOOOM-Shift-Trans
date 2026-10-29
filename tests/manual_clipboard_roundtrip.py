"""Supervised real clipboard round trips; no document, keyboard or mouse input.

The supervisor retains the original IDataObject outside the tested helper and
restores it only while the clipboard still contains our unique test fixture.
A newer user copy is preserved. No original clipboard contents are logged.
"""
import json,pathlib,queue,sys,threading,time,uuid,struct,os,ctypes
from ctypes import wintypes
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import win32gui,win32clipboard
import clipboard_lease as backend
import clipboard_native as native
import clipboard_process as client
import clipboard_worker

user,window=clipboard_worker._create_owner_window();backend.OWNER_WINDOW=window
outer=native.ClipboardState()
prefix='STOOM-NATIVE-TEST-'+uuid.uuid4().hex+':'
rich=win32clipboard.RegisterClipboardFormat('STOOM Native Roundtrip Fixture')
fixture_formats={rich:b'fixture-rich-data',
 win32clipboard.RegisterClipboardFormat('Rich Text Format'):b'{\\rtf1\\ansi Native fixture}',
 win32clipboard.RegisterClipboardFormat('HTML Format'):b'Version:1.0\r\n<html><b>Native fixture</b></html>',
 8:struct.pack('<IiiHHIIiiII',40,2,2,1,32,0,16,0,0,0,0)+b'\xff\x00\x00\x00'*4}
result=queue.Queue();broker=client.Broker([str(pathlib.Path(sys.argv[1]).resolve()),'--clipboard-worker'] if len(sys.argv)>1 else None)
def read_fixture():
 backend._open_clipboard()
 try:
  try:
   text=win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
   payload={fmt:win32clipboard.GetClipboardData(fmt) for fmt in fixture_formats}
  except Exception as error:
   formats=[];fmt=0
   while True:
    fmt=win32clipboard.EnumClipboardFormats(fmt)
    if not fmt:break
    formats.append((fmt,win32clipboard.GetClipboardFormatName(fmt) if fmt>=0xc000 else 'standard'))
   raise RuntimeError(str(error)+'; available formats: '+repr(formats)) from error
  return text,payload
 finally:win32clipboard.CloseClipboard()
def rounds():
 phase='handshake'
 try:
  first=broker.request('ping')
  assert first.get('native_snapshot') and not first['qt_widgets_loaded'] and not first['uia_loaded'],first
  for i in range(20):
   phase='before '+str(i)
   actual,payload=read_fixture()
   assert actual==prefix+'original' and all(payload[fmt].startswith(data) for fmt,data in fixture_formats.items())
   lease=client.ClipboardLease(broker)
   try:
    phase='put '+str(i)
    if i<10:lease.put(prefix+'translated '+str(i))
    else:
     source_text=prefix+'원문😀 '+str(i)
     for _ in range(2):
      lease.arm_copy();assert lease.read_copy([os.getpid()]) is None
      backend._open_clipboard()
      try:
       owner=outer.api[0].GetClipboardOwner();pid=wintypes.DWORD()
       outer.api[0].GetWindowThreadProcessId(owner,ctypes.byref(pid))
       assert pid.value==first['pid'],'newer foreign clipboard detected'
       win32clipboard.EmptyClipboard()
       win32clipboard.SetClipboardText(source_text,win32clipboard.CF_UNICODETEXT)
      finally:win32clipboard.CloseClipboard()
      assert lease.read_copy([os.getpid()])==source_text
     lease.replace_owned(source_text,prefix+'translated '+str(i))
   finally:
    phase='restore '+str(i);assert lease.restore() is True
  phase='final read'
  actual,payload=read_fixture()
  assert actual==prefix+'original' and all(payload[fmt].startswith(data) for fmt,data in fixture_formats.items())
  assert broker.request('ping')['pid']==first['pid']
  phase='delayed paste handoff'
  delayed=client.ClipboardLease(broker)
  delayed.put(prefix+'delayed translation')
  assert isinstance(delayed.keep_translation(),int)
  broker.close()  # Even helper shutdown must not restore the old image.
  time.sleep(.65)
  backend._open_clipboard()
  try:
   assert win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)==prefix+'delayed translation'
   assert not win32clipboard.IsClipboardFormatAvailable(8)
  finally:win32clipboard.CloseClipboard()
  result.put({'ok':True,'rounds':20,'formats':['Unicode','custom','RTF','HTML','DIB'],
    'marker_copy_replace_rounds':10,'delayed_read_milliseconds':650,'text_survives_helper_exit':True,
    'frozen_windowed':len(sys.argv)>1,'same_helper':True})
 except Exception as error:result.put({'ok':False,'phase':phase,'error':str(error)})
 finally:broker.close()

report={'ok':False};restored=False
try:
 outer._put(prefix+'original')
 backend._open_clipboard()
 try:
  for fmt,data in fixture_formats.items():win32clipboard.SetClipboardData(fmt,data)
  outer.ours=backend.ctypes.windll.user32.GetClipboardSequenceNumber()
 finally:win32clipboard.CloseClipboard()
 thread=threading.Thread(target=rounds);thread.start()
 deadline=time.monotonic()+25
 while thread.is_alive() and time.monotonic()<deadline:
  win32gui.PumpWaitingMessages();thread.join(.01)
 if thread.is_alive():raise TimeoutError('test helper timed out')
 report=result.get_nowait()
finally:
 broker.close()
 if outer.ours is not None:
  owned=False
  backend._open_clipboard()
  try:
   if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT):
    text=win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
    if text.startswith(prefix):
     owned=True;outer.ours=backend.ctypes.windll.user32.GetClipboardSequenceNumber()
  finally:win32clipboard.CloseClipboard()
  if owned:restored=outer._restore()
  else:report['newer_user_copy_preserved']=True
 outer.original=None;backend.OWNER_WINDOW=0;user.DestroyWindow(window)
report['supervisor_restored_original']=restored
print(json.dumps(report))
sys.exit(0 if report.get('ok') else 1)

