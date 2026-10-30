"""Completed empty copies are selection results, not transport failures.

All clipboard APIs are fakes; no live clipboard or document is accessed.
"""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import clipboard_lease as common
import clipboard_native as native


for implementation in (common.ClipboardLease,native.ClipboardState):
    state={'seq':10,'owner':42,'pid':123,'text':None,'formats':0,'closed':0,'read':0}
    def process_id(hwnd,pointer):
        pointer._obj.value=state['pid']
        return 1
    user=NS(GetClipboardSequenceNumber=lambda:state['seq'],
            GetClipboardOwner=lambda:state['owner'],
            GetWindowThreadProcessId=process_id)
    def read(fmt):
        state['read']+=1
        assert state['text'] is not None
        return state['text']
    def close():state['closed']+=1
    clipboard=NS(CF_UNICODETEXT=13,CloseClipboard=close,
                 CountClipboardFormats=lambda:state['formats'],
                 IsClipboardFormatAvailable=lambda fmt:state['text'] is not None,
                 GetClipboardData=read)
    value=object.__new__(implementation)
    value.ours=10
    if implementation is native.ClipboardState:value.api=(user,None,None)
    with patch.object(common,'_open_clipboard',lambda:None), \
         patch.object(common,'win32clipboard',clipboard), \
         patch.object(native,'win32clipboard',clipboard), \
         patch.object(common.ctypes,'WinDLL',lambda *a,**kw:user), \
         patch.object(common.ctypes,'windll',NS(user32=user)):
        # An unchanged marker means no response yet, even with old text present.
        state['text']='old unrelated text'
        assert value._read_copy((123,)) is None
        assert state['read']==0 and value.ours==10
        # A focused editor can clear clipboard formats for an empty selection.
        state.update(seq=11,text=None)
        assert value._read_copy((123,))==''
        assert value.ours==11 and state['read']==0
        # A subsequent selection copy is still accepted with exact separators.
        state.update(seq=12,text='선택한 문장 😀\r\n',formats=1)
        assert value._read_copy((123,))=='선택한 문장 😀\r\n'
        assert value.ours==12 and state['read']==1
        # A foreign owner is never converted to an empty-selection result.
        state.update(seq=13,pid=999,text=None)
        try:value._read_copy((123,))
        except RuntimeError as error:assert '다른 프로그램' in str(error)
        else:raise AssertionError('foreign clipboard owner was accepted')
        assert value.ours==12 and state['closed']==4
        # An image/custom object is a real selection, not an empty caret.
        state.update(seq=14,pid=123,text=None,formats=2)
        try:value._read_copy((123,))
        except ValueError as error:assert '복사할 텍스트' in str(error)
        else:raise AssertionError('object copy incorrectly requested automatic selection')
        assert value.ours==14 and state['closed']==5 and state['read']==1

print('empty focused copy, pending marker, exact Unicode, foreign owner, object selection: PASS (native + legacy)')
