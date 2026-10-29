"""Bounded same-user IPC to the TSF service in the focused app's GUI thread.

Only an explicit translation gesture captures text. No keyboard text logging,
network, injection, or clipboard is involved. A missing service can fall back to
UIA. Once TSF accepted a request, uncertain results never fall back to a paste.
"""
import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import uuid

MAGIC=0x53544636
SERVICE_ID='{89EB3B8D-A777-47D6-A4C2-1B63512706B8}'
WINDOW_CLASS='STOOM.TextService.1'
TF_E_LOCKED=0x80040500
E_NOINTERFACE=0x80004002

class Packet(C.Structure):
    _pack_=8
    _fields_=[('magic',C.c_uint32),('version',C.c_uint32),('operation',C.c_uint32),
              ('status',C.c_int32),('deadline',C.c_uint64),('foreground',C.c_uint64),
              ('keyboard',C.c_uint64),('thread',C.c_uint32),('client',C.c_uint32),
              ('length',C.c_uint32),('complete',C.c_uint32),('snapshot',C.c_ubyte*16),
              ('text',C.c_wchar*16001)]
class Notice(C.Structure):
    _fields_=[('magic',C.c_uint32),('name',C.c_wchar*96)]
class CopyData(C.Structure):
    _fields_=[('data',C.c_size_t),('size',W.DWORD),('pointer',C.c_void_p)]
class SecurityAttributes(C.Structure):
    _fields_=[('length',W.DWORD),('descriptor',C.c_void_p),('inherit',W.BOOL)]

class Unavailable(Exception):pass
class Pending(Exception):pass
class TsfError(Exception):pass

@dataclass(frozen=True)
class Snapshot:
    server:int
    token:bytes
    text:str

def _apis():
    k=C.WinDLL('kernel32',use_last_error=True);u=C.WinDLL('user32',use_last_error=True);a=C.WinDLL('advapi32',use_last_error=True)
    signatures=[
      (k,'CreateFileMappingW',W.HANDLE,[W.HANDLE,C.c_void_p,W.DWORD,W.DWORD,W.DWORD,W.LPCWSTR]),
      (k,'MapViewOfFile',C.c_void_p,[W.HANDLE,W.DWORD,W.DWORD,W.DWORD,C.c_size_t]),
      (k,'UnmapViewOfFile',W.BOOL,[C.c_void_p]),(k,'CloseHandle',W.BOOL,[W.HANDLE]),
      (k,'CreateEventW',W.HANDLE,[C.c_void_p,W.BOOL,W.BOOL,W.LPCWSTR]),
      (k,'WaitForSingleObject',W.DWORD,[W.HANDLE,W.DWORD]),(k,'GetTickCount64',C.c_uint64,[]),
      (k,'GetCurrentProcess',W.HANDLE,[]),(k,'LocalFree',W.HANDLE,[W.HANDLE]),
      (u,'FindWindowExW',W.HWND,[W.HWND,W.HWND,W.LPCWSTR,W.LPCWSTR]),
      (u,'GetWindowThreadProcessId',W.DWORD,[W.HWND,C.POINTER(W.DWORD)]),
      (u,'SendMessageTimeoutW',C.c_ssize_t,[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t,W.UINT,W.UINT,C.POINTER(C.c_size_t)]),
      (a,'OpenProcessToken',W.BOOL,[W.HANDLE,W.DWORD,C.POINTER(W.HANDLE)]),
      (a,'GetTokenInformation',W.BOOL,[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]),
      (a,'ConvertSidToStringSidW',W.BOOL,[C.c_void_p,C.POINTER(W.LPWSTR)]),
      (a,'ConvertStringSecurityDescriptorToSecurityDescriptorW',W.BOOL,[W.LPCWSTR,W.DWORD,C.POINTER(C.c_void_p),C.c_void_p])]
    for dll,name,result,args in signatures:
        f=getattr(dll,name);f.restype=result;f.argtypes=args
    return k,u,a

def _owner_security(k,a):
    token=W.HANDLE();sid=W.LPWSTR();sd=C.c_void_p()
    if not a.OpenProcessToken(k.GetCurrentProcess(),8,C.byref(token)):raise C.WinError(C.get_last_error())
    try:
        size=W.DWORD();a.GetTokenInformation(token,1,None,0,C.byref(size));buf=C.create_string_buffer(size.value)
        if not a.GetTokenInformation(token,1,buf,size,C.byref(size)):raise C.WinError(C.get_last_error())
        if not a.ConvertSidToStringSidW(C.cast(buf,C.POINTER(C.c_void_p))[0],C.byref(sid)):raise C.WinError(C.get_last_error())
        sddl='D:P(A;;GA;;;SY)(A;;GA;;;'+sid.value+')'
        if not a.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl,1,C.byref(sd),None):raise C.WinError(C.get_last_error())
        return SecurityAttributes(C.sizeof(SecurityAttributes),sd,False)
    finally:
        if sid:k.LocalFree(C.cast(sid,W.HANDLE))
        k.CloseHandle(token)

class Client:
    def __init__(self,sender_window):
        assert C.sizeof(Packet)==32080 and Packet.text.offset==72
        self.sender=int(sender_window)
        self.k,self.u,self.a=_apis()

    def locate(self,focus):
        pid=W.DWORD();tid=self.u.GetWindowThreadProcessId(focus.keyboard_window,C.byref(pid))
        if tid!=focus.thread_id:return None
        name=f'STOOM.TSF.{pid.value}.{tid}'
        window=self.u.FindWindowExW(W.HWND(-3),None,None,name)
        if not window:return None
        owner=W.DWORD();owner_thread=self.u.GetWindowThreadProcessId(window,C.byref(owner))
        if owner.value!=pid.value or owner_thread!=tid:return None
        return int(window)

    def exchange(self,server,focus,operation,token=b'\0'*16,text='',timeout_ms=1000):
        if len(text.encode('utf-16-le'))//2>16000 or '\0' in text:raise TsfError('TSF 번역문 길이가 올바르지 않습니다.')
        if self.locate(focus)!=server:raise Unavailable('현재 입력창의 TSF 연결이 없습니다.')
        k,u=self.k,self.u;mapping=event=view=None;security=None
        name=f'Local\\STOOM.TSF.{os.getpid()}.{uuid.uuid4().hex}'
        try:
            security=_owner_security(k,self.a)
            mapping=k.CreateFileMappingW(W.HANDLE(-1),C.byref(security),4,0,C.sizeof(Packet),name)
            if not mapping:raise C.WinError(C.get_last_error())
            if C.get_last_error()==183:raise TsfError('TSF 요청 식별자가 중복되었습니다.')
            event=k.CreateEventW(C.byref(security),True,False,name+'.done')
            if not event:raise C.WinError(C.get_last_error())
            view=k.MapViewOfFile(mapping,6,0,0,C.sizeof(Packet))
            if not view:raise C.WinError(C.get_last_error())
            packet=Packet.from_address(view)
            packet.magic=MAGIC;packet.version=1;packet.operation=operation;packet.status=-2147467259
            packet.deadline=k.GetTickCount64()+timeout_ms
            packet.foreground=focus.foreground;packet.keyboard=focus.keyboard_window;packet.thread=focus.thread_id;packet.client=os.getpid()
            packet.snapshot[:]=token;packet.length=len(text.encode('utf-16-le'))//2;packet.text=text
            notice=Notice(MAGIC,name);data=CopyData(MAGIC,C.sizeof(notice),C.addressof(notice));accepted=C.c_size_t()
            sent=u.SendMessageTimeoutW(server,0x4a,self.sender,C.addressof(data),0x0002|0x0020,min(timeout_ms,250),C.byref(accepted))
            if not sent or not accepted.value:
                raise TsfError('입력창의 TSF가 응답하지 않았습니다. 잠시 후 다시 시도하세요.')
            remaining=max(0,int(packet.deadline-k.GetTickCount64()))+100
            if k.WaitForSingleObject(event,remaining)!=0 or packet.complete!=1:
                raise TsfError('TSF 처리 확인 시간이 초과되었습니다. 중복 교체를 피하기 위해 다시 붙여넣지 않습니다.')
            if packet.length>16000:raise TsfError('TSF 응답 길이가 올바르지 않습니다.')
            status=packet.status&0xffffffff
            if status==TF_E_LOCKED:raise Pending('한글 입력 조합 완료를 기다리고 있습니다.')
            if status==E_NOINTERFACE and operation==1:raise Unavailable('이 입력창은 TSF 텍스트 문맥을 제공하지 않습니다.')
            if status==1:raise TsfError('현재 문단 또는 선택 영역에 번역할 문장이 없습니다.')
            if status&0x80000000:
                message={0x80070005:'보안 입력창 또는 읽기 전용 영역입니다.',
                         0x8007051a:'번역 중 원문이나 선택 위치가 바뀌어 교체하지 않았습니다.',
                         0x800704c7:'키보드 입력 위치가 바뀌어 교체하지 않았습니다.'}.get(status,f'TSF 입력 처리 실패 (0x{status:08X})')
                raise TsfError(message)
            return Snapshot(server,bytes(packet.snapshot),C.wstring_at(view+Packet.text.offset,packet.length)),status
        finally:
            if view:k.UnmapViewOfFile(view)
            if event:k.CloseHandle(event)
            if mapping:k.CloseHandle(mapping)
            if security:k.LocalFree(security.descriptor)

    def capture(self,server,focus):return self.exchange(server,focus,1)[0]
    def apply(self,focus,snapshot,text):return self.exchange(snapshot.server,focus,2,snapshot.token,text)[1]

def activate_installed():
    """Run only the registered component's helper, as this user, off the UI thread."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,'SOFTWARE\\Classes\\CLSID\\'+SERVICE_ID+r'\InprocServer32',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
            dll=Path(winreg.QueryValueEx(key,None)[0])
        host=dll.with_name('STOOMTextServiceHost.exe')
        if not host.is_file():return 'TSF 구성요소 없음 · 기본 입력 호환 경로 사용'
        result=subprocess.run([str(host),'--activate'],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:return 'TSF 활성화 실패 · 기본 입력 호환 경로 사용'
        return 'TSF 활성화 요청 완료 · 입력창 연결은 단축키를 누를 때 확인합니다.'
    except (OSError,subprocess.TimeoutExpired):return 'TSF 구성요소 없음 · 기본 입력 호환 경로 사용'
