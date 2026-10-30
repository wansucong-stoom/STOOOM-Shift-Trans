"""Real Windows/Qt second-launch regression, using only isolated test windows.

No application startup, model, hook, tray, document, or clipboard is touched.
The windows run on a private Windows desktop that is never displayed. The App handlers are
compiled directly from main.py so this checks production behavior without its
startup side effects. A separate process sends the actual registered message.
"""
import ast
import ctypes
from ctypes import wintypes
import marshal
import os
from pathlib import Path
import subprocess
import sys
import time
import types
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['QT_QPA_PLATFORM'] = 'windows'
FROZEN_EXE = os.environ.get('SST_TEST_FROZEN_EXE')
if FROZEN_EXE:
    # Test-only archive inspection. Never start the EXE or execute its main
    # module. This exercises the shipped singleton and App method bytecode.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(Path(FROZEN_EXE).resolve(strict=True)))
    pyz = archive.open_embedded_archive('PYZ.pyz')
    singleton = types.ModuleType('settings_reopen_packaged_singleton')
    exec(pyz.extract('singleton'), singleton.__dict__)
else:
    import singleton

# A separate desktop isolates native minimize/restore activation as well as
# painting. This is never switched to the user's input desktop. Both our Qt
# receiver and the child sender are attached only to this temporary desktop.
user = ctypes.WinDLL('user32', use_last_error=True)
user.CreateDesktopW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                              wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
user.CreateDesktopW.restype = wintypes.HANDLE
user.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user.SetThreadDesktop.restype = wintypes.BOOL
user.GetThreadDesktop.argtypes = [wintypes.DWORD]
user.GetThreadDesktop.restype = wintypes.HANDLE
user.CloseDesktop.argtypes = [wintypes.HANDLE]
user.CloseDesktop.restype = wintypes.BOOL
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetCurrentThreadId.restype = wintypes.DWORD
original_desktop = user.GetThreadDesktop(kernel.GetCurrentThreadId())
desktop_name = 'SSTReopenTest-' + uuid.uuid4().hex
desktop = user.CreateDesktopW(desktop_name, None, None, 0, 0x10000000, None)
assert desktop, ctypes.WinError(ctypes.get_last_error())
assert user.SetThreadDesktop(desktop), ctypes.WinError(ctypes.get_last_error())

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
from shiboken6 import VoidPtr, delete


methods = ['nativeEvent', 'show_settings', 'closeEvent']
namespace = dict(__name__='settings_reopen_handlers', QWidget=QWidget, singleton=singleton, QTimer=QTimer)
if FROZEN_EXE:
    main_code = marshal.loads(archive.extract('main'))
    app_code = next(code for code in main_code.co_consts
                    if isinstance(code, types.CodeType) and code.co_name == 'App')
    AppHandlers = __build_class__(types.FunctionType(app_code, namespace), 'App', QWidget)
    assert all(name in AppHandlers.__dict__ for name in methods)
else:
    source = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    production = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == 'App')
    selected = [node for node in production.body if isinstance(node, ast.FunctionDef) and node.name in methods]
    assert len(selected) == len(methods)
    handler_class = ast.ClassDef(name='AppHandlers', bases=[ast.Name(id='QWidget', ctx=ast.Load())],
                                keywords=[], body=selected, decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[handler_class], type_ignores=[]))
    exec(compile(module, str(ROOT / 'main.py'), 'exec'), namespace)
    AppHandlers = namespace['AppHandlers']


class PaintedLabel(QLabel):
    def __init__(self, parent):
        super().__init__('SST isolated settings reopen regression', parent)
        self.paints = 0

    def paintEvent(self, event):
        self.paints += 1
        return super().paintEvent(event)


class Fixture(AppHandlers):
    def __init__(self, title):
        # Do not invoke the production App.__init__, including in frozen mode.
        QWidget.__init__(self, None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowOpacity(0)
        self.setWindowTitle(title)
        self.resize(320, 80)
        self.move(QApplication.primaryScreen().availableGeometry().topLeft())
        self.label = PaintedLabel(self)
        QVBoxLayout(self).addWidget(self.label)
        self._quitting = False
        self._settings_show_pending = False
        self.show_calls = 0
        self.show_events = 0

    def show_settings(self):
        self.show_calls += 1
        return super().show_settings()

    def showEvent(self, event):
        self.show_events += 1
        return super().showEvent(event)

    # The production show/restore and native message handlers are unchanged.
    # Explicit foreground calls are suppressed; Windows-level restore is
    # exercised only on our private desktop, never the user's input desktop.
    def raise_(self):
        pass

    def activateWindow(self):
        pass


qt = QApplication([])
qt.setQuitOnLastWindowClosed(False)
user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user.ShowWindow.restype = wintypes.BOOL
user.IsWindowVisible.argtypes = [wintypes.HWND]
user.IsWindowVisible.restype = wintypes.BOOL
children = []
windows = []


def spin_until(condition, timeout=3):
    deadline = time.monotonic() + timeout
    while not condition():
        qt.processEvents()
        if time.monotonic() >= deadline:
            raise AssertionError('timed out waiting for test Qt event: ' + repr([(w.isVisible(), w.label.isVisible(), w.isMinimized(), w.label.paints, w.show_calls, w._settings_show_pending) for w in windows]))
        time.sleep(.005)
    qt.processEvents()


def make_window(title):
    window = Fixture(title)
    windows.append(window)
    window.winId()  # Materialize the isolated receiver without showing it.
    return window


sender_source = '''import sys, ctypes, os, types
from ctypes import wintypes
user = ctypes.WinDLL('user32', use_last_error=True)
user.OpenDesktopW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user.OpenDesktopW.restype = wintypes.HANDLE
user.SetThreadDesktop.argtypes = [wintypes.HANDLE]
user.SetThreadDesktop.restype = wintypes.BOOL
desktop = user.OpenDesktopW(sys.argv[4], 0, False, 0x10000000)
assert desktop and user.SetThreadDesktop(desktop), ctypes.WinError(ctypes.get_last_error())
sys.path.insert(0, sys.argv[1])
if os.environ.get('SST_TEST_FROZEN_EXE'):
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(os.environ['SST_TEST_FROZEN_EXE'])
    singleton = types.ModuleType('packaged_sender_singleton')
    exec(archive.open_embedded_archive('PYZ.pyz').extract('singleton'), singleton.__dict__)
else:
    import singleton
print('ready', flush=True)
ok = singleton.show_existing(title=sys.argv[2], timeout=float(sys.argv[3]), allow_foreground=False)
print('posted' if ok else 'missing', flush=True)
sys.exit(0 if ok else 4)
'''


def sender(title, timeout=1.5):
    process = subprocess.Popen([sys.executable, '-c', sender_source, str(ROOT), title, str(timeout), desktop_name],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    children.append(process)
    assert process.stdout.readline().strip() == 'ready'
    return process


def finish_sender(process, expected=0):
    spin_until(lambda: process.poll() is not None)
    output, errors = process.communicate(timeout=1)
    assert process.returncode == expected, (process.returncode, output, errors)
    assert output.strip() == ('posted' if expected == 0 else 'missing'), output


def assert_shown(window, previous_paints):
    spin_until(lambda: window.isVisible() and window.label.isVisible() and not window.isMinimized())
    # A minimized window can reuse its cached backing store. Requesting a
    # normal update verifies painting is enabled without grab()/render(),
    # which could paint a widget even while it is logically hidden.
    window.label.update()
    spin_until(lambda: window.label.paints > previous_paints)
    assert user.IsWindowVisible(int(window.winId()))


try:
    title = 'SST-reopen-regression-' + uuid.uuid4().hex
    window = make_window(title)
    hwnd = int(window.winId())
    window.show()
    assert_shown(window, 0)
    window.close()  # Use the production closeEvent: ignored close + Qt hide.
    qt.processEvents()
    assert not window.isVisible() and not window.label.isVisible()

    # Old path: externally showing just the HWND leaves Qt/children hidden.
    # SW_SHOWNOACTIVATE has the same native-only visibility defect as the old
    # SW_RESTORE, without disturbing the user's current foreground application.
    user.ShowWindow(hwnd, 4)
    qt.processEvents()
    assert user.IsWindowVisible(hwnd)
    assert not window.isVisible() and not window.label.isVisible(), 'old bug did not reproduce'

    previous = window.label.paints
    process = sender(title)
    finish_sender(process)
    assert_shown(window, previous)
    assert int(window.winId()) == hwnd and window.show_calls == 1

    for _ in range(3):
        window.close()
        qt.processEvents()
        assert not window.label.isVisible()
        previous = window.label.paints
        process = sender(title)
        finish_sender(process)
        assert_shown(window, previous)
        assert int(window.winId()) == hwnd

    # Minimized native windows must use Qt's normal-state restoration too.
    window.showMinimized()
    qt.processEvents()
    assert window.isMinimized()
    previous = window.label.paints
    process = sender(title)
    finish_sender(process)
    assert_shown(window, previous)

    # Requests arriving together schedule one show on the GUI event loop.
    window.close()
    qt.processEvents()
    message = wintypes.MSG()
    message.hWnd = hwnd
    message.message = singleton.SHOW_SETTINGS_MESSAGE
    pointer = ctypes.addressof(message)
    # Qt supplies a zero-sized VoidPtr: its truth value is false even though
    # its address is valid. Rejecting `not message` silently loses every IPC.
    qt_pointer = VoidPtr(pointer, 0)
    assert int(qt_pointer) == pointer and not qt_pointer
    assert singleton.is_show_request(b'windows_generic_MSG', qt_pointer)
    before = window.show_calls
    for _ in range(8):
        assert window.nativeEvent(b'windows_generic_MSG', pointer) == (True, 0)
    assert window._settings_show_pending and window.show_calls == before
    spin_until(lambda: window.show_calls == before + 1)
    assert not window._settings_show_pending and window.label.isVisible()

    # Invalid messages are not accepted as settings requests.
    assert not singleton.is_show_request(b'windows_dispatcher_MSG', pointer)
    message.wParam = 1
    assert not singleton.is_show_request(b'windows_generic_MSG', pointer)
    message.wParam = 0

    # A request racing shutdown must not resurrect the settings window.
    window.close()
    qt.processEvents()
    window.nativeEvent(b'windows_generic_MSG', pointer)
    window._quitting = True
    qt.processEvents()
    assert not window.isVisible() and not window._settings_show_pending
    before = window.show_calls
    process = sender(title)
    finish_sender(process)
    assert not window.isVisible() and window.show_calls == before

    # The receiver can appear after the second process begins its lookup.
    delayed_title = 'SST-reopen-startup-' + uuid.uuid4().hex
    delayed = []
    process = sender(delayed_title)
    QTimer.singleShot(100, lambda: delayed.append(make_window(delayed_title)))
    finish_sender(process)
    spin_until(lambda: bool(delayed))
    assert_shown(delayed[0], 0)
    assert delayed[0].show_calls == 1

    # A nonexistent receiver returns within its bounded retry interval.
    process = sender('SST-reopen-missing-' + uuid.uuid4().hex, .1)
    finish_sender(process, expected=4)
finally:
    for process in children:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=2)
    for window in windows:
        window.hide()
        delete(window)
    qt.processEvents()
    delete(qt)
    assert user.SetThreadDesktop(original_desktop), ctypes.WinError(ctypes.get_last_error())
    assert user.CloseDesktop(desktop), ctypes.WinError(ctypes.get_last_error())

print('PASS: native blank-window reproduction; cross-process Qt reopen/paint, repeated reopen, '
      'minimize, coalescing, shutdown and startup race on an isolated Windows desktop; '
      + ('frozen EXE bytecode' if FROZEN_EXE else 'source handlers'))
