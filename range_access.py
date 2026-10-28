"""Capture immutable text/location facts alongside live UIA ranges.

UIA range objects may move after selection or IME updates. A saved range is
never treated as immutable source text when validating a later operation.
"""
from dataclasses import dataclass
import hashlib
import unicodedata

START=0
END=1
TEXT_UNIT_PARAGRAPH=4

def normalize(text):
    return unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n'))

def same_text(a,b):
    return normalize(a)==normalize(b)

def _prefix(text_pattern, text_range):
    before=text_pattern.DocumentRange.Clone()
    before.MoveEndpointByRange(END,text_range,START)
    text=normalize(before.GetText(-1))
    return (len(text),hashlib.sha256(text.encode('utf-8')).digest())

@dataclass
class RangeSnapshot:
    runtime_id: tuple
    caret_or_selection: object
    target: object
    text: str
    selected: bool
    document_mode: bool
    anchor_prefix: tuple
    anchor_text: str
    target_prefix: tuple

    def fingerprint(self):
        return (self.runtime_id,normalize(self.text),self.document_mode,
                self.anchor_prefix,normalize(self.anchor_text),self.target_prefix)

def capture(runtime_id,text_pattern,document_mode):
    selections=text_pattern.GetSelection()
    if selections.Length!=1:
        raise ValueError('텍스트 선택 범위를 하나로 확인할 수 없습니다.')
    anchor=selections.GetElement(0).Clone()
    target=anchor.Clone()
    anchor_text=anchor.GetText(-1)
    selected=bool(anchor_text)
    if not document_mode:
        target=text_pattern.DocumentRange.Clone()
    elif not selected:
        target.ExpandToEnclosingUnit(TEXT_UNIT_PARAGRAPH)
    text=target.GetText(-1)
    if not text or not text.strip():
        raise ValueError('현재 선택 또는 문단의 텍스트를 읽을 수 없습니다.')
    return RangeSnapshot(tuple(runtime_id),anchor,target,text,selected,document_mode,
                         _prefix(text_pattern,anchor),anchor_text,_prefix(text_pattern,target))

def unchanged(snapshot,runtime_id,text_pattern):
    if tuple(runtime_id)!=snapshot.runtime_id:
        return False
    try:
        current=capture(runtime_id,text_pattern,snapshot.document_mode)
        return current.fingerprint()==snapshot.fingerprint()
    except Exception:
        return False

def after_selection_source_matches(snapshot,runtime_id,text_pattern):
    """Validate fresh provider data after our own deliberate selection change."""
    if tuple(runtime_id)!=snapshot.runtime_id:
        return False
    try:
        if not snapshot.document_mode:
            return same_text(text_pattern.DocumentRange.GetText(-1),snapshot.text)
        selections=text_pattern.GetSelection()
        if selections.Length!=1:return False
        current=selections.GetElement(0)
        return same_text(current.GetText(-1),snapshot.text) and _prefix(text_pattern,current)==snapshot.target_prefix
    except Exception:
        return False

def selection_matches(selection,target,expected,document_range):
    if selection.Length!=1 or not expected:return False
    try:
        current=selection.GetElement(0)
        if not same_text(current.GetText(-1),expected):return False
        if current.CompareEndpoints(START,target,START)==0 and current.CompareEndpoints(END,target,END)==0:return True
        a=document_range.Clone();a.MoveEndpointByRange(END,target,START)
        b=document_range.Clone();b.MoveEndpointByRange(END,current,START)
        return same_text(a.GetText(-1),b.GetText(-1))
    except Exception:return False
