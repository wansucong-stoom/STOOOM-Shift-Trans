"""Caret lookup contracts; no real UI, keyboard, mouse, document or clipboard."""
import pathlib
import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import caret_locator as c


class Range:
    def __init__(self, start=2, end=2, boxes=(), text='x', adjacent=None):
        self.start, self.end = start, end
        self.boxes, self.text, self.adjacent = boxes, text, adjacent
    def CompareEndpoints(self, endpoint, other, other_endpoint):
        return (self.start, self.end)[endpoint] - (other.start, other.end)[other_endpoint]
    def GetBoundingRectangles(self):
        return self.boxes
    def Clone(self):
        copy = Range(self.start, self.end, self.boxes, self.text, self.adjacent)
        return copy
    def MoveEndpointByUnit(self, endpoint, unit, amount):
        assert unit == 0
        config = (self.adjacent or {}).get(amount)
        if config is None:
            return 0
        self.boxes, self.text = config
        if endpoint == 0:
            self.start += amount
        else:
            self.end += amount
        return amount
    def GetText(self, maximum):
        assert maximum == 3
        return self.text[:maximum]


class Pattern:
    def __init__(self, rng, active=True):
        self.rng, self.active = rng, active
    def QueryInterface(self, interface):
        return self
    def GetCaretRange(self):
        return self.active, self.rng
    def GetSelection(self):
        return types.SimpleNamespace(Length=1, GetElement=lambda index: self.rng)


class Element:
    def __init__(self, v2=None, old=None):
        self.v2, self.old, self.calls = v2, old, []
    def GetCurrentPattern(self, identifier):
        self.calls.append(identifier)
        return self.v2 if identifier == 10024 else self.old


class WinAPI:
    def __init__(self):
        self.foreground = 100
        self.at_point = 101
        self.monitor = 1
        self.visible = True
        self.rect = (-1920, -1080, -500, 700)
    def GetForegroundWindow(self):
        return self.foreground
    def GetAncestor(self, hwnd, kind):
        assert kind == 2
        return 100 if hwnd in (100, 101) else 200
    def IsWindowVisible(self, hwnd):
        return self.visible
    def GetWindowRect(self, hwnd, output):
        output._obj.left, output._obj.top, output._obj.right, output._obj.bottom = self.rect
        return True
    def WindowFromPoint(self, point):
        return self.at_point
    def MonitorFromPoint(self, point, flags):
        assert flags == 0
        return self.monitor
    def GetGUIThreadInfo(self, thread_id, output):
        info = output._obj
        info.hwndFocus = 101
        info.hwndCaret = 101
        info.rcCaret.left, info.rcCaret.top = 20, 30
        info.rcCaret.right, info.rcCaret.bottom = 20, 50
        return True
    def ClientToScreen(self, hwnd, output):
        output._obj.x -= 1920
        output._obj.y -= 1080
        return True


class CaretTests(unittest.TestCase):
    def test_negative_monitor_and_zero_width(self):
        self.assertEqual(c._rect_point((-1400, -400, 0, 20)), (-1400, -390))

    def test_invalid_or_paragraph_rectangles(self):
        for rectangle in ((0, 0, 300, 20), (0, 0, -1, 20), (0, 0, 1, 0),
                          (float('nan'), 0, 1, 20), (0, float('inf'), 1, 20),
                          (2**31, 0, 1, 20), (0, 0, 1, 20, 0, 20, 1, 20)):
            with self.subTest(rectangle=rectangle):
                self.assertIsNone(c._rect_point(rectangle))

    def test_nonempty_selection_rejected_even_with_narrow_rectangle(self):
        self.assertIsNone(c._range_point(Range(2, 3, (10, 20, 1, 20))))

    def test_collapsed_range_rectangle(self):
        self.assertEqual(c._range_point(Range(boxes=(10, 20, 0, 20))), (10, 30))

    def test_adjacent_character_without_expanding_paragraph(self):
        rng = Range(adjacent={1: ((10, 20, 12, 20), '가')})
        self.assertEqual(c._range_point(rng), (16, 30))
        self.assertEqual((rng.start, rng.end), (2, 2))

    def test_line_end_uses_previous_character_not_newline(self):
        rng = Range(adjacent={1: ((10, 20, 0, 20), '\r'), -1: ((2, 20, 8, 20), 'x')})
        self.assertEqual(c._range_point(rng), (6, 30))

    def test_provider_expansion_or_multiple_lines_rejected(self):
        for boxes, text in (((10, 20, 200, 20), 'paragraph'),
                            ((10, 20, 10, 20, 20, 40, 10, 20), 'x'),
                            ((10, 20, 10, 20), '\ufffc')):
            self.assertIsNone(c._range_point(Range(adjacent={1: (boxes, text)})))

    def test_active_textpattern2_is_preferred(self):
        el = Element(Pattern(Range(boxes=(10, 20, 0, 20))), Pattern(Range(0, 20)))
        interfaces = types.SimpleNamespace(IUIAutomationTextPattern2=object, IUIAutomationTextPattern=object)
        self.assertEqual(c._pattern_point(el, interfaces), (10, 30))
        self.assertEqual(el.calls, [10024])

    def test_inactive_v2_does_not_fall_back_to_stale_selection(self):
        el = Element(Pattern(Range(boxes=(10, 20, 0, 20)), False), Pattern(Range(boxes=(30, 40, 0, 20))))
        interfaces = types.SimpleNamespace(IUIAutomationTextPattern2=object, IUIAutomationTextPattern=object)
        self.assertIsNone(c._pattern_point(el, interfaces))
        self.assertEqual(el.calls, [10024])

    def test_older_pattern_only_accepts_collapsed_selection(self):
        interfaces = types.SimpleNamespace(IUIAutomationTextPattern=object)
        self.assertEqual(c._pattern_point(Element(old=Pattern(Range(boxes=(1, 2, 0, 20)))), interfaces), (1, 12))
        self.assertIsNone(c._pattern_point(Element(old=Pattern(Range(0, 4, (1, 2, 10, 20)))), interfaces))

    def test_native_success_never_starts_uia(self):
        windows = types.SimpleNamespace(native=lambda focus: (-2, 20))
        with patch.object(c, '_Windows', return_value=windows), patch.object(c, 'warmup') as warmup:
            self.assertEqual(c.locate(c._Focus(1, 2, 3)), (-2, 20))
            warmup.assert_not_called()

    def test_changed_foreground_never_queries_provider(self):
        windows = types.SimpleNamespace(native=lambda focus: None, current=lambda focus: False)
        with patch.object(c, '_Windows', return_value=windows), patch.object(c, 'warmup') as warmup:
            self.assertIsNone(c.locate(c._Focus(1, 2, 3)))
            warmup.assert_not_called()

    def test_late_result_revalidated_before_return(self):
        windows = types.SimpleNamespace(native=lambda focus: None, current=lambda focus: True,
                                       valid=lambda point, focus: False)
        with patch.object(c, '_Windows', return_value=windows), patch.object(c, 'warmup'), \
             patch.object(c, '_worker', types.SimpleNamespace(locate=lambda focus, timeout: (10, 20))):
            self.assertIsNone(c.locate(c._Focus(1, 2, 3)))

    def test_native_client_coordinates_are_mapped_to_negative_monitor(self):
        windows = object.__new__(c._Windows)
        windows.u = WinAPI()
        self.assertEqual(windows.native(c._Focus(100, 101, 7)), (-1900, -1040))

    def test_window_monitor_and_visibility_rejections(self):
        windows = object.__new__(c._Windows)
        focus = c._Focus(100, 101, 7)
        for attr, value in (('foreground', 200), ('at_point', 200), ('monitor', 0), ('visible', False)):
            with self.subTest(attr=attr):
                windows.u = WinAPI()
                setattr(windows.u, attr, value)
                self.assertFalse(windows.valid((-1900, -1040), focus))
        windows.u = WinAPI()
        self.assertFalse(windows.valid((20, 20), focus))

    def test_uia_backend_rejects_focus_identity_change_and_offscreen(self):
        element = Element(Pattern(Range(boxes=(10, 20, 0, 20))))
        element.CurrentHasKeyboardFocus = True
        element.CurrentIsOffscreen = False
        element.CurrentNativeWindowHandle = 100
        element.GetRuntimeId = lambda: (1, 2, 3)
        element.CurrentBoundingRectangle = types.SimpleNamespace(left=0, top=0, right=100, bottom=100)
        backend = object.__new__(c._UIABackend)
        backend.windows = types.SimpleNamespace(current=lambda focus: True,
                            root_matches=lambda hwnd, focus: hwnd == focus.foreground,
                            valid=lambda point, focus: True)
        backend.interfaces = types.SimpleNamespace(IUIAutomationTextPattern2=object)
        backend.automation = types.SimpleNamespace(GetFocusedElement=lambda: element)
        focus = c._Focus(100, 101, 7)
        self.assertEqual(backend.locate(focus), (10, 30))
        changed = types.SimpleNamespace(CurrentHasKeyboardFocus=True, GetRuntimeId=lambda: (9,))
        sequence = iter((element, changed))
        backend.automation.GetFocusedElement = lambda: next(sequence)
        self.assertIsNone(backend.locate(focus))
        element.CurrentIsOffscreen = True
        backend.automation.GetFocusedElement = lambda: element
        self.assertIsNone(backend.locate(focus))

    def check_com_initialization(self, first_error=None):
        events = []
        module = types.ModuleType('comtypes')
        class COMError(Exception):
            hresult = -2147417850
        def initialize(flags):
            self.assertEqual(flags, 0)
            events.append('initialize')
            if events == ['initialize'] and first_error is not None:
                raise first_error
        module.COMError = COMError
        module.CoInitializeEx = initialize
        module.CoUninitialize = lambda: events.append('uninitialize')
        client = types.ModuleType('comtypes.client')
        client.GetModule = lambda name: types.SimpleNamespace(CUIAutomation=object, IUIAutomation=object)
        client.CreateObject = lambda *args, **kwargs: object()
        module.client = client
        with patch.dict(sys.modules, {'comtypes': module, 'comtypes.client': client}), \
             patch.object(c, '_Windows', return_value=object()):
            backend = c._UIABackend()
            backend.close()
        return events

    def test_comtypes_first_import_sta_is_balanced_before_mta(self):
        error = OSError('changed apartment')
        error.winerror = -2147417850
        self.assertEqual(self.check_com_initialization(error),
                         ['initialize', 'uninitialize', 'initialize', 'uninitialize'])

    def test_comtypes_already_imported_does_not_uninitialize_another_thread(self):
        self.assertEqual(self.check_com_initialization(), ['initialize', 'uninitialize'])

    def test_stalled_provider_has_bounded_wait_and_no_growing_queue(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Backend:
            def locate(self, focus):
                calls.append(threading.get_ident())
                entered.set()
                release.wait(2)
                return (10, 20)
            def close(self):
                pass
        worker = c._Worker(Backend)
        started = time.monotonic()
        try:
            self.assertIsNone(worker.locate(c._Focus(1, 2, 3), .04))
            self.assertLess(time.monotonic() - started, .4)
            self.assertTrue(entered.is_set())
            for _ in range(20):
                self.assertIsNone(worker.locate(c._Focus(1, 2, 3), .04))
            self.assertEqual(len(calls), 1)
            self.assertEqual(worker.requests.qsize(), 0)
            self.assertNotEqual(calls[0], threading.get_ident())
        finally:
            release.set()
            worker.requests.put(None)
            worker.thread.join(2)
        self.assertFalse(worker.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
