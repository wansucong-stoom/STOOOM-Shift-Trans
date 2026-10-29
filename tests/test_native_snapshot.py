"""Real HGLOBAL allocation with an in-memory clipboard stand-in; no live clipboard."""
import pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_native as n
real_user,kernel,gdi=n._api()
state={'handles':{},'empties':0,'sets':0}
class User:
 def GetClipboardData(self,fmt):
  assert fmt!=2,'unnecessary synthesized bitmap request'
  return state['handles'].get(fmt,0)
 def SetClipboardData(self,fmt,handle):
  state['handles'][fmt]=handle;state['sets']+=1;return handle
class Clip:
 def EnumClipboardFormats(self,previous):
  formats=list(state['handles'])
  if previous==0:return formats[0] if formats else 0
  index=formats.index(previous)+1
  return formats[index] if index<len(formats) else 0
 def GetClipboardFormatName(self,fmt):return {0xc001:'HTML Format',0xc002:'Rich Text Format',0xc003:'DataObject'}[fmt]
 def EmptyClipboard(self):
  state['empties']+=1
  for fmt,handle in state['handles'].items():
   if handle and fmt!=2:kernel.GlobalFree(handle)
  state['handles']={}
n._api=lambda:(User(),kernel,gdi);n.win32clipboard=Clip()
allocator=n.Snapshot()
fixtures={13:('원문😀\0').encode('utf-16-le'),0xc001:b'<b>formatted HTML</b>\0',
          0xc002:b'{\\rtf1 formatted RTF}\0',8:b'DIB fixture data'}
def reset():
 for fmt,handle in state['handles'].items():
  if handle and fmt!=2:kernel.GlobalFree(handle)
 state.update(handles={fmt:allocator._allocate(data) for fmt,data in fixtures.items()},empties=0,sets=0)
try:
 reset();state['handles'][2]=0
 snapshot=n.Snapshot.capture()
 assert {fmt:data[:len(fixtures[fmt])] for fmt,kind,data in snapshot.items}==fixtures
 snapshot.write(lambda:None)
 assert state['empties']==1 and state['sets']==len(fixtures)
 copied=n.Snapshot.capture()
 assert {fmt:data[:len(fixtures[fmt])] for fmt,kind,data in copied.items}==fixtures

 # A failure allocating any restoration handle must happen before emptying.
 reset();snapshot=n.Snapshot.capture();allocate=snapshot._allocate;calls=[]
 def fail_second(data):
  calls.append(data)
  if len(calls)==2:raise MemoryError('injected allocation failure')
  return allocate(data)
 snapshot._allocate=fail_second
 try:snapshot.write(lambda:None)
 except MemoryError:pass
 else:raise AssertionError('allocation failure was hidden')
 assert state['empties']==0 and state['sets']==0
 assert n.Snapshot.capture().items[0][2].startswith(fixtures[13])

 # Unsupported owner-dependent data is rejected while everything is intact.
 for fmt in (0x80,0x201,0x301):
  reset();state['handles'][fmt]=0
  try:n.Snapshot.capture()
  except RuntimeError:pass
  else:raise AssertionError('owner-managed format accepted')
  assert state['empties']==0
finally:
 for fmt,handle in state['handles'].items():
  if handle and fmt!=2:kernel.GlobalFree(handle)
print('Native snapshot: real HGLOBAL Unicode/HTML/RTF/DIB copies, ownership transfer, allocation failure before empty, and unsupported formats leave clipboard intact: PASS')
