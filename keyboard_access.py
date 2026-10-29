"""Keyboard/clipboard input path, independent of TSF text stores and app names.

Keep the original selection until translation is ready. Recopy it immediately
before one paste. Input generated here is tagged so it cannot retrigger STOOM.
"""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import time
import clipboard_lease
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
        self.owner_pids=[]
        for hwnd in (focus.foreground,focus.keyboard_window):
            pid=W.DWORD();self.u.GetWindowThreadProcessId(hwnd,C.byref(pid));self.owner_pids.append(pid.value)
    def current(self):return focus_guard.unchanged(self.focus)
    def safe(self):
        name=C.create_unicode_buffer(256)
        self.u.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int];self.u.GetClassNameW.restype=C.c_int
        self.u.GetClassNameW(self.focus.keyboard_window,name,len(name))
        if name.value.lower()=='edit' or name.value.lower().startswith('richedit'):
            style=self.u.GetWindowLongW(self.focus.keyboard_window,-16)
            if style&0x20:raise KeyboardError('보안 입력창입니다.')
            if style&0x800:raise KeyboardError('읽기 전용 입력창입니다.')
        if self.safety() is False and self.caret_point() is None:
            raise KeyboardError('텍스트 입력 위치를 확인하지 못했습니다.')
    def modifiers(self):return any(self.u.GetAsyncKeyState(v)&0x8000 for v in (SHIFT,CTRL,ALT,0x5b,0x5c))
    def anchor(self):
        info=focus_guard.GUITHREADINFO();info.cbSize=C.sizeof(info)
        if not self.u.GetGUIThreadInfo(self.focus.thread_id,C.byref(info)):return None
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
        batch=(INPUT*len(events))(*events)
        if self.u.SendInput(len(batch),batch,C.sizeof(INPUT))!=len(batch):
            raise KeyboardError('Windows가 입력 전달을 허용하지 않았습니다.')
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
        point=self.caret_point()
        if point:
            original=W.POINT();saved=bool(self.u.GetCursorPos(C.byref(original)))
            guard();self._move(point)
            try:
                for _ in range(3):
                    guard();current=W.POINT()
                    if not self.u.GetCursorPos(C.byref(current)) or abs(current.x-point[0])>1 or abs(current.y-point[1])>1:
                        raise Cancelled('마우스 위치가 바뀌어 자동 선택을 취소했습니다.')
                    self.click();pause(.025)
            finally:
                current=W.POINT()
                if saved and self.current() and self.u.GetCursorPos(C.byref(current)) and (current.x,current.y)==point:
                    self._move((original.x,original.y))
        else:
            # Same navigation keys for every application; never Ctrl+A.
            guard();self.chord(CTRL,DOWN);pause(.025)
            guard();self.chord(CTRL,SHIFT,UP);pause(.025)


class Driver:
    def __init__(self,env,lease_factory=clipboard_lease.ClipboardLease):
        self.env=env;self.lease_factory=lease_factory
    def guard(self,revision):
        if not self.env.current() or self.env.activity()[0]!=revision:
            raise Cancelled('입력 위치나 내용이 바뀌어 번역을 취소했습니다.')
    def pause(self,seconds,revision):
        end=self.env.now()+seconds
        while self.env.now()<end:
            self.guard(revision);self.env.sleep(min(.01,max(0,end-self.env.now())))
        self.guard(revision)
    def copy(self,lease,revision,timeout=.16):
        self.guard(revision);lease.arm_copy();self.guard(revision);self.env.chord(CTRL,ord('C'))
        end=self.env.now()+timeout
        while True:
            self.guard(revision)
            try:text=lease.read_copy(self.env.owner_pids)
            except OSError:text=None  # Another process can briefly hold OpenClipboard.
            if text is not None:return text
            if self.env.now()>=end:return None
            self.pause(.01,revision)
    def capture(self,revision,commit_space=True):
        self.guard(revision);self.env.safe()
        end=self.env.now()+.4
        while self.env.modifiers():
            if self.env.now()>=end:raise KeyboardError('단축키에서 손을 뗀 뒤 다시 시도하세요.')
            self.pause(.01,revision)
        lease=self.lease_factory()
        try:
            text=self.copy(lease,revision)
            automatic=text is None or not text
            if automatic:
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
                self.env.select(lambda:self.guard(revision),lambda s:self.pause(s,revision))
                text=self.copy(lease,revision)
            if not text or not text.strip():raise KeyboardError('선택·복사할 글이 없습니다. 글을 선택한 뒤 다시 시도하세요.')
            if len(text.encode('utf-16-le'))//2>MAX_SOURCE or '\0' in text or '\ufffc' in text:
                raise KeyboardError('선택한 텍스트가 너무 길거나 텍스트 이외의 개체가 포함되어 있습니다.')
            # Two actual copies, not a provider's cached range/value.
            if self.copy(lease,revision)!=text:raise Cancelled('복사된 원문이 바뀌어 번역을 취소했습니다.')
            self.guard(revision)
            return Snapshot(text,self.env.focus,revision,self.env.anchor(),automatic)
        finally:lease.restore()
    def apply(self,snapshot,translation):
        revision=snapshot.revision;self.guard(revision);self.env.safe()
        if not isinstance(translation,str) or not translation.strip() or '\0' in translation or len(translation.encode('utf-16-le'))//2>16000:
            raise KeyboardError('번역 결과가 비어 있거나 너무 깁니다.')
        if self.env.modifiers():raise Cancelled('새 키보드 입력이 있어 교체를 취소했습니다.')
        if snapshot.anchor is not None and self.env.anchor()!=snapshot.anchor:
            raise Cancelled('선택 위치가 바뀌어 교체를 취소했습니다.')
        lease=self.lease_factory()
        try:
            if self.copy(lease,revision)!=snapshot.text:raise Cancelled('선택된 원문이 바뀌어 교체를 취소했습니다.')
            lease.replace_owned(snapshot.text,translation)
            self.guard(revision)
            if snapshot.anchor is not None and self.env.anchor()!=snapshot.anchor:
                raise Cancelled('선택 위치가 바뀌어 교체를 취소했습니다.')
            self.env.chord(CTRL,ord('V'))
            # Do not paste twice if the target provides no acknowledgement.
            self.env.sleep(.2)
            return '키보드 경로 · 번역문 전달 완료'
        finally:lease.restore()
