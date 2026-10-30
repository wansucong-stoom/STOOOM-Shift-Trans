"""Partial Win32 input delivery must not leave STOOM-owned downs held.

All delivery is simulated; this test never sends OS input or installs hooks.
"""
import ctypes
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import keyboard_access as k


def describe(event):
    if event.kind==1:
        return ('key',event.key.vk,event.key.scan,event.key.flags,event.key.extra)
    return ('mouse',event.mouse.flags,event.mouse.extra)


class User32:
    def __init__(self,counts):
        self.counts=list(counts);self.calls=[];self.held=set()
    def SendInput(self,count,batch,size):
        assert size==ctypes.sizeof(k.INPUT)
        values=[describe(batch[i]) for i in range(count)]
        self.calls.append(values)
        accepted=min(count,self.counts.pop(0)) if self.counts else count
        for event in values[:accepted]:
            if event[0]=='key':
                identity=(event[0],event[1],event[2],event[3]&~2)
                if event[3]&2:self.held.discard(identity)
                else:self.held.add(identity)
            else:
                if event[1]&4:self.held.discard(('left',))
                elif event[1]&2:self.held.add(('left',))
        return accepted


def instance(counts):
    native=k.Windows.__new__(k.Windows);native.u=User32(counts)
    return native


for keys in ((k.CTRL,ord('V')),(k.CTRL,k.SHIFT,k.UP)):
    total=len(keys)*2
    for accepted in range(total+1):
        native=instance([accepted])
        try:native.chord(*keys)
        except k.KeyboardError:assert accepted<total
        else:assert accepted==total
        assert not native.u.held,(keys,accepted,native.u.calls)
        for call in native.u.calls[1:]:
            assert all(e[0]=='key' and e[3]&2 and e[4]==k.INPUT_TAG for e in call)
        if accepted in (0,total):assert len(native.u.calls)==1

# A partial release may be retried; only its still-unaccepted ups are resent.
native=instance([3,1,1,1]);native.report=lambda *a,**kw:None
try:native.chord(k.CTRL,k.SHIFT,k.UP)
except k.KeyboardError:pass
else:raise AssertionError('partial chord accepted')
assert len(native.u.calls)==4  # bounded cleanup, never replay the chord
assert not native.u.held
assert all(e[3]&2 for call in native.u.calls[1:] for e in call)
assert native.u.calls[2]==native.u.calls[1][1:]
assert native.u.calls[3]==native.u.calls[2][1:]

# One temporary rejection followed by one-up-at-a-time progress also finishes.
native=instance([3,0,1,1,1])
try:native.chord(k.CTRL,k.SHIFT,k.UP)
except k.KeyboardError:pass
assert not native.u.held and len(native.u.calls)==5

# A permanently blocked cleanup cannot spin, suppress the error, or replay down.
native=instance([1,0,0])
try:native.chord(k.CTRL,ord('V'))
except k.KeyboardError:pass
else:raise AssertionError('blocked input accepted')
assert len(native.u.calls)==3
assert native.u.calls[1]==native.u.calls[2]
assert all(e[3]&2 for call in native.u.calls[1:] for e in call)

for accepted in (0,1,2):
    native=instance([accepted])
    try:native.click()
    except k.KeyboardError:assert accepted<2
    assert not native.u.held
    assert all(e==('mouse',4,k.INPUT_TAG) for call in native.u.calls[1:] for e in call)

# A move has no button down and needs no synthetic button/key release.
event=k.INPUT();event.kind=0
event.mouse=k.MOUSEINPUT(1,1,0,1,0,k.INPUT_TAG)
native=instance([0])
try:native._send([event])
except k.KeyboardError:pass
assert len(native.u.calls)==1
print('SendInput accepted-prefix cleanup: copy/paste chords, extended navigation, mouse, bounded failure: PASS')
