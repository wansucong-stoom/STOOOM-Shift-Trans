"""Opt-in diagnostic clicks only; default selection never uses this helper."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import keyboard_access as k


class Cursor:
    def __init__(self):self.position=(70,80);self.fail_once=False
    def GetCursorPos(self,pointer):
        if self.fail_once:self.fail_once=False;return False
        pointer._obj.x,pointer._obj.y=self.position;return True


class Env:
    def __init__(self,interaction=None,final_move=False):
        self.u=Cursor();self.focus=object();self.revision=7;self.focused=True;self.clock=0.
        self.moves=[];self.clicks=[];self.sent=[];self.interaction=interaction;self.final_move=final_move
        self.changed=set();self.cause='unknown'
    def caret_point(self):return (10,20)
    def current(self):return self.focused
    def activity(self):return self.revision,self.clock
    def activity_cause(self):return self.cause
    def now(self):return self.clock
    def _move(self,point):self.moves.append(point);self.u.position=point
    def _send(self,events):
        assert all(event.kind==0 and event.mouse.extra==k.INPUT_TAG for event in events)
        self.sent.extend(events);self.clicks.append(self.u.position)
    def click(self):k.Windows.click(self)
    def sleep(self,seconds):
        self.clock+=seconds;count=len(self.clicks)
        if count in self.changed:return
        self.changed.add(count)
        if self.interaction and count==1:
            self.revision=8;self.cause=self.interaction
            if self.interaction in ('click','drag'):self.u.position=(90,91)
        elif count in (1,2):self.u.position=(11+count,22+count)
        elif self.final_move and count==3:self.u.position=(99,98)


# Coordinate-only drift does not alter the activity revision. All three actual
# tagged clicks must target the original caret point, followed by restoration.
e=Env();driver=k.Driver(e)
assert k.Windows.select_by_click(e,lambda:driver.guard(7),lambda seconds:driver.pause(seconds,7))=='unknown'
assert e.clicks==[(10,20)]*3 and e.moves==[(10,20)]*3+[(70,80)]
assert e.u.position==(70,80) and len(e.sent)==6
assert [event.mouse.flags for event in e.sent]==[2,4]*3

# A transient coordinate read failure also retargets instead of cancelling.
e=Env();driver=k.Driver(e)
calls=[0];read=e.u.GetCursorPos
def intermittent(pointer):
    calls[0]+=1
    if calls[0]==2:return False
    return read(pointer)
e.u.GetCursorPos=intermittent
k.Windows.select_by_click(e,lambda:driver.guard(7),lambda seconds:driver.pause(seconds,7))
assert e.clicks==[(10,20)]*3 and e.u.position==(70,80)

# Click/drag/typing after the first automatic click cancel before the second
# and do not restore over the user's new pointer position or typing activity.
for action in ('click','drag','typing'):
    e=Env(interaction=action);driver=k.Driver(e)
    try:k.Windows.select_by_click(e,lambda:driver.guard(7),lambda seconds:driver.pause(seconds,7))
    except k.Cancelled:pass
    else:raise AssertionError('Real interaction did not cancel selection')
    assert len(e.clicks)==1 and (70,80) not in e.moves
    assert e.u.position==((90,91) if action in ('click','drag') else (10,20))

# Mere pointer motion after the final click is allowed, and is not overwritten
# by restoring the old location. It does not trigger another click or paste.
e=Env(final_move=True);driver=k.Driver(e)
k.Windows.select_by_click(e,lambda:driver.guard(7),lambda seconds:driver.pause(seconds,7))
assert e.u.position==(99,98) and e.clicks==[(10,20)]*3 and (70,80) not in e.moves
print('Diagnostic click retarget only: coordinate drift/read failure, tagged clicks, real-input guard and pointer restoration: PASS')
