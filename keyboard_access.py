"""Keyboard/clipboard input path, independent of TSF text stores and app names.

Keep the original selection until translation is ready. Recopy it immediately
before one paste. Input generated here is tagged so it cannot retrigger STOOM.
"""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import time
import clipboard_process
import focus_guard

INPUT_TAG = 0x53544F4D
CTRL, SHIFT, ALT = 0x11, 0x10, 0x12
LEFT, UP, RIGHT, DOWN, HOME, END = 0x25, 0x26, 0x27, 0x28, 0x24, 0x23
MAX_SOURCE = 8000


class Cancelled(Exception): pass
class KeyboardError(Exception): pass


class KEYBDINPUT(C.Structure):
    _fields_=[('vk',W.WORD),('scan',W.WORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class MOUSEINPUT(C.Structure):
    _fields_=[('dx',W.LONG),('dy',W.LONG),('data',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
class INPUTUNION(C.Union):
    _fields_=[('key',KEYBDINPUT),('mouse',MOUSEINPUT)]
class INPUT(C.Structure):
    _anonymous_=('value',)
    _fields_=[('kind',W.DWORD),('value',INPUTUNION)]


@dataclass(frozen=True)
class Snapshot:
    text: str
    focus: object
    revision: int
    anchor: object
    selected_automatically: bool


def select_paragraph(env,guard,pause):
    # Common paragraph navigation for no-caret hosts and a click that selected
    # no usable text. Do not guess with line/paragraph-specific alternatives.
    guard();env.chord(CTRL,DOWN);pause(.025)
    guard();env.chord(CTRL,SHIFT,UP);pause(.025)
    return 'backward'


class Windows:
    now=staticmethod(time.monotonic)
    sleep=staticmethod(time.sleep)
    def __init__(self,focus,activity,safety):
        self.focus=focus;self.activity=activity;self.safety=safety
        self.u=C.WinDLL('user32',use_last_error=True)
        self.u.SendInput.argtypes=[W.UINT,C.POINTER(INPUT),C.c_int];self.u.SendInput.restype=W.UINT
        self.u.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)];self.u.GetWindowThreadProcessId.restype=W.DWORD
        self.u.GetGUIThreadInfo.argtypes=[W.DWORD,C.POINTER(focus_guard.GUITHREADINFO)];self.u.GetGUIThreadInfo.restype=W.BOOL
        self.u.ClientToScreen.argtypes=[W.HWND,C.POINTER(W.POINT)];self.u.ClientToScreen.restype=W.BOOL
        self.u.GetCursorPos.argtypes=[C.POINTER(W.POINT)];self.u.GetCursorPos.restype=W.BOOL
        self.u.WindowFromPoint.argtypes=[W.POINT];self.u.WindowFromPoint.restype=W.HWND
        self.u.GetAncestor.argtypes=[W.HWND,W.UINT];self.u.GetAncestor.restype=W.HWND
        self.u.GetAsyncKeyState.argtypes=[C.c_int];self.u.GetAsyncKeyState.restype=C.c_short
        self.u.GetWindowLongW.argtypes=[W.HWND,C.c_int];self.u.GetWindowLongW.restype=W.LONG
        self.u.GetClipboardSequenceNumber.argtypes=[];self.u.GetClipboardSequenceNumber.restype=W.DWORD
        self.owner_pids=[]
        for hwnd in (focus.foreground,focus.keyboard_window):
            pid=W.DWORD();self.u.GetWindowThreadProcessId(hwnd,C.byref(pid));self.owner_pids.append(pid.value)
    def current(self):return focus_guard.same_foreground(self.focus)
    def current_focus(self):
        try:return focus_guard.capture()
        except (OSError,ValueError):return None
    def clipboard_sequence(self):return self.u.GetClipboardSequenceNumber()
    def safe(self):
        if self.safety() is False and self.caret_point() is None:
            raise KeyboardError('텍스트 입력 위치를 확인하지 못했습니다.')
    def modifiers(self):return any(self.u.GetAsyncKeyState(v)&0x8000 for v in (SHIFT,CTRL,ALT,0x5b,0x5c))
    def anchor(self):
        current=self.current_focus()
        if current is None or current.foreground!=self.focus.foreground:return None
        info=focus_guard.GUITHREADINFO();info.cbSize=C.sizeof(info)
        if not self.u.GetGUIThreadInfo(current.thread_id,C.byref(info)):return None
        r=info.rcCaret
        if not info.hwndCaret or r.bottom<=r.top:return None
        return (int(info.hwndCaret or 0),r.left,r.top,r.right,r.bottom)
    def caret_point(self):
        anchor=self.anchor()
        if not anchor or not anchor[0] or anchor[4]<=anchor[2]:return None
        point=W.POINT(anchor[1],(anchor[2]+anchor[4])//2)
        if not self.u.ClientToScreen(anchor[0],C.byref(point)):return None
        window=self.u.WindowFromPoint(point)
        if not window or self.u.GetAncestor(window,2)!=self.focus.foreground:return None
        return point.x,point.y
    def _send(self,events):
        if not events:return
        batch=(INPUT*len(events))(*events)
        accepted=int(self.u.SendInput(len(batch),batch,C.sizeof(INPUT)))
        if accepted!=len(batch):
            report=getattr(self,'report',lambda *args,**details:None)
            report('input_partial',accepted=accepted,expected=len(batch))
            # SendInput may accept only a prefix. Release only downs in that
            # prefix which have no matching up. Never retry a copy/paste/down
            # or release unrelated physical keys/buttons.
            remaining=self._unreleased(events[:max(0,min(accepted,len(events)))])
            blocked=0
            for _ in range(len(remaining)+1):
                if not remaining:break
                cleanup=(INPUT*len(remaining))(*remaining)
                released=int(self.u.SendInput(len(cleanup),cleanup,C.sizeof(INPUT)))
                report('input_release',accepted=released,expected=len(cleanup))
                if not released:
                    blocked+=1
                    if blocked>=2:break
                remaining=remaining[max(0,min(released,len(remaining))):]
            raise KeyboardError('Windows가 입력 전달을 허용하지 않았습니다.')
    @staticmethod
    def _unreleased(events):
        pending={}
        for event in events:
            if event.kind==1:
                key=event.key;identity=('key',key.vk,key.scan,key.flags & ~2)
                if key.flags & 2:pending.pop(identity,None)
                else:
                    release=INPUT();release.kind=1
                    release.key=KEYBDINPUT(key.vk,key.scan,key.flags|2,0,INPUT_TAG)
                    pending[identity]=release
            elif event.kind==0:
                # STOOM emits a tagged left click, never other mouse buttons.
                if event.mouse.flags & 4:pending.pop(('left',),None)
                elif event.mouse.flags & 2:
                    release=INPUT();release.kind=0
                    release.mouse=MOUSEINPUT(0,0,0,4,0,INPUT_TAG)
                    pending[('left',)]=release
        return list(reversed(pending.values()))
    def chord(self,*keys):
        def event(vk,up):
            value=INPUT();value.kind=1
            value.key=KEYBDINPUT(vk,0,(2 if up else 0)|(1 if vk in (LEFT,UP,RIGHT,DOWN,HOME,END) else 0),0,INPUT_TAG)
            return value
        self._send([event(k,False) for k in keys]+[event(k,True) for k in reversed(keys)])
    def _move(self,point):
        left,top=self.u.GetSystemMetrics(76),self.u.GetSystemMetrics(77)
        width,height=self.u.GetSystemMetrics(78),self.u.GetSystemMetrics(79)
        if width<2 or height<2:raise KeyboardError('화면 좌표를 확인하지 못했습니다.')
        value=INPUT();value.kind=0
        value.mouse=MOUSEINPUT(round((point[0]-left)*65535/(width-1)),round((point[1]-top)*65535/(height-1)),0,0x8000|0x4000|1,0,INPUT_TAG)
        self._send([value])
    def click(self):
        events=[]
        for flag in (2,4):
            value=INPUT();value.kind=0;value.mouse=MOUSEINPUT(0,0,0,flag,0,INPUT_TAG);events.append(value)
        self._send(events)
    def select(self,guard,pause):
        # A caret coordinate can overlap a table/object handle. Default input
        # must never turn paragraph selection into an object double click.
        return select_paragraph(self,guard,pause)
    def select_by_click(self,guard,pause):
        """Explicit diagnostic helper; the application route never calls it."""
        point=self.caret_point()
        if point:
            original=W.POINT();saved=bool(self.u.GetCursorPos(C.byref(original)))
            guard();self._move(point)
            try:
                for _ in range(3):
                    guard();current=W.POINT()
                    if not self.u.GetCursorPos(C.byref(current)) or (current.x,current.y)!=point:
                        self._move(point)
                    guard()
                    self.click();pause(.025)
            finally:
                # Never pull the pointer back after a real click/drag/typing
                # cancelled the request, or after the user moved it away.
                restore=True
                try:guard()
                except Cancelled:restore=False
                current=W.POINT()
                if restore and saved and self.current() and self.u.GetCursorPos(C.byref(current)) and (current.x,current.y)==point:
                    self._move((original.x,original.y))
            # Click selection orientation belongs to the host editor.
            return 'unknown'
        else:
            return select_paragraph(self,guard,pause)


class Driver:
    def __init__(self,env,lease_factory=clipboard_process.ClipboardLease,report=None):
        self.env=env;self.lease_factory=lease_factory;self._report=report
        self.env.report=self.record
    def record(self,phase,**details):
        if self._report is not None:
            try:self._report(phase,**details)
            except Exception:pass  # Diagnostics must never affect an edit.
    def guard(self,revision):
        if not self.env.current():
            self.record('guard_cancelled',cause='focus',revision=revision,focus=self.env.focus,
                        current_focus=getattr(self.env,'current_focus',lambda:None)())
            raise Cancelled('입력창의 포커스가 바뀌어 번역을 취소했습니다.')
        current=self.env.activity()[0]
        if current!=revision:
            self.record('guard_cancelled',cause=getattr(self.env,'activity_cause',lambda:'unknown')(),revision=revision,current_revision=current)
            raise Cancelled('새 키보드 입력이나 클릭·스크롤이 감지되어 번역을 취소했습니다.')
    def pause(self,seconds,revision):
        end=self.env.now()+seconds
        while self.env.now()<end:
            self.guard(revision);self.env.sleep(min(.01,max(0,end-self.env.now())))
        self.guard(revision)
    def copy(self,lease,revision,timeout=.16):
        self.record('copy_started',revision=revision)
        self.guard(revision);lease.arm_copy();self.guard(revision);self.env.chord(CTRL,ord('C'))
        end=self.env.now()+timeout
        while True:
            self.guard(revision)
            try:text=lease.read_copy(self.env.owner_pids)
            except OSError:text=None  # Another process can briefly hold OpenClipboard.
            if text is not None:
                self.record('copy_done',source_chars=len(text))
                return text
            if self.env.now()>=end:
                self.record('copy_timeout',cause='clipboard')
                return None
            self.pause(.01,revision)
    def capture(self,revision,commit_space=False):
        self.record('capture_started',revision=revision)
        self.guard(revision);self.env.safe()
        end=self.env.now()+.4
        while self.env.modifiers():
            if self.env.now()>=end:raise KeyboardError('단축키에서 손을 뗀 뒤 다시 시도하세요.')
            self.pause(.01,revision)
        lease=self.lease_factory()
        try:
            text=self.copy(lease,revision)
            automatic=text is None or not text
            strategy=None
            if automatic:
                self.record('selection_started')
                before_space=self.env.anchor()
                if commit_space and before_space is not None:
                    self.guard(revision);self.env.chord(0x20);self.pause(.025,revision)
                    if self.env.anchor()==before_space:
                        raise KeyboardError('조합 확정용 공백의 추가를 확인하지 못했습니다. 입력창을 확인하세요.')
                    self.env.chord(SHIFT,LEFT);self.pause(.025,revision)
                    space=self.copy(lease,revision)
                    if space!=' ':
                        raise KeyboardError('조합 확정용 공백을 확인하지 못했습니다. 입력창을 확인하세요.')
                    self.guard(revision);self.env.chord(0x08);self.pause(.025,revision)
                strategy=self.env.select(lambda:self.guard(revision),lambda s:self.pause(s,revision))
                self.record('selection_sent')
                self.record('selection_backward' if strategy=='backward' else 'selection_direction_unknown')
                text=self.copy(lease,revision)
                if strategy=='unknown' and (not text or not text.strip()):
                    self.record('selection_keyboard_fallback')
                    # A copied whitespace range is an actual selection; collapse
                    # it first. A timeout/empty copy does not prove a selection,
                    # so Left could otherwise move into a previous paragraph.
                    if text:
                        self.guard(revision);self.env.chord(LEFT)
                    strategy=select_paragraph(self.env,lambda:self.guard(revision),lambda s:self.pause(s,revision))
                    self.record('selection_backward')
                    text=self.copy(lease,revision)
            if not text or not text.strip():raise KeyboardError('선택·복사할 글이 없습니다. 글을 선택한 뒤 다시 시도하세요.')
            # Preserve the destination paragraph's existing formatting by
            # leaving a selected trailing paragraph break in the document.
            # A selected edge moves differently in some editors: only proceed
            # if an actual second copy proves exactly the intended shrink.
            if text.endswith(('\r','\n','\u2028','\u2029')):
                without_break=text[:-2] if text.endswith('\r\n') else text[:-1]
                if not without_break.strip():raise KeyboardError('번역할 글이 없습니다.')
                # Hosts can expose a forward block even after Ctrl+Shift+Up.
                # Try the working manual-selection path before assuming which
                # endpoint is active. Never collapse/reselect using Down: logs
                # showed a complete paragraph becoming only its delimiter.
                self.record('paragraph_trim_started')
                self.guard(revision);self.env.chord(SHIFT,LEFT);self.pause(.025,revision)
                shrunk=self.copy(lease,revision)
                if shrunk!=without_break:
                    # Reverse only a probe that actually changed the selection.
                    # At document start Shift+Left can be a no-op.
                    if shrunk!=text:
                        self.guard(revision);self.env.chord(SHIFT,RIGHT);self.pause(.025,revision)
                        if self.copy(lease,revision)!=text:
                            self.record('paragraph_restore_failed')
                            raise KeyboardError('문단을 자동으로 인식하지 못했습니다. 원하는 문장을 드래그해 직접 선택한 뒤 다시 시도해 주세요.')
                    if not (automatic and strategy=='backward'):
                        raise KeyboardError('문단을 자동으로 인식하지 못했습니다. 원하는 문장을 드래그해 직접 선택한 뒤 다시 시도해 주세요.')
                    self.record('paragraph_end_reselect_started')
                    # Collapse to the copied end, step over exactly one
                    # boundary (CRLF is one caret step), and select backward.
                    # A synthetic clipboard newline or unexpected key behavior
                    # cannot silently drop a character: recopy must match.
                    for keys in ((RIGHT,),(LEFT,),(CTRL,SHIFT,UP)):
                        self.guard(revision);self.env.chord(*keys);self.pause(.025,revision)
                    shrunk=self.copy(lease,revision)
                    if shrunk!=without_break:
                        self.record('paragraph_end_reselect_failed',source_chars=len(shrunk) if shrunk is not None else 0)
                        raise KeyboardError('문단을 자동으로 인식하지 못했습니다. 원하는 문장을 드래그해 직접 선택한 뒤 다시 시도해 주세요.')
                self.record('paragraph_trim_confirmed',source_chars=len(shrunk))
                text=shrunk
            if len(text.encode('utf-16-le'))//2>MAX_SOURCE or '\0' in text or '\ufffc' in text:
                raise KeyboardError('선택한 텍스트가 너무 길거나 텍스트 이외의 개체가 포함되어 있습니다.')
            # Two actual copies, not a provider's cached range/value.
            if self.copy(lease,revision)!=text:raise Cancelled('복사된 원문이 바뀌어 번역을 취소했습니다.')
            self.guard(revision)
            self.record('source_confirmed',source_chars=len(text))
            return Snapshot(text,self.env.focus,revision,self.env.anchor(),automatic)
        finally:
            lease.restore()
            self.record('capture_clipboard_restored')
    def apply(self,snapshot,translation):
        self.record('apply_started',source_chars=len(snapshot.text),output_chars=len(translation) if isinstance(translation,str) else 0)
        revision=snapshot.revision;self.guard(revision);self.env.safe()
        if not isinstance(translation,str) or not translation.strip() or '\0' in translation or len(translation.encode('utf-16-le'))//2>16000:
            raise KeyboardError('번역 결과가 비어 있거나 너무 깁니다.')
        if self.env.modifiers():raise Cancelled('새 키보드 입력이 있어 교체를 취소했습니다.')
        lease=self.lease_factory()
        try:
            if self.copy(lease,revision)!=snapshot.text:raise Cancelled('선택된 원문이 바뀌어 교체를 취소했습니다.')
            self.record('apply_source_confirmed',source_chars=len(snapshot.text))
            lease.replace_owned(snapshot.text,translation)
            self.guard(revision)
            # Ctrl+V is asynchronous. The target may not read the clipboard
            # until much later, so restoring an image after a fixed delay can
            # paste that image instead. Keep the materialized translation.
            sequence=lease.keep_translation()
            self.record('translation_clipboard_ready',output_chars=len(translation))
            self.guard(revision)
            if hasattr(self.env,'clipboard_sequence') and self.env.clipboard_sequence()!=sequence:
                raise Cancelled('클립보드가 바뀌어 교체를 취소했습니다.')
            self.env.chord(CTRL,ord('V'))
            self.record('paste_sent')
            # Do not paste twice if the target provides no acknowledgement.
            return '키보드 경로 · 번역문 전달 완료'
        finally:lease.restore()
