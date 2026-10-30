"""Manual ranges or one Shift+Home, with explicit selection endpoints.

This fixture models text editing, not application APIs. No native input, mouse,
clipboard, document or hooks are used. Other navigation fails immediately.
"""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import keyboard_access as k


class Lease:
    def __init__(self,env):self.env=env;self.text=None;self.kept=False;self.restored=False
    def arm_copy(self):self.text=None;self.env.lease=self
    def read_copy(self,pids):return self.text
    def replace_owned(self,expected,text):assert self.text==expected;self.text=text
    def keep_translation(self):self.kept=True;return 1
    def restore(self):self.restored=not self.kept;return self.restored


class Editor:
    def __init__(self,text,caret,selection=None,visual_start=None,home_works=True):
        self.text=text;self.anchor_pos=self.active=caret
        if selection is not None:self.anchor_pos,self.active=selection
        self.visual_start=visual_start;self.home_works=home_works
        self.revision=7;self.focus=object();self.owner_pids=(123,)
        self.focused=True;self.clock=0.;self.events=[];self.pasted=0;self.selected=0
        self.copy_values=[];self.leases=[];self.after_chord=None;self.held=False
    def activity(self):return self.revision,self.clock
    def current(self):return self.focused
    def modifiers(self):return self.held
    def now(self):return self.clock
    def sleep(self,seconds):self.clock+=seconds
    def safe(self):pass
    def anchor(self):return self.anchor_pos,self.active
    def bounds(self):return min(self.anchor_pos,self.active),max(self.anchor_pos,self.active)
    def factory(self):
        lease=Lease(self);self.leases.append(lease);return lease
    def select(self,guard,pause):
        self.selected+=1;return k.Windows.select(self,guard,pause)
    def chord(self,*keys):
        self.events.append(keys)
        if keys==(k.CTRL,ord('C')):
            start,end=self.bounds()
            self.lease.text=self.text[start:end] if end>start else None
            self.copy_values.append(self.lease.text)
        elif keys==(k.SHIFT,k.HOME):
            if self.home_works:
                start=self.visual_start
                if start is None:
                    start=max(self.text.rfind(mark,0,self.active) for mark in ('\r','\n','\v','\f','\x85','\u2028','\u2029'))+1
                self.active=start
        elif keys==(k.CTRL,ord('V')):
            start,end=self.bounds();replacement=self.lease.text
            self.text=self.text[:start]+replacement+self.text[end:]
            self.anchor_pos=self.active=start+len(replacement);self.pasted+=1
        else:raise AssertionError(('extra navigation/input forbidden',keys))
        if self.after_chord:self.after_chord(self,keys)


def refused(editor,expected=(k.KeyboardError,k.Cancelled)):
    original=editor.text
    try:k.Driver(editor,editor.factory).capture(7)
    except expected:pass
    else:raise AssertionError('empty/invalid selection accepted')
    assert editor.text==original and not editor.pasted
    assert all(lease.restored for lease in editor.leases)


# First/body/cell-like/final contexts use the same rule. A middle caret selects
# only its prefix; text after it and adjacent paragraphs remain unchanged.
for delimiter in ('\n','\r\n','\r','\v','\f','\x85','\u2028','\u2029'):
    contexts=(('',delimiter+'Next line'),('Previous line'+delimiter,delimiter+'Next line'),
              ('[Previous cell]'+delimiter,delimiter+'[Next cell]'),('Previous line'+delimiter,''),
              ('Previous line'+delimiter,delimiter))
    for before,after in contexts:
        for text in ('가','[향후]','(추천사유)','A test line with spaces.','안녕하세요 😀 번역 시험'):
            for offset in sorted({0,len(text)//2,len(text)}):
                original=before+text+after;e=Editor(original,len(before)+offset)
                if offset==0:
                    refused(e)
                    assert e.events.count((k.SHIFT,k.HOME))==1 and e.bounds()==(len(before),len(before))
                    continue
                driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
                assert snapshot.selected_automatically and snapshot.text==text[:offset]
                assert e.text==original and e.bounds()==(len(before),len(before)+offset)
                assert e.selected==1 and e.events.count((k.SHIFT,k.HOME))==1
                assert e.copy_values==[None,text[:offset],text[:offset]] and e.clock<.3
                driver.apply(snapshot,'Replacement')
                assert e.text==before+'Replacement'+text[offset:]+after and e.pasted==1
                assert e.events.count((k.SHIFT,k.HOME))==1 and e.active==len(before)+len('Replacement')

# A visual wrap has no copied separator. Only this display line's prefix is
# selected; the earlier wrapped line and text after the caret remain intact.
before='Earlier paragraph.\r\nFirst wrapped display line ';current='second visual line';after=' still here.\r\nNext paragraph.'
for offset in (0,7,len(current)):
    e=Editor(before+current+after,len(before)+offset,visual_start=len(before))
    if offset==0:refused(e)
    else:
        driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
        assert snapshot.text==current[:offset]
        driver.apply(snapshot,'Translated')
        assert e.text==before+'Translated'+current[offset:]+after
    assert e.events.count((k.SHIFT,k.HOME))==1

# Both manual directions preserve the exact chosen range, including leading /
# trailing separators, multiple paragraphs, intentional blanks and astral text.
for selected in ('ONE','ONE\nTWO','ONE\nTWO\n','\nONE\n','ONE\r\nTWO\r\n','ONE\n\n',
                 'ONE\u2028TWO\u2029','[서비스러닝]','😀'):
    text='PRE|'+selected+'|POST';start=4;end=start+len(selected)
    for anchor,active in ((start,end),(end,start)):
        e=Editor(text,active,selection=(anchor,active));driver=k.Driver(e,e.factory)
        snapshot=driver.capture(7)
        assert snapshot.text==selected and not snapshot.selected_automatically
        assert e.anchor()==(anchor,active) and e.text==text and not e.selected
        assert all(keys==(k.CTRL,ord('C')) for keys in e.events)
        driver.apply(snapshot,'replacement\nrequested separators\n')
        assert e.text=='PRE|replacement\nrequested separators\n|POST' and e.pasted==1
        assert (k.SHIFT,k.HOME) not in e.events

# Blank lines or unsupported Home do not trigger another selection strategy.
for text,caret in (('Previous\n',9),('Previous\r\n\r\nNext',10),('',0)):
    e=Editor(text,caret);refused(e)
    assert e.events.count((k.SHIFT,k.HOME))==1 and e.selected==1
e=Editor('Previous\nUnchanged\nNext',len('Previous\nUnchanged'),home_works=False);refused(e)
assert e.events.count((k.SHIFT,k.HOME))==1
for whitespace in (' ','\n','\r\n','\n\n'):
    e=Editor('PRE'+whitespace+'POST',3,selection=(3,3+len(whitespace)));refused(e)
    assert not e.selected and (k.SHIFT,k.HOME) not in e.events

# Legacy callers cannot re-enable temporary Space/Backspace edits.
e=Editor('Before\nSource',len('Before\nSource'));driver=k.Driver(e,e.factory)
snapshot=driver.capture(7,commit_space=True)
assert snapshot.text=='Source' and e.text=='Before\nSource' and e.events.count((k.SHIFT,k.HOME))==1

# A changed second copy fails instead of accepting a stale source snapshot.
e=Editor('Source',6)
e.after_chord=lambda env,keys:setattr(env,'text','Changed') if len(env.copy_values)==2 else None
original=e.text
try:k.Driver(e,e.factory).capture(7)
except k.Cancelled:pass
else:raise AssertionError('changed source accepted')
assert e.text=='Changed' and not e.pasted and e.events.count((k.SHIFT,k.HOME))==1

# Real input/focus loss stops before the next key, including immediately after
# Home. These guards and the source check before paste remain part of capture.
for interrupted in ((k.CTRL,ord('C')),(k.SHIFT,k.HOME)):
    for cause in ('typing','focus'):
        e=Editor('Previous\nSource\nNext',len('Previous\nSource'))
        def interrupt(env,keys):
            if keys==interrupted:
                if cause=='typing':env.revision+=1
                else:env.focused=False
        e.after_chord=interrupt;refused(e,k.Cancelled)
        assert e.events[-1]==interrupted
for cause in ('typing','focus','source'):
    e=Editor('Previous\nSource\nNext',len('Previous\nSource'));driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
    if cause=='typing':e.revision+=1
    elif cause=='focus':e.focused=False
    else:e.text=e.text.replace('Source','Edited')
    original=e.text
    try:driver.apply(snapshot,'Must not paste')
    except (k.KeyboardError,k.Cancelled):pass
    else:raise AssertionError('stale source/focus/input accepted')
    assert e.text==original and not e.pasted and e.events.count((k.SHIFT,k.HOME))==1

# The default route ignores caret/mouse geometry, including table handles.
def forbidden_mouse(*args,**kwargs):raise AssertionError('default path accessed mouse/caret geometry')
e=Editor('Previous\nCurrent\nNext',len('Previous\nCurrent'))
e.caret_point=forbidden_mouse;e._move=forbidden_mouse;e.click=forbidden_mouse
e.u=NS(GetCursorPos=forbidden_mouse,WindowFromPoint=forbidden_mouse)
driver=k.Driver(e,e.factory);driver.apply(driver.capture(7),'Only current')
assert e.text=='Previous\nOnly current\nNext' and e.pasted==1
e=Editor('Source',6);e.held=True;refused(e)
assert not e.events and not e.selected
print('PASS: exact forward/backward manual ranges; one current-visual-line Shift+Home; start/middle/end, '
      'separators, wraps, no adjacent-line retry, stale input and one paste')
