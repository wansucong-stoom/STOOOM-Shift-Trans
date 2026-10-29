"""Real Windows IPC with a test-owned receiver, NOT a real TSF service.

Exercises the production Python Client across two processes using named file
mapping/event objects and WM_COPYDATA. The receiver is an explicit protocol stub;
native TSF range tests live in native_tsf/tests/host.cpp. No application focus,
clipboard, keyboard input, registration, or third-party document is touched.
"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import tsf_bridge as bridge

WM_COPYDATA=0x004A
CONTROL=0x8001
COUNT=0x8002
REPORT=0x8003
STOP=0x8004
TOKEN=bytes(range(16))
SAMPLE='안녕하세요 😀 日本語\r\nHello'


def apis():
    k,u,a=bridge._apis()
    callback=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,C.c_size_t,C.c_ssize_t)
    class WindowClass(C.Structure):
        _fields_=[('style',W.UINT),('proc',callback),('class_extra',C.c_int),
                  ('window_extra',C.c_int),('instance',W.HINSTANCE),('icon',W.HICON),
                  ('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
    signatures=[
        (k,'GetCurrentThreadId',W.DWORD,[]),
        (k,'OpenFileMappingW',W.HANDLE,[W.DWORD,W.BOOL,W.LPCWSTR]),
        (k,'OpenEventW',W.HANDLE,[W.DWORD,W.BOOL,W.LPCWSTR]),
        (k,'SetEvent',W.BOOL,[W.HANDLE]),
        (k,'GetHandleInformation',W.BOOL,[W.HANDLE,C.POINTER(W.DWORD)]),
        (u,'RegisterClassW',W.ATOM,[C.POINTER(WindowClass)]),
        (u,'CreateWindowExW',W.HWND,[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]),
        (u,'DefWindowProcW',C.c_ssize_t,[W.HWND,W.UINT,C.c_size_t,C.c_ssize_t]),
        (u,'DestroyWindow',W.BOOL,[W.HWND]),
        (u,'GetMessageW',W.BOOL,[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT]),
        (u,'TranslateMessage',W.BOOL,[C.POINTER(W.MSG)]),
        (u,'DispatchMessageW',C.c_ssize_t,[C.POINTER(W.MSG)]),
        (u,'PostQuitMessage',None,[C.c_int]),
        (a,'GetSecurityInfo',W.DWORD,[W.HANDLE,C.c_int,W.DWORD,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,C.POINTER(C.c_void_p)]),
        (a,'ConvertSecurityDescriptorToStringSecurityDescriptorW',W.BOOL,[C.c_void_p,W.DWORD,W.DWORD,C.POINTER(W.LPWSTR),C.POINTER(W.DWORD)]),
    ]
    for dll,name,result,args in signatures:
        fn=getattr(dll,name);fn.restype=result;fn.argtypes=args
    return k,u,a,callback,WindowClass


def serve():
    k,u,a,Callback,WindowClass=apis()
    state={'mode':0,'requests':0,'bad_senders':0,'errors':[], 'names':[], 'inputs':[], 'dacl_checks':0}

    def inspect_security(handle):
        descriptor=C.c_void_p();sddl=W.LPWSTR()
        status=a.GetSecurityInfo(handle,6,4,None,None,None,None,C.byref(descriptor))
        assert status==0,('GetSecurityInfo',status)
        try:
            assert a.ConvertSecurityDescriptorToStringSecurityDescriptorW(descriptor,1,4,C.byref(sddl),None)
            # Exactly LocalSystem and the creating user; no Everyone, Users,
            # authenticated users, anonymous user, or inherited ACEs.
            acl=sddl.value
            principals=re.findall(r';;;([^)]*)\)',acl)
            assert len(principals)==2 and 'SY' in principals,acl
            assert any(p.startswith('S-1-5-21-') for p in principals),acl
            assert acl.startswith('D:P'),acl
            state['dacl_checks']+=1
        finally:
            if sddl:k.LocalFree(C.cast(sddl,W.HANDLE))
            if descriptor:k.LocalFree(descriptor)

    @Callback
    def window_proc(window,message,wp,lp):
        if message==CONTROL:state['mode']=int(wp);return 1
        if message==COUNT:return state['requests']
        if message==REPORT:print(json.dumps(state,ensure_ascii=True),flush=True);return 1
        if message==STOP:u.DestroyWindow(window);u.PostQuitMessage(0);return 1
        if message!=WM_COPYDATA:return u.DefWindowProcW(window,message,wp,lp)
        mapping=event=view=None
        try:
            data=C.cast(lp,C.POINTER(bridge.CopyData)).contents
            assert data.data==bridge.MAGIC and data.size==C.sizeof(bridge.Notice)
            notice=C.cast(data.pointer,C.POINTER(bridge.Notice)).contents
            assert notice.magic==bridge.MAGIC
            sender=W.DWORD();u.GetWindowThreadProcessId(W.HWND(wp),C.byref(sender))
            if not sender.value:
                state['bad_senders']+=1;return 0
            name=notice.name
            assert name.startswith(f'Local\\STOOM.TSF.{sender.value}.')
            assert re.fullmatch(r'Local\\STOOM\.TSF\.\d+\.[0-9a-f]{32}',name)
            assert name not in state['names'],'request mapping name was reused'
            state['names'].append(name)
            mapping=k.OpenFileMappingW(6|0x20000,False,name)
            assert mapping,('OpenFileMapping',C.get_last_error())
            event=k.OpenEventW(2|0x20000,False,name+'.done')
            assert event,('OpenEvent',C.get_last_error())
            inspect_security(mapping);inspect_security(event)
            view=k.MapViewOfFile(mapping,6,0,0,C.sizeof(bridge.Packet));assert view
            packet=bridge.Packet.from_address(view)
            assert packet.magic==bridge.MAGIC and packet.version==1 and packet.complete==0
            assert packet.client==sender.value and packet.thread==k.GetCurrentThreadId()
            assert packet.foreground==window and packet.keyboard==window
            assert packet.deadline>=k.GetTickCount64()
            assert packet.length<=16000
            text=C.string_at(view+bridge.Packet.text.offset,packet.length*2).decode('utf-16-le')
            assert C.string_at(view+bridge.Packet.text.offset+packet.length*2,2)==b'\0\0'
            state['inputs'].append({'op':packet.operation,'text':text,'token':list(packet.snapshot)})
            state['requests']+=1
            mode=state['mode']
            if mode==4:return 1  # Accepted but deliberately unconfirmed.
            output=SAMPLE if packet.operation==1 else text
            raw=output.encode('utf-16-le')
            C.memmove(view+bridge.Packet.text.offset,raw+b'\0\0',len(raw)+2)
            packet.length=len(raw)//2;packet.snapshot[:]=TOKEN
            status={0:0,1:bridge.TF_E_LOCKED,2:bridge.E_NOINTERFACE,3:0x80070005,5:0x00040601,6:0x8007051a,7:1}.get(mode,0)
            packet.status=C.c_int32(status).value
            if mode==8:packet.length=16001
            packet.complete=1
            assert k.SetEvent(event)
            return 1
        except Exception as exc:
            state['errors'].append(repr(exc));return 0
        finally:
            if view:k.UnmapViewOfFile(view)
            if event:k.CloseHandle(event)
            if mapping:k.CloseHandle(mapping)

    class_name='STOOM.Test.IpcReceiver.'+str(os.getpid())
    wc=WindowClass();wc.proc=window_proc;wc.name=class_name
    assert u.RegisterClassW(C.byref(wc))
    name=f'STOOM.TSF.{os.getpid()}.{k.GetCurrentThreadId()}'
    window=u.CreateWindowExW(0,class_name,name,0,0,0,0,0,W.HWND(-3),None,None,None)
    assert window
    print(json.dumps({'window':int(window),'thread':k.GetCurrentThreadId(),'pid':os.getpid()}),flush=True)
    msg=W.MSG()
    while u.GetMessageW(C.byref(msg),None,0,0)>0:
        u.TranslateMessage(C.byref(msg));u.DispatchMessageW(C.byref(msg))


def run():
    assert C.sizeof(bridge.Packet)==32080 and bridge.Packet.text.offset==72
    assert C.sizeof(bridge.Notice)==196
    k,u,a,Callback,WindowClass=apis()
    sender=u.CreateWindowExW(0,'STATIC','STOOM IPC test sender',0,0,0,0,0,W.HWND(-3),None,None,None)
    assert sender
    child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--receiver'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    info=json.loads(child.stdout.readline())
    server=info['window'];focus=SimpleNamespace(foreground=server,keyboard_window=server,thread_id=info['thread'])
    client=bridge.Client(sender)

    def command(message,value=0):
        result=C.c_size_t()
        assert u.SendMessageTimeoutW(server,message,value,0,0x0002,1000,C.byref(result)),C.get_last_error()
        return result.value

    def expect(kind,call):
        try:call()
        except kind:return
        raise AssertionError(f'expected {kind.__name__}')

    try:
        assert client.locate(focus)==server
        snap=client.capture(server,focus)
        assert snap.text==SAMPLE and snap.token==TOKEN
        assert client.apply(focus,snap,'번역 😀 完了')==0
        command(CONTROL,5)
        assert client.apply(focus,snap,'caret failure')==0x00040601
        command(CONTROL,1)
        expect(bridge.Pending,lambda:client.capture(server,focus))
        command(CONTROL,2)
        expect(bridge.Unavailable,lambda:client.capture(server,focus))
        expect(bridge.TsfError,lambda:client.apply(focus,snap,'must not fallback'))
        for mode in (3,6,7,8):
            command(CONTROL,mode)
            expect(bridge.TsfError,lambda:client.capture(server,focus))
        command(CONTROL,4)
        before=command(COUNT);start=time.monotonic()
        expect(bridge.TsfError,lambda:client.exchange(server,focus,2,snap.token,'uncertain apply',timeout_ms=120))
        assert command(COUNT)==before+1,'apply timeout must not retry automatically'
        assert time.monotonic()-start<2,'timeout must be bounded'
        command(CONTROL,0)
        before=command(COUNT)
        expect(bridge.TsfError,lambda:client.apply(focus,snap,'x'*16001))
        expect(bridge.TsfError,lambda:client.apply(focus,snap,'bad\0text'))
        assert command(COUNT)==before,'invalid payload must never reach receiver'
        expect(bridge.TsfError,lambda:bridge.Client(0).capture(server,focus))
        absent=SimpleNamespace(foreground=0,keyboard_window=0,thread_id=0)
        expect(bridge.Unavailable,lambda:client.capture(server,absent))
        command(REPORT)
        report=json.loads(child.stdout.readline())
        assert not report['errors'],report['errors']
        assert report['bad_senders']==1
        assert report['dacl_checks']==2*report['requests']
        assert report['inputs'][1]['text']=='번역 😀 完了'
        assert bytes(report['inputs'][1]['token'])==TOKEN
        assert len(set(report['names']))==report['requests']
        print('Windows IPC stub: cross-process UTF-16, sender PID, unique owner/SYSTEM ACLs, capture/apply status, bounded no-retry timeout: PASS')
        print('This validates Python IPC, not native TSF registration or editor compatibility.')
    except Exception:
        command(REPORT)
        print('Receiver diagnostics:',child.stdout.readline().strip())
        raise
    finally:
        command(STOP)
        child.wait(timeout=3)
        errors=child.stderr.read()
        u.DestroyWindow(sender)
        assert child.returncode==0,errors


if __name__=='__main__':
    if '--receiver' in sys.argv:serve()
    else:run()
