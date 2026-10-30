"""Read the focused text caret; never click, select, type, or use the clipboard.

Coordinate lookup was adapted from the user-supplied Downloads/caretclick.py
(SHA256 2ec89dadd3c3246fdb9e4c5876b35b1a55bdea773a23881c1569e09c494a1274).
Its input/clipboard/daemon code is deliberately not included. Unlike that helper,
this module rejects non-collapsed ranges and does not expand a paragraph or use
the mouse position. A supported provider is required; this is not a guarantee
that every application exposes its visible caret.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as W
from dataclasses import dataclass
import math
import queue
import threading
import time

from focus_guard import GUITHREADINFO


@dataclass(frozen=True)
class _Focus:
    foreground: int
    keyboard_window: int
    thread_id: int


def _rect_point(values, *, character=False):
    """Accept one narrow screen rectangle, including a zero-width caret."""
    try:
        if len(values) != 4:
            return None
        x, y, width, height = map(float, values)
        if not all(math.isfinite(v) for v in (x, y, width, height)):
            return None
        if not (2 <= height <= 400 and 0 <= width <= (2 if character else 1.2) * height):
            return None
        # Signed coordinates are intentional: monitors may be left/above origin.
        if any(abs(v) >= 2**30 for v in (x, y, x + width, y + height)):
            return None
        return int(math.floor(x + width / 2)), int(math.floor(y + height / 2))
    except (TypeError, ValueError, OverflowError):
        return None


def _collapsed(rng):
    return rng is not None and rng.CompareEndpoints(0, rng, 1) == 0


def _range_point(rng):
    """Read a collapsed range, or one adjacent character when it has no box."""
    if not _collapsed(rng):
        return None
    rectangles = tuple(rng.GetBoundingRectangles() or ())
    if rectangles:
        return _rect_point(rectangles)
    # Move one endpoint, not ExpandToEnclosingUnit: an unsupported expansion
    # can silently produce a whole paragraph. Never move/select the real caret.
    for endpoint, direction in ((1, 1), (0, -1)):
        adjacent = rng.Clone()
        if adjacent.MoveEndpointByUnit(endpoint, 0, direction) != direction:
            continue
        stationary = 0 if endpoint == 1 else 1
        if adjacent.CompareEndpoints(stationary, rng, stationary) != 0:
            continue
        # Bound the read and reject newline/object/paragraph fallbacks even if
        # a buggy provider reports a successful one-character movement.
        text = adjacent.GetText(3)
        if (not text or len(text) > 2 or
                any(c in text for c in '\r\n\t\u2028\u2029\ufffc\0')):
            continue
        point = _rect_point(tuple(adjacent.GetBoundingRectangles() or ()), character=True)
        if point is not None:
            return point
    return None


def _pattern_point(element, interfaces):
    """Prefer an active TextPattern2 caret; reject inactive/stale selections."""
    pattern2 = None
    if hasattr(interfaces, 'IUIAutomationTextPattern2'):
        try:
            raw = element.GetCurrentPattern(10024)
            if raw:
                pattern2 = raw.QueryInterface(interfaces.IUIAutomationTextPattern2)
        except Exception:
            pass
    if pattern2 is not None:
        active, rng = pattern2.GetCaretRange()
        # An inactive/failed v2 caret is not permission to use an older cached
        # selection from the same provider.
        return _range_point(rng) if active else None
    raw = element.GetCurrentPattern(10014)
    if not raw:
        return None
    pattern = raw.QueryInterface(interfaces.IUIAutomationTextPattern)
    ranges = pattern.GetSelection()
    if ranges is None or ranges.Length != 1:
        return None
    return _range_point(ranges.GetElement(0))


class _Windows:
    def __init__(self):
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        signatures = {
            'GetForegroundWindow': ([], W.HWND),
            'GetWindowThreadProcessId': ([W.HWND, ctypes.POINTER(W.DWORD)], W.DWORD),
            'GetGUIThreadInfo': ([W.DWORD, ctypes.POINTER(GUITHREADINFO)], W.BOOL),
            'ClientToScreen': ([W.HWND, ctypes.POINTER(W.POINT)], W.BOOL),
            'GetAncestor': ([W.HWND, W.UINT], W.HWND),
            'IsWindowVisible': ([W.HWND], W.BOOL),
            'GetWindowRect': ([W.HWND, ctypes.POINTER(W.RECT)], W.BOOL),
            'WindowFromPoint': ([W.POINT], W.HWND),
            'MonitorFromPoint': ([W.POINT, W.DWORD], W.HANDLE),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(self.u, name)
            fn.argtypes, fn.restype = args, result

    def root_matches(self, hwnd, focus):
        return bool(hwnd) and int(self.u.GetAncestor(hwnd, 2) or 0) == focus.foreground

    def current(self, focus):
        return bool(focus.foreground) and int(self.u.GetForegroundWindow() or 0) == focus.foreground

    def valid(self, point, focus):
        if point is None or not self.current(focus):
            return False
        if not self.u.IsWindowVisible(focus.foreground):
            return False
        x, y = point
        bounds = W.RECT()
        if not self.u.GetWindowRect(focus.foreground, ctypes.byref(bounds)):
            return False
        if not (bounds.left <= x < bounds.right and bounds.top <= y < bounds.bottom):
            return False
        screen_point = W.POINT(x, y)
        if not self.u.MonitorFromPoint(screen_point, 0):
            return False
        return self.root_matches(self.u.WindowFromPoint(screen_point), focus)

    def native(self, focus):
        if not self.current(focus):
            return None
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self.u.GetGUIThreadInfo(focus.thread_id, ctypes.byref(info)):
            return None
        if not self.root_matches(info.hwndFocus, focus) or not self.root_matches(info.hwndCaret, focus):
            return None
        if not self.u.IsWindowVisible(info.hwndCaret):
            return None
        rect = info.rcCaret
        origin = W.POINT(rect.left, rect.top)
        if not self.u.ClientToScreen(info.hwndCaret, ctypes.byref(origin)):
            return None
        point = _rect_point((origin.x, origin.y, rect.right - rect.left, rect.bottom - rect.top))
        return point if self.valid(point, focus) else None


class _UIABackend:
    """Created and used only by _Worker's persistent, windowless MTA thread."""
    def __init__(self):
        import comtypes
        # A first-ever comtypes import initializes this thread as STA. This is
        # our new dedicated thread, so balance that import before entering MTA.
        try:
            comtypes.CoInitializeEx(0)
        except (comtypes.COMError, OSError) as error:
            # comtypes 1.4's OleDLL/HRESULT call raises OSError here, while
            # other wrappers expose COMError; both carry RPC_E_CHANGED_MODE.
            code = getattr(error, 'hresult', getattr(error, 'winerror', None))
            if code != -2147417850:
                raise
            comtypes.CoUninitialize()
            comtypes.CoInitializeEx(0)
        self.comtypes = comtypes
        try:
            import comtypes.client
            self.interfaces = comtypes.client.GetModule('UIAutomationCore.dll')
            self.automation = comtypes.client.CreateObject(
                self.interfaces.CUIAutomation,
                interface=self.interfaces.IUIAutomation)
            self.windows = _Windows()
        except Exception:
            self.automation = None
            comtypes.CoUninitialize()
            raise

    def locate(self, focus):
        if not self.windows.current(focus):
            return None
        element = self.automation.GetFocusedElement()
        if element is None or not element.CurrentHasKeyboardFocus or element.CurrentIsOffscreen:
            return None
        identity = tuple(element.GetRuntimeId() or ())
        if not identity:
            return None
        # A text provider can have NativeWindowHandle == 0; walk only ancestors
        # to establish its real top-level window, not arbitrary nearby elements.
        ancestor = element
        for _ in range(16):
            hwnd = ancestor.CurrentNativeWindowHandle
            if hwnd:
                if not self.windows.root_matches(hwnd, focus):
                    return None
                break
            ancestor = self.automation.ControlViewWalker.GetParentElement(ancestor)
            if ancestor is None:
                return None
        else:
            return None
        point = _pattern_point(element, self.interfaces)
        if point is None:
            return None
        bounds = element.CurrentBoundingRectangle
        if not all(math.isfinite(float(v)) for v in (bounds.left, bounds.top, bounds.right, bounds.bottom)):
            return None
        if not (bounds.left <= point[0] < bounds.right and bounds.top <= point[1] < bounds.bottom):
            return None
        current = self.automation.GetFocusedElement()
        if (current is None or not current.CurrentHasKeyboardFocus or
                tuple(current.GetRuntimeId() or ()) != identity):
            return None
        return point if self.windows.valid(point, focus) else None

    def close(self):
        self.automation = None
        self.comtypes.CoUninitialize()


class _Worker:
    """One request total. A stalled provider cannot spawn workers or grow a queue."""
    def __init__(self, factory=_UIABackend):
        self.factory = factory
        self.requests = queue.Queue(maxsize=1)
        self.lock = threading.Lock()
        self.busy = False
        self.thread = threading.Thread(target=self._run, name='STOOM-caret-uia', daemon=True)
        self.thread.start()

    def _run(self):
        try:
            backend = self.factory()
        except Exception:
            backend = None
        try:
            while True:
                request = self.requests.get()
                if request is None:
                    return
                focus, deadline, finished, result = request
                try:
                    if backend is not None and time.monotonic() < deadline:
                        point = backend.locate(focus)
                        if (time.monotonic() < deadline and isinstance(point, tuple) and
                                len(point) == 2 and all(type(v) is int for v in point)):
                            result.append(point)
                except Exception:
                    pass
                finally:
                    with self.lock:
                        self.busy = False
                    finished.set()
        finally:
            if backend is not None:
                backend.close()

    def locate(self, focus, timeout):
        finished, result = threading.Event(), []
        with self.lock:
            if self.busy:
                return None
            self.busy = True
            self.requests.put_nowait((focus, time.monotonic() + timeout, finished, result))
        finished.wait(timeout)
        return result[0] if finished.is_set() and result else None


_worker = None
_worker_lock = threading.Lock()


def warmup():
    """Start COM preparation asynchronously; does not inspect the focused app."""
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = _Worker()


def locate(focus, timeout=.25):
    """Return a visible caret point for the captured foreground, or None."""
    try:
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            return None
        timeout = min(timeout, 1.0)
        deadline = time.monotonic() + timeout
        captured = _Focus(int(focus.foreground), int(focus.keyboard_window), int(focus.thread_id))
        windows = _Windows()
        point = windows.native(captured)
        if point is not None:
            return point
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not windows.current(captured):
            return None
        warmup()
        point = _worker.locate(captured, remaining)
        return point if windows.valid(point, captured) else None
    except Exception:
        return None
