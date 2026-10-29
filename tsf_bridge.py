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
    """Activate as the current user and retain the helper's diagnostic evidence.

    This runs off the UI thread. A successful profile activation request does not
    prove that the focused editor loaded the service or exposes a text context.
    """
    import json
    import re
    import winreg

    def system_error(error):
        code=getattr(error,'winerror',None)
        if code is None:code=getattr(error,'errno',None)
        return f' (Windows 오류 {code})' if code is not None else ''

    registry_path='SOFTWARE\\Classes\\CLSID\\'+SERVICE_ID+r'\InprocServer32'
    try:
        key=winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,registry_path,0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return 'TSF 구성요소가 등록되지 않았습니다. 설치 프로그램에서 TSF 입력 지원을 설치하세요.'
    except OSError as error:
        return 'TSF 등록 정보 읽기 실패'+system_error(error)+'. 설치 상태를 확인하지 못했습니다.'
    try:
        with key:
            registered_path,value_type=winreg.QueryValueEx(key,None)
        if not isinstance(registered_path,str) or not registered_path.strip():
            return 'TSF 등록 정보 형식 오류: 구성요소 경로가 비어 있거나 올바르지 않습니다.'
        if value_type==getattr(winreg,'REG_EXPAND_SZ',2):registered_path=os.path.expandvars(registered_path)
        dll=Path(registered_path)
        if not dll.is_absolute():
            return 'TSF 등록 정보 형식 오류: 구성요소 경로가 절대 경로가 아닙니다.'
        host=dll.with_name('STOOMTextServiceHost.exe')
        if not host.is_file():
            return 'TSF 등록은 있지만 실행 도우미 파일이 없습니다. TSF 입력 지원을 다시 설치하세요.'
    except (ValueError,TypeError):
        return 'TSF 등록 정보 형식 오류: 구성요소 경로를 확인할 수 없습니다.'
    except OSError as error:
        return 'TSF 등록 정보 또는 실행 파일 확인 실패'+system_error(error)+'. 등록된 구성요소를 확인하지 못했습니다.'

    try:
        result=subprocess.run([str(host),'--activate'],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
    except subprocess.TimeoutExpired:
        return 'TSF 활성화 응답 시간 초과 (10초). 구성요소는 등록되어 있지만 활성화 결과를 확인하지 못했습니다.'
    except OSError as error:
        return 'TSF 실행 도우미 시작 실패'+system_error(error)+'. TSF 활성화 요청을 실행하지 못했습니다.'

    exit_detail=f'종료 코드 {result.returncode}'
    try:
        raw=result.stdout
        if not isinstance(raw,(bytes,str)) or len(raw)>65536:raise ValueError('invalid output size')
        data=json.loads(raw.decode('utf-8-sig') if isinstance(raw,bytes) else raw)
        if not isinstance(data,dict):raise ValueError('not a status object')
    except (ValueError,UnicodeError,TypeError):
        return f'TSF 활성화 상태 응답을 해석하지 못했습니다 ({exit_detail}). 활성화 성공 여부를 확인할 수 없습니다.'

    def hresult(value):
        if isinstance(value,str) and re.fullmatch(r'0[xX][0-9a-fA-F]{8}',value):return int(value,16)
        if isinstance(value,int) and not isinstance(value,bool) and -(2**31)<=value<2**32:return value&0xffffffff
        return None

    details=[]
    step=data.get('step')
    if isinstance(step,str) and step:
        # The helper emits API identifiers, not document content. Bound and
        # sanitize unexpected strings before placing them in the settings UI.
        details.append(re.sub(r'[^A-Za-z0-9_.:-]','?',step[:64]))
    top_hr=hresult(data.get('hresult'))
    if top_hr is not None:details.append(f'0x{top_hr:08X}')
    if data.get('registered') is False:details.append('프로필 등록 확인 실패')
    error_code=data.get('error')
    error_labels={
        'registration_incomplete':'입력 서비스 등록이 완전하지 않습니다',
        'keyboard_state_unavailable':'현재 키보드 프로필을 확인하지 못했습니다',
        'current_language_not_supported':'현재 입력 언어의 TSF 프로필이 없습니다',
        'profile_activation_failed':'언어 프로필 활성화 실패',
        'self_service_not_loaded':'TSF 도우미에 입력 서비스가 로드되지 않았습니다',
        'keyboard_profile_changed':'기존 키보드 프로필 유지 확인 실패'}
    if isinstance(error_code,str) and error_code:
        safe_code=re.sub(r'[^A-Za-z0-9_.:-]','?',error_code[:64])
        details.append(error_labels.get(error_code,'TSF 구성요소 오류')+f' ({safe_code})')
    self_hr=hresult(data.get('self_probe_hresult'))
    if self_hr is not None and self_hr!=0:details.append(f'서비스 자체 확인 0x{self_hr:08X}')
    if data.get('operation')=='activate' and data.get('registered') is True:
        if 'self_service_loaded' not in data or 'keyboard_unchanged' not in data:
            details.append('이전 TSF 구성요소에는 서비스 로딩·키보드 유지 확인 결과가 없습니다. TSF 입력 지원을 업데이트하세요')
        else:
            if data.get('self_service_loaded') is not True and error_code!='self_service_not_loaded':details.append('입력 서비스 자체 로딩을 확인하지 못했습니다')
            if data.get('keyboard_unchanged') is not True and error_code!='keyboard_profile_changed':details.append('기존 키보드 프로필 유지 여부를 확인하지 못했습니다')
    category=data.get('category_checks')
    category_valid=False
    if isinstance(category,dict):
        category_hr=hresult(category.get('hresult'))
        category_valid=(category_hr==0 and category.get('type_registered') is True and category.get('service_member') is True and category.get('keyboard_member') is False)
        if category_hr is not None and category_hr!=0:details.append(f'입력 서비스 분류 확인 0x{category_hr:08X}')
        if category.get('type_registered') is not True or category.get('service_member') is not True or category.get('keyboard_member') is not False:
            details.append('보조 입력 서비스 등록 관계가 일치하지 않습니다')
    profiles=data.get('profiles')
    codes=[]
    language_ids=[]
    languages={0x0412:'한국어',0x0409:'영어',0x0411:'일본어'}
    if isinstance(profiles,list):
        for profile in profiles[:8]:
            if not isinstance(profile,dict):codes.append(None);language_ids.append(None);continue
            language=profile.get('language')
            language_ids.append(language if isinstance(language,int) and not isinstance(language,bool) else None)
            label=languages.get(language) if isinstance(language,int) and not isinstance(language,bool) else None
            if label is None:label=f'언어 0x{language:04X}' if isinstance(language,int) and not isinstance(language,bool) and 0<=language<=0xffff else '알 수 없는 언어'
            code=hresult(profile.get('hresult'));codes.append(code)
            details.append(f'{label} '+(f'0x{code:08X}' if code is not None else '결과 코드 없음'))
    confirmed=(result.returncode==0 and data.get('ok') is True and data.get('operation')=='activate'
               and data.get('registered') is True and isinstance(profiles,list)
               and data.get('self_service_loaded') is True and data.get('keyboard_unchanged') is True and self_hr==0
               and category_valid
               and len(profiles)==3 and len(codes)==3 and all(code==0 for code in codes)
               and set(language_ids)==set(languages))
    if confirmed:
        return 'TSF 활성화 요청 완료 (한국어·영어·일본어). 입력창의 실제 연결은 단축키를 누를 때 확인합니다.'
    if not details:details.append('구성요소가 상세 상태를 반환하지 않았습니다')
    details.append(exit_detail)
    label='TSF 활성화 실패' if result.returncode!=0 or data.get('ok') is False or any(code not in (None,0) for code in codes) else 'TSF 활성화 결과 확인 실패'
    return label+' · '+' / '.join(details)
