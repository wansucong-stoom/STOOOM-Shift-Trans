"""An explicit diagnostic click host can use one common-key fallback.

The simulated cell has a final CRLF caret boundary. These checks do not claim
that an actually empty terminal paragraph can be distinguished universally.
Default Windows.select never uses click selection; it goes directly to keys.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import keyboard_access as k


class Lease:
    def __init__(self,env):self.env=env;self.text=None;self.kept=False
    def arm_copy(self):self.text=None;self.env.lease=self
    def read_copy(self,pids):return self.text
    def replace_owned(self,expected,text):assert self.text==expected;self.text=text
    def keep_translation(self):self.kept=True;return 1
    def restore(self):return not self.kept


class Cell:
    def __init__(self,body,click='whitespace',caret='end',manual=None):
        self.prefix='Previous paragraph.\r\n';self.body=body
        self.text=self.prefix+body+'\r\n';self.start=len(self.prefix);self.end=self.start+len(body)
        self.anchor_pos=self.active=self.start if caret=='start' else self.end
        if manual is not None:self.anchor_pos,self.active=manual(self)
        self.focus=object();self.owner_pids=(42,);self.revision=7;self.clock=0.
        self.events=[];self.selected=0;self.pasted=0;self.copy_values=[]
        self.click=click;self.just_clicked=False;self.after_chord=None
    def activity(self):return self.revision,self.clock
    def current(self):return True
    def modifiers(self):return False
    def now(self):return self.clock
    def sleep(self,seconds):self.clock+=seconds
    def safe(self):pass
    def anchor(self):return self.anchor_pos,self.active
    def factory(self):return Lease(self)
    def bounds(self):return min(self.anchor_pos,self.active),max(self.anchor_pos,self.active)
    def down(self,position):
        end=self.text.find('\n',position)
        return len(self.text) if end<0 else end+1
    def select(self,guard,pause):
        guard();self.selected+=1;self.just_clicked=True
        if self.click=='whitespace':self.anchor_pos,self.active=self.end,self.end+2
        elif self.click=='body':self.anchor_pos,self.active=self.start,self.end
        elif self.click not in ('none','empty'):raise AssertionError(self.click)
        return 'unknown'
    def chord(self,*keys):
        self.events.append(keys)
        if keys==(k.CTRL,ord('C')):
            start,end=self.bounds()
            self.lease.text=self.text[start:end] if end>start else None
            if self.just_clicked and self.click=='empty':self.lease.text=''
            self.just_clicked=False;self.copy_values.append(self.lease.text)
        elif keys==(k.LEFT,):
            start,end=self.bounds();self.active=start if start!=end else max(0,self.active-1)
            self.anchor_pos=self.active
        elif keys==(k.CTRL,k.DOWN):self.active=self.down(self.active);self.anchor_pos=self.active
        elif keys==(k.CTRL,k.SHIFT,k.UP):self.active=self.text.rfind('\n',0,max(0,self.active-1))+1
        elif keys==(k.CTRL,k.SHIFT,k.DOWN):self.active=self.down(self.active)
        elif keys==(k.SHIFT,k.LEFT):
            self.active-=2 if self.text[max(0,self.active-2):self.active]=='\r\n' else 1
        elif keys==(k.CTRL,ord('V')):
            start,end=self.bounds();replacement=self.lease.text
            self.text=self.text[:start]+replacement+self.text[end:]
            self.anchor_pos=self.active=start+len(replacement);self.pasted+=1
        else:raise AssertionError(('unexpected common key',keys))
        if self.after_chord:self.after_chord(self,keys)


# The observed two-character CRLF click selection at the last cell sentence is
# collapsed before common navigation, then fully recopied/direction-normalized.
e=Cell('The last sentence in this cell.');original=e.text;reports=[]
driver=k.Driver(e,e.factory,report=lambda phase,**fields:reports.append((phase,fields)))
snapshot=driver.capture(7)
assert snapshot.text==e.body and e.text==original and e.copy_values[1]=='\r\n'
nav=[event for event in e.events if event!=(k.CTRL,ord('C'))]
assert nav[:3]==[(k.LEFT,),(k.CTRL,k.DOWN),(k.CTRL,k.SHIFT,k.UP)]
assert [phase for phase,_ in reports].count('selection_keyboard_fallback')==1
assert 'The last sentence' not in repr(reports)
driver.apply(snapshot,'Translated cell sentence.')
assert e.text==e.prefix+'Translated cell sentence.\r\n' and e.pasted==1

# A missing or empty click copy proves no selection. Do not send Left from a
# paragraph-start caret, which could otherwise move into the previous paragraph.
for copied in ('none','empty'):
    e=Cell('Current paragraph.',click=copied,caret='start');original=e.text
    driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
    assert snapshot.text==e.body and e.text==original
    nav=[event for event in e.events if event!=(k.CTRL,ord('C'))]
    assert nav[:2]==[(k.CTRL,k.DOWN),(k.CTRL,k.SHIFT,k.UP)]
    assert e.selected==1 and e.events.count((k.CTRL,k.DOWN))==1
    assert e.clock<.6
    driver.apply(snapshot,'Translated current paragraph.')
    assert e.text==e.prefix+'Translated current paragraph.\r\n' and e.pasted==1

# Failure of that one common navigation attempt is bounded; it does not retry
# arbitrary directions, insert whitespace, cut text, or paste a stale payload.
class Unsupported(Cell):
    def chord(self,*keys):
        if keys in ((k.CTRL,k.DOWN),(k.CTRL,k.SHIFT,k.UP)):
            self.events.append(keys);return
        super().chord(*keys)
e=Unsupported('Still unchanged.',click='none',caret='start');original=e.text
try:k.Driver(e,e.factory).capture(7)
except k.KeyboardError:pass
else:raise AssertionError('Unsupported paragraph navigation was accepted')
assert e.text==original and not e.pasted and e.events.count((k.CTRL,k.DOWN))==1
assert (k.LEFT,) not in e.events and (0x20,) not in e.events and (k.CTRL,ord('X')) not in e.events

# A whitespace-only result from the common no-caret strategy is not eligible
# for another fallback. This is not a general retry/previous-paragraph search.
class NoCaret(Cell):
    def select(self,guard,pause):
        self.selected+=1;return k.select_paragraph(self,guard,pause)
e=NoCaret('',caret='start');original=e.text
try:k.Driver(e,e.factory).capture(7)
except k.KeyboardError:pass
else:raise AssertionError('Empty paragraph was accepted as text')
assert e.text==original and not e.pasted and e.events.count((k.CTRL,k.DOWN))==1
assert (k.LEFT,) not in e.events

# Brackets never filter out a real nonempty heading or cause another selection.
for heading in ('[실적]','[향후]','[서비스러닝]','[ 향후 계획 ]','[]'):
    e=Cell(heading,click='body');driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
    assert snapshot.text==heading and e.selected==1
    assert (k.CTRL,k.DOWN) not in e.events and (k.LEFT,) not in e.events
    driver.apply(snapshot,'Translated heading')
    assert e.text==e.prefix+'Translated heading\r\n' and e.pasted==1

# Existing user selections are not reselected, even when they contain only a
# paragraph delimiter. Genuine input during fallback still cancels before paste.
e=Cell('Manual body.',manual=lambda cell:(cell.start,cell.end))
snapshot=k.Driver(e,e.factory).capture(7)
assert snapshot.text=='Manual body.' and not snapshot.selected_automatically and not e.selected
e=Cell('Unchanged body.',manual=lambda cell:(cell.end,cell.end+2));original=e.text
try:k.Driver(e,e.factory).capture(7)
except k.KeyboardError:pass
else:raise AssertionError('Whitespace manual selection was silently expanded')
assert not e.selected and (k.CTRL,k.DOWN) not in e.events and e.text==original
for action in ('typing','click'):
    e=Cell('Do not change this.');original=e.text
    e.activity_cause=lambda:action
    e.after_chord=lambda cell,keys:setattr(cell,'revision',8) if keys==(k.LEFT,) else None
    try:k.Driver(e,e.factory).capture(7)
    except k.Cancelled:pass
    else:raise AssertionError('Real interaction did not cancel fallback')
    assert e.text==original and not e.pasted and (k.CTRL,k.DOWN) not in e.events

print('Diagnostic click-host fallback: CRLF-only cell end, missing/empty copy, bracket headings, manual selection and real-input cancellation: PASS')
