"""User-run, metadata-only paragraph selection diagnostic. No document writes.

Freeze with --paths <release> and the SST icon/PNG resources. --self-test uses
fixed in-memory fixtures; --clipboard-worker is the existing private helper.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time

SOURCE_ROOT = Path(__file__).resolve().parents[1]
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(SOURCE_ROOT))

import clipboard_process
import focus_guard
import keyboard_access as keyboard

VERSION = 'paragraph-probe-1'
REPORT_NAME = 'paragraph-probe.json'
COPY = (keyboard.CTRL, ord('C'))
ALLOWED_KEYS = frozenset((COPY, (keyboard.CTRL, keyboard.DOWN),
    (keyboard.CTRL, keyboard.SHIFT, keyboard.UP), (keyboard.SHIFT, keyboard.LEFT),
    (keyboard.SHIFT, keyboard.RIGHT), (keyboard.RIGHT,), (keyboard.LEFT,)))
NEWLINES = {'\r': 'CR', '\n': 'LF', '\u2028': 'LS', '\u2029': 'PS'}


class ProbeStopped(Exception):
    pass


def trim_boundary(text):
    if text.endswith('\r\n'):
        return text[:-2]
    if text.endswith(tuple(NEWLINES)):
        return text[:-1]
    return text


def metadata(text, baseline, caret=None):
    """Allowlisted numeric/boolean metadata; never serialize arbitrary text."""
    result = {'available': text is not None}
    if text is not None:
        ending = []
        for char in reversed(text):
            if char not in NEWLINES or len(ending) >= 4:
                break
            ending.append(NEWLINES[char])
        result.update(chars=len(text), utf16_units=len(text.encode('utf-16-le', errors='replace')) // 2,
                      terminal_newlines=list(reversed(ending)), whitespace_only=not bool(text.strip()))
        if baseline is not None:
            result.update(equals_baseline=text == baseline,
                          equals_trimmed=text == trim_boundary(baseline))
    if isinstance(caret, (tuple, list)) and len(caret) == 5 and all(type(v) is int for v in caret):
        result['caret'] = list(caret)
    return result


def run_probe(env, lease_factory, guard):
    """Bounded fixed sequence; all content lives only in this call's memory."""
    started = time.monotonic()
    report = {'version': VERSION, 'time_utc': datetime.now(timezone.utc).isoformat(),
              'status': 'running', 'stages': [], 'clipboard_restored': False,
              'document_text_recorded': False, 'paste_sent': False}
    baseline = None
    lease = None
    current_selection = False

    def press(keys):
        if keys not in ALLOWED_KEYS:
            raise AssertionError('Disallowed diagnostic key')
        guard()
        env.chord(*keys)
        end = env.now() + .025
        while env.now() < end:
            guard()
            env.sleep(min(.01, max(0, end - env.now())))
        guard()

    def copied(stage):
        nonlocal current_selection
        guard()
        lease.arm_copy()
        press(COPY)
        end = env.now() + .18
        value = None
        while env.now() < end:
            guard()
            try:
                value = lease.read_copy(env.owner_pids)
            except OSError:
                value = None
            if value is not None:
                break
            env.sleep(.01)
        guard()
        current_selection = bool(value)
        report['stages'].append({'stage': stage, **metadata(value, baseline, env.anchor())})
        return value

    try:
        guard()
        lease = lease_factory()
        existing = copied('initial_copy')
        if not existing:
            press((keyboard.CTRL, keyboard.DOWN))
            press((keyboard.CTRL, keyboard.SHIFT, keyboard.UP))
            baseline = copied('automatic_selection')
            report['selection_origin'] = 'automatic'
        else:
            baseline = existing
            report['selection_origin'] = 'manual'
        report['baseline'] = metadata(baseline, baseline)
        if not baseline or not baseline.strip():
            report['status'] = 'no_source'
            return report
        if len(baseline) > 8000:
            report['status'] = 'source_too_large'
            return report
        if trim_boundary(baseline) == baseline:
            report['status'] = 'no_terminal_boundary'
            return report

        press((keyboard.SHIFT, keyboard.LEFT))
        probe = copied('shift_left_probe')
        if probe != baseline:
            press((keyboard.SHIFT, keyboard.RIGHT))
            if copied('shift_right_restore') != baseline:
                report['status'] = 'restore_mismatch'
                return report
        else:
            report['probe_was_noop'] = True

        press((keyboard.RIGHT,))
        collapsed = copied('right_collapse')
        if collapsed:
            report['status'] = 'right_did_not_collapse'
            return report
        press((keyboard.SHIFT, keyboard.LEFT))
        copied('selected_single_suffix')
        press((keyboard.SHIFT, keyboard.RIGHT))
        if copied('suffix_undo'):
            report['status'] = 'suffix_undo_not_collapsed'
            return report
        press((keyboard.LEFT,))
        press((keyboard.CTRL, keyboard.SHIFT, keyboard.UP))
        alternative = copied('end_then_previous_paragraph')
        report['status'] = 'completed'
        report['alternate_matches_trimmed'] = alternative == trim_boundary(baseline)
        return report
    except ProbeStopped:
        report['status'] = 'aborted'
        return report
    except Exception as error:
        # Do not record exception text/repr, which can contain source data.
        report['status'] = 'clipboard_error' if isinstance(error, clipboard_process.ClipboardWorkerError) else 'probe_error'
        return report
    finally:
        # Leave no active block when a confirmed selection remains, provided
        # the same target still has focus and the user has not pressed Esc.
        if current_selection:
            try:
                press((keyboard.RIGHT,))
                report['selection_collapsed_at_end'] = True
            except Exception:
                report['selection_collapsed_at_end'] = False
        if lease is not None:
            try:
                report['clipboard_restored'] = bool(lease.restore())
            except Exception:
                report['clipboard_restore_error'] = True
        report['elapsed_ms'] = round((time.monotonic() - started) * 1000, 1)


def save_report(report):
    destination = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'STOOMShiftTranslator05' / REPORT_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, ensure_ascii=True, indent=2).encode('utf-8')
    if len(content) > 32768:
        raise ValueError('Diagnostic report exceeds limit')
    pending = destination.with_suffix('.json.tmp')
    pending.write_bytes(content)
    os.replace(pending, destination)
    return destination


class Hotkey:
    def __init__(self, events):
        self.events = events
        self.thread_id = None
        self.thread = threading.Thread(target=self.listen, name='STOOM-probe-hotkey', daemon=True)

    def listen(self):
        user = ctypes.WinDLL('user32', use_last_error=True)
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.thread_id = kernel.GetCurrentThreadId()
        user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        user.RegisterHotKey.restype = wintypes.BOOL
        user.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
        user.GetMessageW.restype = ctypes.c_int
        if not user.RegisterHotKey(None, 1, 0x4000, 0x77):
            self.events.put(('hotkey_unavailable', None))
            return
        self.events.put(('ready', None))
        message = wintypes.MSG()
        try:
            while user.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message == 0x0312:
                    try:
                        self.events.put(('probe', focus_guard.capture()))
                    except (OSError, ValueError):
                        self.events.put(('focus_unavailable', None))
        finally:
            user.UnregisterHotKey(None, 1)

    def close(self):
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)


def main():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title('STOOM SST · 문단 선택 진단')
    root.geometry('640x550')
    root.configure(bg='#ffffff')
    root.minsize(600, 530)
    resources = Path(getattr(sys, '_MEIPASS', SOURCE_ROOT))
    icon = resources / 'stoom.ico'
    if icon.is_file():
        root.iconbitmap(str(icon))
    header = tk.Frame(root, bg='#071019', padx=22, pady=16)
    header.pack(fill='x')
    logo = resources / 'branding' / 'sst' / 'icon-48.png'
    if logo.is_file():
        root.brand_image = tk.PhotoImage(file=str(logo))
        tk.Label(header, image=root.brand_image, bg='#071019').pack(side='left', padx=(0, 12))
    tk.Label(header, text='SST  문단 선택 진단', bg='#071019', fg='#e3faff',
             font=('맑은 고딕', 17, 'bold')).pack(side='left')
    body = tk.Frame(root, bg='white', padx=24, pady=20)
    body.pack(fill='both', expand=True)
    instructions = ('1. 한글에서 저장할 필요 없는 새 빈 문서를 엽니다.\n'
                    '2. 다음 세 문장을 Enter로 구분해 직접 입력합니다.\n'
                    '     앞 문단입니다.\n'
                    '     문단 선택을 시험합니다.\n'
                    '     뒤 문단입니다.\n'
                    '3. 두 번째 문장 안에 커서를 놓고, 드래그 없이 F8을 누릅니다.\n'
                    '4. 완료될 때까지 잠시 입력을 멈춥니다. Esc로 중단할 수 있습니다.\n\n'
                    '선택·방향키·복사만 시험합니다. 번역하거나 붙여넣지 않습니다.\n'
                    '문서 글자는 저장하지 않으며 글자 수·줄바꿈·일치 여부만 기록합니다.\n'
                    '진단 후 이전 클립보드를 복원합니다. 기존 문서 대신 빈 문서를 사용하세요.')
    tk.Label(body, text=instructions, justify='left', anchor='w', bg='white', fg='#17394c',
             font=('맑은 고딕', 10), wraplength=580).pack(fill='x')
    status = tk.StringVar(value='F8 단축키를 준비하고 있습니다…')
    tk.Label(body, textvariable=status, bg='white', fg='#12667b', wraplength=580,
             justify='left', font=('맑은 고딕', 11)).pack(fill='x', pady=(22, 8))
    path_text = tk.StringVar(value='결과: %LOCALAPPDATA%\\STOOMShiftTranslator05\\paragraph-probe.json')
    tk.Label(body, textvariable=path_text, bg='white', fg='#607080', wraplength=580,
             justify='left', font=('맑은 고딕', 9)).pack(fill='x')
    events = queue.Queue()
    stop = threading.Event()
    busy = False
    broker = clipboard_process.Broker(command=[sys.executable, '--clipboard-worker'] if getattr(sys, 'frozen', False)
                                     else [sys.executable, str(Path(__file__).resolve()), '--clipboard-worker'])
    hotkey = Hotkey(events)

    def diagnose(focus):
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user.GetAsyncKeyState.restype = ctypes.c_short

        def guard():
            if stop.is_set() or user.GetAsyncKeyState(0x1b) & 0x8000 or not focus_guard.same_foreground(focus):
                raise ProbeStopped()
            if time.monotonic() > deadline:
                raise ProbeStopped()

        deadline = time.monotonic() + 15
        try:
            while user.GetAsyncKeyState(0x77) & 0x8000:
                guard()
                time.sleep(.01)
            env = keyboard.Windows(focus, lambda: (0, 0), lambda: True)
            report = run_probe(env, lambda: clipboard_process.ClipboardLease(broker=broker), guard)
            destination = save_report(report)
            events.put(('done', (report, str(destination))))
        except ProbeStopped:
            events.put(('stopped', None))
        except Exception:
            events.put(('failed', None))

    def poll():
        nonlocal busy
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == 'ready':
                    status.set('준비됐습니다. 테스트 문장에 커서를 놓고 F8을 누르세요.')
                elif kind == 'hotkey_unavailable':
                    status.set('F8을 다른 프로그램이 사용 중입니다. 해당 단축키를 해제하고 다시 실행하세요.')
                elif kind == 'focus_unavailable':
                    status.set('입력 위치를 확인하지 못했습니다. 테스트 문서를 클릭하고 다시 F8을 누르세요.')
                elif kind == 'probe' and not busy:
                    target_pid = wintypes.DWORD()
                    user = ctypes.WinDLL('user32', use_last_error=True)
                    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
                    user.GetWindowThreadProcessId(payload.foreground, ctypes.byref(target_pid))
                    if target_pid.value == os.getpid():
                        status.set('한글의 테스트 문장 안에 커서를 놓고 F8을 누르세요.')
                        continue
                    busy = True
                    status.set('선택 범위를 확인하고 있습니다. 입력을 잠시 멈춰 주세요. Esc: 중단')
                    threading.Thread(target=diagnose, args=(payload,), name='STOOM-paragraph-probe', daemon=True).start()
                elif kind == 'done':
                    busy = False
                    report, destination = payload
                    status.set('진단 완료. 이 대화에 “진단했어”라고 알려 주세요. (' + report['status'] + ')')
                    path_text.set(destination)
                elif kind in ('failed', 'stopped'):
                    busy = False
                    status.set('진단이 중단됐습니다. 테스트 문서에 커서를 두고 다시 F8을 누르세요.')
        except queue.Empty:
            pass
        root.after(75, poll)

    def close():
        stop.set()
        hotkey.close()
        # Give the bounded diagnostic worker a chance to restore its lease.
        if busy:
            status.set('진단을 멈추고 클립보드를 정리하고 있습니다…')
            root.after(150, close_when_idle)
        else:
            broker.close()
            root.destroy()

    def close_when_idle():
        if busy:
            root.after(150, close_when_idle)
        else:
            broker.close()
            root.destroy()

    ttk.Button(body, text='닫기', command=close).pack(anchor='e', pady=(15, 0))
    root.protocol('WM_DELETE_WINDOW', close)
    hotkey.thread.start()
    root.after(75, poll)
    root.mainloop()


def self_test():
    """Only fixed fixtures; importing/running this does not call Windows input."""
    class FakeLease:
        def __init__(self, env):
            self.env = env
            self.text = None
            self.restored = False
        def arm_copy(self):
            self.text = None
            self.env.lease = self
        def read_copy(self, owners):
            return self.text
        def restore(self):
            self.restored = True
            return True
    class Fake:
        owner_pids = (1,)
        def __init__(self):
            self.text = 'PREFIX\r\nPRIVATE_FIXED_SOURCE_921\r\nNEXT'
            self.active = self.anchor_pos = 10
            self.clock = 0.
            self.events = []
        def now(self):
            return self.clock
        def sleep(self, seconds):
            self.clock += seconds
        def anchor(self):
            return (1, self.active, 0, self.active + 1, 12)
        def previous(self):
            return max(0, self.active - (2 if self.text[max(0, self.active - 2):self.active] == '\r\n' else 1))
        def following(self):
            return min(len(self.text), self.active + (2 if self.text[self.active:self.active + 2] == '\r\n' else 1))
        def chord(self, *keys):
            assert keys in ALLOWED_KEYS
            self.events.append(keys)
            low, high = sorted((self.anchor_pos, self.active))
            if keys == COPY:
                self.lease.text = self.text[low:high] if low != high else None
            elif keys == (keyboard.CTRL, keyboard.DOWN):
                end = self.text.find('\n', self.active)
                self.active = self.anchor_pos = len(self.text) if end < 0 else end + 1
            elif keys == (keyboard.CTRL, keyboard.SHIFT, keyboard.UP):
                self.active = self.text.rfind('\n', 0, max(0, self.active - 1)) + 1
            elif keys == (keyboard.RIGHT,):
                self.active = self.anchor_pos = high if low != high else self.following()
            elif keys == (keyboard.LEFT,):
                self.active = self.anchor_pos = low if low != high else self.previous()
            elif keys == (keyboard.SHIFT, keyboard.LEFT):
                self.active = self.previous()
            elif keys == (keyboard.SHIFT, keyboard.RIGHT):
                self.active = self.following()
    env = Fake()
    lease = FakeLease(env)
    original = env.text
    report = run_probe(env, lambda: lease, lambda: None)
    serialized = json.dumps(report)
    assert report['status'] == 'completed', report
    assert report['alternate_matches_trimmed'] and report['clipboard_restored']
    assert env.text == original and lease.restored
    assert 'PRIVATE_FIXED_SOURCE_921' not in serialized and 'PREFIX' not in serialized
    assert all(keys in ALLOWED_KEYS for keys in env.events)
    assert not any(ord(letter) in keys for keys in env.events for letter in ('V', 'X'))
    assert (0x08,) not in env.events and (0x2e,) not in env.events and (0x20,) not in env.events
    assert metadata('source\r\n', 'source\r\n')['terminal_newlines'] == ['CR', 'LF']
    env = Fake(); lease = FakeLease(env)
    def abort():
        if len(env.events) >= 3:
            raise ProbeStopped()
    stopped = run_probe(env, lambda: lease, abort)
    assert stopped['status'] == 'aborted' and stopped['clipboard_restored'] and env.text == original
    print('Paragraph probe self-test: fixed fixture only; arrow/copy allowlist, no source output, no document writes, clipboard cleanup and abort: PASS')


if __name__ == '__main__':
    if '--clipboard-worker' in sys.argv:
        import clipboard_worker
        clipboard_worker.run()
    elif '--self-test' in sys.argv:
        self_test()
    else:
        main()
