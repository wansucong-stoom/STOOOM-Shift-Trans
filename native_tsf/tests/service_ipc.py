"""Explicit native integration test; briefly activates only our own test window.

Usage: python service_ipc.py [--interactive] PATH_TO_HOST_EXE PATH_TO_PRODUCTION_TSF_DLL
No profile registration, language changes, key injection, clipboard, or user
document access. Native host restores the prior foreground if still ours.
With --interactive, the host waits up to 45 seconds for a user click on its
own window. It does not request or restore foreground focus programmatically.
Do not add to the ordinary no-focus Python unit test runner.
"""
import ctypes as C
import argparse
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import tsf_bridge as bridge


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interactive',action='store_true')
    parser.add_argument('host',type=Path)
    parser.add_argument('dll',type=Path)
    args=parser.parse_args()
    host=args.host.resolve();dll=args.dll.resolve()
    assert host.is_file() and dll.is_file()
    k,u,a=bridge._apis()
    u.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
    u.CreateWindowExW.restype=W.HWND
    u.DestroyWindow.argtypes=[W.HWND];u.DestroyWindow.restype=W.BOOL
    u.AllowSetForegroundWindow.argtypes=[W.DWORD];u.AllowSetForegroundWindow.restype=W.BOOL
    sender=u.CreateWindowExW(0,'STATIC','STOOM native test sender',0,0,0,0,0,W.HWND(-3),None,None,None)
    assert sender
    child=subprocess.Popen([str(host),'--ipc-interactive' if args.interactive else '--ipc',str(dll)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
    # This only grants our child permission if Windows already allows this
    # driver to do so. A denied foreground request remains an explicit skip.
    if not args.interactive:u.AllowSetForegroundWindow(child.pid)
    window=None
    def message(code,value=0):
        result=C.c_size_t()
        assert u.SendMessageTimeoutW(window,code,value,0,0x0002,1000,C.byref(result)),C.get_last_error()
        return result.value
    def report(stage):
        message(0x8000+20,stage)
        return json.loads(child.stdout.readline())
    try:
        first=child.stdout.readline()
        if not first:raise AssertionError('Native host failed: '+child.stderr.read())
        info=json.loads(first)
        if info.get('waiting_for_click'):
            print(json.dumps(info,ensure_ascii=False),flush=True)
            first=child.stdout.readline()
            if not first:raise AssertionError('Native host failed while awaiting a click: '+child.stderr.read())
            info=json.loads(first)
        if info.get('skip'):
            print('SKIP: '+info['reason']);child.wait(timeout=3);return 77
        window=info['window'];focus=SimpleNamespace(foreground=window,keyboard_window=window,thread_id=info['thread'])
        client=bridge.Client(sender)
        server=client.locate(focus)
        assert server,'production TSF service window not found'
        snap=client.capture(server,focus)
        assert snap.text=='안녕하세요'
        assert client.apply(focus,snap,'Hello 😀')==0
        assert report(1)['first'],'native host did not observe exact selection replacement/caret'
        try:client.apply(focus,snap,'must not repeat')
        except bridge.TsfError:pass
        else:raise AssertionError('snapshot replay was accepted')
        assert report(2)['first'],'snapshot replay caused a second write'
        second=client.capture(server,focus)
        assert second.text=='앞 Hello 😀 뒤',second.text
        assert client.apply(focus,second,'Second 👋')==0
        assert report(3)['second'],'repeat translation or paragraph replacement failed'
        third=client.capture(server,focus)
        assert third.text=='Second 👋'
        message(0x8000+22)
        try:client.apply(focus,third,'must not overwrite changed text')
        except bridge.TsfError:pass
        else:raise AssertionError('stale snapshot was accepted')
        assert report(4)['changed'],'changed text was overwritten'
        print('PASS: production Python IPC -> production native TSF DLL -> real msctf.dll store; selected replacement, emoji/caret, replay blocked, repeat paragraph translation, stale source blocked')
        print('Registration and third-party editor compatibility were not exercised.')
    finally:
        if window:
            try:message(0x8000+21)
            except Exception:pass
        child.wait(timeout=12)
        u.DestroyWindow(sender)
        if child.returncode not in (0,77):raise AssertionError(f'Native host exit {child.returncode}: '+child.stderr.read())
    return 0


if __name__=='__main__':sys.exit(main())
