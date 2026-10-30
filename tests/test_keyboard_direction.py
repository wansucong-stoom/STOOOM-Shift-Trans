"""Common paragraph keys with real anchor/active selection endpoints.

No native input, document or clipboard APIs are called. Unlike an ordered
selection tuple, this model distinguishes Shift+Left extending backward from
Shift+Left trimming a forward selection.
"""
from pathlib import Path
import sys
from types import SimpleNamespace as NS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import keyboard_access as k


class Lease:
    def __init__(self,env):self.env=env;self.text=None;self.kept=False
    def arm_copy(self):self.text=None;self.env.lease=self
    def read_copy(self,pids):return self.text
    def replace_owned(self,expected,text):assert self.text==expected;self.text=text
    def keep_translation(self):self.kept=True;return 1
    def restore(self):return not self.kept


class Editor:
    def __init__(self,text,caret,selection=None,forward='normal'):
        self.text=text;self.anchor_pos=caret;self.active=caret
        if selection is not None:self.anchor_pos,self.active=selection
        self.revision=7;self.focus=object();self.owner_pids=(123,)
        self.focused=True;self.clock=0.;self.events=[];self.pasted=0;self.selected=0
        self.forward=forward;self.after_chord=None;self.copy_values=[]
    def activity(self):return self.revision,self.clock
    def current(self):return self.focused
    def modifiers(self):return False
    def now(self):return self.clock
    def sleep(self,seconds):self.clock+=seconds
    def safe(self):pass
    def anchor(self):return self.anchor_pos,self.active
    def caret_point(self):return None
    def factory(self):return Lease(self)
    def bounds(self):return min(self.anchor_pos,self.active),max(self.anchor_pos,self.active)
    def down(self,position):
        edge=self.text.find('\n',position)
        return len(self.text) if edge<0 else edge+1
    def up(self,position):return self.text.rfind('\n',0,max(0,position-1))+1
    def select(self,guard,pause):
        self.selected+=1
        return k.Windows.select(self,guard,pause)
    def chord(self,*keys):
        self.events.append(keys)
        if keys==(k.CTRL,ord('C')):
            start,end=self.bounds()
            self.lease.text=self.text[start:end] if end>start else None
            self.copy_values.append(self.lease.text)
        elif keys==(k.CTRL,k.DOWN):
            self.active=self.down(self.active);self.anchor_pos=self.active
        elif keys==(k.CTRL,k.SHIFT,k.UP):self.active=self.up(self.active)
        elif keys==(k.LEFT,):
            start,end=self.bounds()
            self.active=start if start!=end else max(0,self.active-1)
            self.anchor_pos=self.active
        elif keys==(k.CTRL,k.SHIFT,k.DOWN):
            if self.forward=='normal':self.active=self.down(self.active)
            elif self.forward=='too_far':self.active=self.down(self.down(self.active))
            elif self.forward!='unsupported':raise AssertionError(self.forward)
        elif keys==(k.SHIFT,k.LEFT):
            # Hosts commonly expose CRLF as two copied characters but one
            # paragraph-boundary caret position. The recopy still proves it.
            step=2 if self.text[max(0,self.active-2):self.active]=='\r\n' else 1
            self.active=max(0,self.active-step)
        elif keys==(k.CTRL,ord('V')):
            start,end=self.bounds();replacement=self.lease.text
            self.text=self.text[:start]+replacement+self.text[end:]
            self.active=start+len(replacement);self.anchor_pos=self.active;self.pasted+=1
        else:raise AssertionError(('unexpected common key',keys))
        if self.after_chord:self.after_chord(self,keys)


def refused(editor):
    original=editor.text
    try:k.Driver(editor,editor.factory).capture(7)
    except (k.KeyboardError,k.Cancelled):pass
    else:raise AssertionError('Unconfirmed selection was accepted')
    assert editor.text==original and editor.pasted==0


paragraph='A long paragraph whose display can wrap without another paragraph break.'
prefix='Previous paragraph.\n';suffix='\nNext paragraph.\n'
original=prefix+paragraph+suffix
for offset in (0,len(paragraph)//2,len(paragraph)):
    e=Editor(original,len(prefix)+offset);driver=k.Driver(e,e.factory)
    snapshot=driver.capture(7)
    assert snapshot.text==paragraph and snapshot.selected_automatically
    assert e.text==original and e.anchor_pos<e.active
    assert (k.LEFT,) in e.events and (k.CTRL,k.SHIFT,k.DOWN) in e.events
    # The original range including its delimiter is recopied unchanged before
    # the first ShiftLeft; the final source verification excludes the delimiter.
    assert e.copy_values==[None,paragraph+'\n',paragraph+'\n',paragraph,paragraph]
    assert e.clock<.3
    driver.apply(snapshot,'Translated paragraph.')
    assert e.text==prefix+'Translated paragraph.'+suffix and e.pasted==1

# End-of-document paragraphs without a delimiter need no normalization; the
# backward selection itself is valid and source-checked immediately before paste.
for offset in (0,len(paragraph)//2,len(paragraph)):
    e=Editor(prefix+paragraph,len(prefix)+offset);driver=k.Driver(e,e.factory)
    snapshot=driver.capture(7)
    assert snapshot.text==paragraph and snapshot.anchor[0]>snapshot.anchor[1]
    assert (k.LEFT,) not in e.events and (k.CTRL,k.SHIFT,k.DOWN) not in e.events
    driver.apply(snapshot,'Translated final paragraph.')
    assert e.text==prefix+'Translated final paragraph.'

# A final paragraph followed by the document's last delimiter remains intact.
e=Editor(prefix+paragraph+'\n',len(prefix)+len(paragraph));driver=k.Driver(e,e.factory)
driver.apply(driver.capture(7),'Last paragraph.')
assert e.text==prefix+'Last paragraph.\n'

# CRLF is copied as two code points but crossed as one caret position.
crlf_prefix='Previous paragraph.\r\n';crlf_suffix='\r\nNext paragraph.\r\n'
for offset in (0,len(paragraph)//2,len(paragraph)):
    e=Editor(crlf_prefix+paragraph+crlf_suffix,len(crlf_prefix)+offset)
    driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
    assert snapshot.text==paragraph
    assert e.copy_values==[None,paragraph+'\r\n',paragraph+'\r\n',paragraph,paragraph]
    driver.apply(snapshot,'CRLF translation.')
    assert e.text==crlf_prefix+'CRLF translation.'+crlf_suffix

# Unsupported or broader forward navigation is never accepted as the source.
for behavior in ('unsupported','too_far'):
    e=Editor(original,len(prefix)+5,forward=behavior);refused(e)
    assert (k.CTRL,k.SHIFT,k.DOWN) in e.events and (k.SHIFT,k.LEFT) not in e.events

# A real interaction between collapse and forward selection cancels before the
# next navigation key. Source/focus/revision protections remain in force.
e=Editor(original,len(prefix)+5)
e.after_chord=lambda editor,keys:setattr(editor,'revision',8) if keys==(k.LEFT,) else None
refused(e)
assert (k.CTRL,k.SHIFT,k.DOWN) not in e.events

# User selections, including multiple paragraphs, are never blindly replaced
# with a new paragraph selection. Forward selection preserves prior behavior;
# a backward selection with a delimiter is refused rather than guessed.
multi='PRE\nONE\nTWO\nPOST\n';start=4;end=12
e=Editor(multi,start,selection=(start,end));snapshot=k.Driver(e,e.factory).capture(7)
assert snapshot.text=='ONE\nTWO' and not snapshot.selected_automatically
assert not e.selected and (k.CTRL,k.SHIFT,k.DOWN) not in e.events
e=Editor(multi,start,selection=(end,start));refused(e)
assert not e.selected and (k.LEFT,) not in e.events and (k.CTRL,k.SHIFT,k.DOWN) not in e.events

# A triple click supplies no known orientation. If the host returns a backward
# range, the automatic route does not pretend that it was the keyboard fallback.
class UnknownClick(Editor):
    def select(self,guard,pause):
        self.selected+=1;guard();self.anchor_pos=len(prefix)+len(paragraph)+1;self.active=len(prefix)
        return 'unknown'
e=UnknownClick(original,len(prefix)+5);refused(e)
assert e.selected==1 and (k.LEFT,) not in e.events and (k.CTRL,k.SHIFT,k.DOWN) not in e.events

# Exercise only the explicit diagnostic click helper with a simulated cursor.
# Default Windows.select is keyboard-only, regardless of a valid caret point.
class Cursor:
    def __init__(self):self.position=(2,3)
    def GetCursorPos(self,pointer):
        pointer._obj.x,pointer._obj.y=self.position;return True
cursor=Cursor();clicks=[]
mouse=NS(caret_point=lambda:(10,20),u=cursor,current=lambda:True,
         _move=lambda point:setattr(cursor,'position',point),click=lambda:clicks.append(1))
assert k.Windows.select_by_click(mouse,lambda:None,lambda seconds:None)=='unknown'
assert len(clicks)==3 and cursor.position==(2,3)

# A valid Windows caret may overlap a table/object property handle. The default
# full capture-and-paste path must never query a mouse position/object target,
# move the pointer or click there, even though the caret coordinate is available.
def forbidden_mouse(*args,**kwargs):raise AssertionError('Default route used mouse selection')
e=Editor(original,len(prefix)+len(paragraph));caret_queries=[]
e.caret_point=lambda:caret_queries.append(1) or (400,300)
e.u=NS(GetCursorPos=forbidden_mouse,WindowFromPoint=forbidden_mouse)
e._move=forbidden_mouse;e.click=forbidden_mouse
driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
assert snapshot.text==paragraph and not caret_queries
assert (k.CTRL,k.DOWN) in e.events and (k.CTRL,k.SHIFT,k.UP) in e.events
driver.apply(snapshot,'Keyboard-only translation.')
assert e.text==prefix+'Keyboard-only translation.'+suffix and e.pasted==1

print('Paragraph direction: keyboard-only default with valid table-object caret, backward/forward recopy, boundaries/refusal, user selections and diagnostic click orientation: PASS')
