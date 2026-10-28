"""Read and revalidate UI Automation text ranges; no mutation or clipboard access."""
from dataclasses import dataclass

START = 0
END = 1
TEXT_UNIT_PARAGRAPH = 4

@dataclass
class RangeSnapshot:
    runtime_id: tuple
    caret_or_selection: object
    target: object
    text: str
    selected: bool

def capture(runtime_id, text_pattern, document_mode):
    selections = text_pattern.GetSelection()
    if selections.Length != 1:
        raise ValueError('텍스트 선택 범위를 하나로 확인할 수 없습니다.')
    anchor = selections.GetElement(0).Clone()
    target = anchor.Clone()
    selected = bool(target.GetText(-1))
    if not document_mode:
        target = text_pattern.DocumentRange.Clone()
    elif not selected:
        target.ExpandToEnclosingUnit(TEXT_UNIT_PARAGRAPH)
    text = target.GetText(-1)
    if not text or not text.strip():
        raise ValueError('현재 선택 또는 문단의 텍스트를 읽을 수 없습니다.')
    return RangeSnapshot(tuple(runtime_id),anchor,target,text,selected)

def unchanged(snapshot, runtime_id, text_pattern):
    if tuple(runtime_id) != snapshot.runtime_id:
        return False
    selections = text_pattern.GetSelection()
    if selections.Length != 1:
        return False
    current=selections.GetElement(0)
    if current.CompareEndpoints(START,snapshot.caret_or_selection,START) != 0:
        return False
    if current.CompareEndpoints(END,snapshot.caret_or_selection,END) != 0:
        return False
    return snapshot.target.GetText(-1) == snapshot.text


def selection_matches(selection, target, expected, document_range):
    """Verify selected text and location, including provider endpoint quirks."""
    if selection.Length != 1 or not expected:
        return False
    import unicodedata
    def norm(text):
        return unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n'))
    try:
        current=selection.GetElement(0)
        if norm(current.GetText(-1)) != norm(expected):
            return False
        if current.CompareEndpoints(START,target,START)==0 and current.CompareEndpoints(END,target,END)==0:
            return True
        # When a provider uses different endpoint representations, compare
        # the entire text preceding each range to avoid accepting an identical
        # but different occurrence elsewhere in a document.
        before_target=document_range.Clone()
        before_target.MoveEndpointByRange(END,target,START)
        before_current=document_range.Clone()
        before_current.MoveEndpointByRange(END,current,START)
        return norm(before_target.GetText(-1)) == norm(before_current.GetText(-1))
    except Exception:
        return False
