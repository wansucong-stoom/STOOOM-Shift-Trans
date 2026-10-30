"""Optional legacy provider diagnostic route; no GUI or live document.

The production shortcut now uses the common keyboard route. These retained
checks still exercise provider settling through an explicit legacy entry.
"""

import heapq
import os
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
# Importing main creates its data directories.  Keep even those out of the
# user's actual application data while exercising its unbound App methods.
with tempfile.TemporaryDirectory() as import_data:
    previous_data = os.environ.get('LOCALAPPDATA')
    os.environ['LOCALAPPDATA'] = import_data
    try:
        import main
    finally:
        if previous_data is None:
            del os.environ['LOCALAPPDATA']
        else:
            os.environ['LOCALAPPDATA'] = previous_data


class Clock:
    def __init__(self, now=10.0):
        self.now = now
        self.pending = []
        self.serial = 0

    def single_shot(self, milliseconds, callback):
        self.serial += 1
        heapq.heappush(self.pending, (self.now + milliseconds / 1000, self.serial, callback))

    def until(self, end):
        callbacks = 0
        while self.pending and self.pending[0][0] <= end + 1e-9:
            self.now, _, callback = heapq.heappop(self.pending)
            callback()
            callbacks += 1
            assert callbacks < 1000, 'settling must not spin or schedule an unbounded burst'
        self.now = end


class Box:
    def __init__(self, text):
        self.text = text

    def currentText(self):
        return self.text


class Snapshot:
    def __init__(self, text):
        self.text = text

    def fingerprint(self):
        return ('paragraph', self.text)


class World:
    def __init__(self):
        self.clock = Clock()
        self.focus = types.SimpleNamespace(foreground=7)
        self.rid = (1, 2)
        self.revision = 7
        self.last_activity = self.clock.now - 1
        self.modifiers = set()
        self.provider = lambda: '안녕하세요'
        self.captures = []
        self.focus_captures = 0

    def capture_focus(self):
        self.focus_captures += 1
        return self.focus

    def capture(self):
        text = self.provider()
        self.captures.append((self.clock.now, text))
        return self.rid, text, ('range', Snapshot(text))

    def install(self):
        main.time = types.SimpleNamespace(monotonic=lambda: self.clock.now)
        main.QTimer = types.SimpleNamespace(singleShot=self.clock.single_shot)
        main.ctypes = types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(
            GetAsyncKeyState=lambda key: 0x8000 if key in self.modifiers else 0)))
        main.focus_guard.capture = self.capture_focus
        main.focus_guard.unchanged = lambda focus: focus is self.focus
        main.focus_guard.same_foreground = lambda focus: focus is self.focus
        main.focused_element = lambda: (self.rid, None, None)
        main.capture_input = self.capture


class FakeApp:
    run_translation = main.App.run_translation
    begin_keyboard_capture = main.App.begin_legacy_capture
    poll_input = main.App.poll_input
    cancel_pending_input = main.App.cancel_pending_input
    engine_configuration = main.App.engine_configuration

    def __init__(self, world):
        self.world = world
        self._quitting = False
        self.busy = False
        self._pending_input = None
        self.engine_initializing = False
        self.target = {'shift': Box('영어'), 'ctrl': Box('사용 안 함')}
        self.source = Box('자동')
        self.engine = Box('기본 오프라인 엔진')
        self.external_path = ''
        self.tap = types.SimpleNamespace(activity_snapshot=lambda: (world.revision, world.last_activity))
        self.starts = []
        self.errors = []

    def isActiveWindow(self):
        return False

    def start_translation(self, key, focus, rid, text, context):
        # This is the only hand-off into translation.  No real engine, thread,
        # paste, selection, clipboard or keyboard action occurs in this test.
        self.starts.append((self.world.clock.now, key, focus, rid, text, context))

    def error(self, text):
        self.errors.append(text)
        self.cancel_pending_input()
        self.busy = False

    def gesture(self, started=None, revision=None):
        self.run_translation(('shift', self.world.revision if revision is None else revision,
                              self.world.clock.now if started is None else started))


def forbidden(*args, **kwargs):
    raise AssertionError('settling must not synthesize keys, select text or touch the clipboard')


# Guard the common mutation entry points even if an accidental future change
# tries to call them before the fake translation hand-off.
main.keyboard.Controller = forbidden
main.clipboard_lease.ClipboardLease = forbidden
main.range_access.capture = forbidden


def setup():
    world = World()
    world.install()
    return world, FakeApp(world)


# UIA initially reports the penultimate IME text.  A changing provider sample
# must settle again, and only the completed final text is handed off once.
w, app = setup()
start = w.clock.now
w.last_activity = start - .02
w.provider = lambda: '안녕하세' if w.clock.now < start + .19 else '안녕하세요'
app.gesture()
w.clock.until(start + .11)
assert not w.captures and not app.starts, 'no provider access before typing quiet time'
w.clock.until(start + .25)
assert [text for _, text in w.captures] == ['안녕하세', '안녕하세', '안녕하세요', '안녕하세요']
assert not app.starts, 'a changed final syllable must restart the stability interval'
w.clock.until(start + .50)
assert len(app.starts) == 1 and app.starts[0][4] == '안녕하세요'
assert app._pending_input is None and not app.errors
w.clock.until(start + .75)
assert len(app.starts) == 1, 'one gesture must never start duplicate translations'


# Ordinary key down cancels rather than including newly typed text.  Its old
# queued callback cannot revive the request or replace a newer pending one.
w, app = setup()
app.gesture()
old_request = app._pending_input
old_timer = w.clock.pending[0][2]
w.revision += 1
w.last_activity = w.clock.now
app.poll_input(old_request)
assert not app.busy and app._pending_input is None and not app.starts
w.clock.now += .01
app.gesture()
new_request = app._pending_input
old_timer()
assert app._pending_input is new_request and not app.starts
w.clock.until(w.clock.now + .5)
assert len(app.starts) == 1 and app._pending_input is None and not app.errors


# Native focus, UIA runtime identity and configuration each bind the request.
for change in ('focus', 'rid', 'configuration'):
    w, app = setup()
    app.gesture()
    if change == 'focus':
        w.focus = types.SimpleNamespace(foreground=8)
    elif change == 'rid':
        # UIA reads are deliberately deferred until the native/keyboard quiet
        # gate opens; bind the first sampled identity before changing it.
        w.clock.until(w.clock.now + .09)
        assert w.captures and not app.starts
        w.rid = (3, 4)
    else:
        app.target['shift'].text = '일본어'
    w.clock.until(w.clock.now + .5)
    assert not app.busy and app._pending_input is None and not app.starts, change
    assert not app.errors, 'normal cancellation should stay quiet: ' + change


# Keyboard hook payload survives Qt delivery delay: the original release time
# is retained, while typing before delivery causes immediate rejection.
w, app = setup()
released = w.clock.now
w.clock.now += .6
app.gesture(started=released)
assert app._pending_input['gate'].started == released
w.clock.until(w.clock.now + .3)
assert len(app.starts) == 1
assert app.starts[0][0] - (released + .6) <= .3

w, app = setup()
released, revision = w.clock.now, w.revision
w.clock.now += .2
w.revision += 1
app.gesture(started=released, revision=revision)
assert not app.busy and app._pending_input is None
assert not w.clock.pending and not w.captures and w.focus_captures == 0


# The hook's old timestamp also bounds a request already expired in the queue.
w, app = setup()
released = w.clock.now
w.clock.now += 2.3
app.gesture(started=released)
w.clock.until(w.clock.now + .1)
assert app.errors and not app.busy and app._pending_input is None
assert not app.starts and not w.captures


# A transient failed provider read clears previous stability.  Success after
# the read failure must build a fresh stable interval, rather than paste early.
w, app = setup()
start = w.clock.now
reads = [0]
def briefly_unavailable():
    reads[0] += 1
    if reads[0] == 2:
        raise RuntimeError('provider still updating')
    return '안녕하세요'
w.provider = briefly_unavailable
app.gesture()
w.clock.until(start + .15)
assert not app.starts, 'a failed read must discard the sample from before it'
w.clock.until(start + .4)
assert len(app.starts) == 1 and not app.errors


# Persistent provider failure reaches the bounded timeout, releases busy, and
# permits a new request immediately after the provider becomes available.
w, app = setup()
def unavailable():
    raise RuntimeError('provider unavailable')
w.provider = unavailable
app.gesture()
w.clock.until(w.clock.now + 2.4)
assert app.errors == ['provider unavailable']
assert not app.busy and app._pending_input is None and not app.starts
w.provider = lambda: '다시 시도합니다'
app.gesture()
w.clock.until(w.clock.now + .3)
assert len(app.starts) == 1 and app.starts[0][4] == '다시 시도합니다'


# A stable already-quiet input should only pay the short sampling interval,
# not a fixed one- or two-second delay after every shortcut.
w, app = setup()
released = w.clock.now
app.gesture()
w.clock.until(released + .3)
assert len(app.starts) == 1
overhead = app.starts[0][0] - released
assert .08 <= overhead <= .3, overhead
assert not app.errors

print('input settle flow: provider lag, passive reads, cancellation, queued gestures, stale timers, read recovery and timeout: PASS')
print('already-quiet stable input simulated hand-off overhead: %.0f ms (limit 300 ms)' % (overhead * 1000))
