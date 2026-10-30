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
    def __init__(self,text,caret,selection=None,forward='normal',automatic_forward=False):
        self.text=text;self.anchor_pos=caret;self.active=caret
        if selection is not None:self.anchor_pos,self.active=selection
        self.revision=7;self.focus=object();self.owner_pids=(123,)
        self.focused=True;self.clock=0.;self.events=[];self.pasted=0;self.selected=0
        self.forward=forward;self.after_chord=None;self.copy_values=[]
        self.automatic_forward=automatic_forward
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
        strategy=k.Windows.select(self,guard,pause)
        if self.automatic_forward:self.anchor_pos,self.active=self.active,self.anchor_pos
        return strategy
    def previous(self,position):
        step=2 if self.text[max(0,position-2):position]=='\r\n' else 1
        return max(0,position-step)
    def following(self,position):
        step=2 if self.text[position:position+2]=='\r\n' else 1
        return min(len(self.text),position+step)
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
            self.active=start if start!=end else self.previous(self.active)
            self.anchor_pos=self.active
        elif keys==(k.RIGHT,):
            start,end=self.bounds()
            self.active=end if start!=end else self.following(self.active)
            self.anchor_pos=self.active
        elif keys==(k.CTRL,k.SHIFT,k.DOWN):
            if self.forward=='normal':self.active=self.down(self.active)
            elif self.forward=='too_far':self.active=self.down(self.down(self.active))
            elif self.forward!='unsupported':raise AssertionError(self.forward)
        elif keys==(k.SHIFT,k.LEFT):
            # Hosts commonly expose CRLF as two copied characters but one
            # paragraph-boundary caret position. The recopy still proves it.
            self.active=self.previous(self.active)
        elif keys==(k.SHIFT,k.RIGHT):self.active=self.following(self.active)
        elif keys==(k.CTRL,ord('V')):
            start,end=self.bounds();replacement=self.lease.text
            self.text=self.text[:start]+replacement+self.text[end:]
            self.active=start+len(replacement);self.anchor_pos=self.active;self.pasted+=1
        else:raise AssertionError(('unexpected common key',keys))
        if self.after_chord:self.after_chord(self,keys)


class AdvancingRight(Editor):
    """Observed HWP-like endpoint behavior, without native editor calls.

    Right on a nonempty selection collapses to the end and advances one caret
    position. The diagnostic's subsequent Shift+Left therefore copies a real
    character rather than the selected paragraph delimiter.
    """
    def chord(self,*keys):
        start,end=self.bounds()
        super().chord(*keys)
        if keys==(k.RIGHT,) and start!=end:
            self.active=self.anchor_pos=self.following(end)


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
    assert e.text==original and e.anchor_pos>e.active
    assert e.events.count((k.RIGHT,))==1 and (k.CTRL,k.SHIFT,k.DOWN) not in e.events
    # The failed endpoint probe extends backward; restore its exact source
    # before collapsing to the end and selecting without the paragraph mark.
    assert e.copy_values==[None,paragraph+'\n','\n'+paragraph+'\n',paragraph+'\n',paragraph,paragraph]
    assert e.clock<.5
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
    assert e.copy_values==[None,paragraph+'\r\n','\r\n'+paragraph+'\r\n',paragraph+'\r\n',paragraph,paragraph]
    driver.apply(snapshot,'CRLF translation.')
    assert e.text==crlf_prefix+'CRLF translation.'+crlf_suffix

# Reproduce the 2026-10-30 user diagnostic, including the CRLF counts. The
# first reselection returns exactly the old block; the bounded second candidate
# must exclude its delimiter while preserving both adjacent paragraphs.
probe_text='문단 선택을 시험합니다.'
probe_prefix='앞 문단입니다.\r\n';probe_suffix='\r\n뒤 문단입니다.'
e=AdvancingRight(probe_prefix+probe_text+probe_suffix,len(probe_prefix)+4)
driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
assert snapshot.text==probe_text and snapshot.selected_automatically
baseline=probe_text+'\r\n'
assert e.copy_values==[None,baseline,'\r\n'+baseline,baseline,baseline,probe_text,probe_text]
assert [len(value) if value is not None else None for value in e.copy_values]==[None,15,17,15,15,13,13]
assert e.events.count((k.RIGHT,))==2
assert e.events.count((k.CTRL,k.SHIFT,k.UP))==3
assert e.clock<.6
driver.apply(snapshot,'Paragraph selection test.')
assert e.text==probe_prefix+'Paragraph selection test.'+probe_suffix and e.pasted==1

# Short headings, bracketed text and terminal paragraphs exercise the same
# content checks. These are simulated text blocks, not a claim of native HWP
# table-cell validation. Surrounding cell-like labels must remain unchanged.
for delimiter in ('\n','\r\n'):
    contexts=(('',delimiter+'뒤 문단'),
              ('앞 문단'+delimiter,delimiter+'뒤 문단'),
              ('[앞 셀]'+delimiter,delimiter+'[다음 셀]'),
              ('앞 문단'+delimiter,''),
              ('앞 문단'+delimiter,delimiter))
    for before,after in contexts:
        for text in ('가','[향후]','(추천사유)','표의 마지막 문장입니다.'):
            for offset in (0,len(text)//2,len(text)):
                original_block=before+text+after
                e=AdvancingRight(original_block,len(before)+offset)
                driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
                assert snapshot.text==text and e.text==original_block
                expected_retries=2 if after and len(after)>len(delimiter) else (1 if after else 0)
                assert e.events.count((k.RIGHT,))==expected_retries
                assert e.events.count((k.CTRL,k.SHIFT,k.UP))<=3
                assert (k.CTRL,k.SHIFT,k.DOWN) not in e.events
                driver.apply(snapshot,'Replacement')
                assert e.text==before+'Replacement'+after and e.pasted==1

# An unrelated result must not trigger the second candidate. Only an exact
# baseline copy demonstrates the observed unchanged-boundary condition.
e=AdvancingRight(probe_prefix+probe_text+probe_suffix,len(probe_prefix)+4)
def unrelated_first_reselect(editor,keys):
    if keys==(k.CTRL,k.SHIFT,k.UP) and editor.events.count(keys)==2:
        editor.active=editor.following(editor.active)
e.after_chord=unrelated_first_reselect;refused(e)
assert e.events.count((k.RIGHT,))==1

# The additional candidate is bounded and must itself match the exact source
# without one delimiter. A second bad range cannot be accepted or retried.
e=AdvancingRight(probe_prefix+probe_text+probe_suffix,len(probe_prefix)+4)
def wrong_second_reselect(editor,keys):
    if keys==(k.CTRL,k.SHIFT,k.UP) and editor.events.count(keys)==3:
        editor.active=editor.following(editor.active)
e.after_chord=wrong_second_reselect;refused(e)
assert e.events.count((k.RIGHT,))==2
assert e.events.count((k.CTRL,k.SHIFT,k.UP))==3

# Actual user input during the extra candidate stops before the next key. No
# document mutation or paste is issued after the changed activity revision.
e=AdvancingRight(probe_prefix+probe_text+probe_suffix,len(probe_prefix)+4)
def cancel_retry(editor,keys):
    if keys==(k.RIGHT,) and editor.events.count(keys)==2:
        editor.revision+=1
e.after_chord=cancel_retry;refused(e)
assert e.events[-1]==(k.RIGHT,)
assert e.events.count((k.CTRL,k.SHIFT,k.UP))==2

# Forward selection is not the inverse of backward selection in every host.
# Neither missing nor broader Ctrl+Shift+Down affects the new end-based route.
for behavior in ('unsupported','too_far'):
    e=Editor(original,len(prefix)+5,forward=behavior)
    driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
    assert snapshot.text==paragraph and (k.CTRL,k.SHIFT,k.DOWN) not in e.events
    driver.apply(snapshot,'Asymmetric navigation.')
    assert e.text==prefix+'Asymmetric navigation.'+suffix and e.pasted==1

# Some hosts leave the active endpoint at the end even for a keyboard Up
# selection. Probe the real endpoint instead of trusting the strategy label.
for delimiter in ('\n','\r\n'):
    before='Previous paragraph.'+delimiter;after=delimiter+'Next paragraph.'+delimiter
    for offset in (0,5,len(paragraph)):
        e=Editor(before+paragraph+after,len(before)+offset,forward='unsupported',automatic_forward=True)
        driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
        assert snapshot.text==paragraph and snapshot.selected_automatically
        assert e.copy_values==[None,paragraph+delimiter,paragraph,paragraph]
        assert (k.RIGHT,) not in e.events and (k.SHIFT,k.RIGHT) not in e.events
        assert (k.CTRL,k.SHIFT,k.DOWN) not in e.events
        driver.apply(snapshot,'Forward endpoint.')
        assert e.text==before+'Forward endpoint.'+after and e.pasted==1

# Shift+Left cannot extend before the document start. A no-op probe must not
# be "restored" with Shift+Right, which would drop the first source character.
e=Editor(paragraph+suffix,5);driver=k.Driver(e,e.factory)
snapshot=driver.capture(7)
assert snapshot.text==paragraph and (k.SHIFT,k.RIGHT) not in e.events
driver.apply(snapshot,'First paragraph.')
assert e.text=='First paragraph.'+suffix

# A restoration key whose host behavior differs must never be followed by
# navigation/paste based on a guessed range.
e=Editor(original,len(prefix)+5)
def damage_restore(editor,keys):
    if keys==(k.SHIFT,k.RIGHT):editor.active=editor.following(editor.active)
e.after_chord=damage_restore;refused(e)
assert (k.RIGHT,) not in e.events

# A host that collapses Right to the wrong endpoint cannot lose source text.
e=Editor(original,len(prefix)+5)
def wrong_collapse(editor,keys):
    if keys==(k.RIGHT,):editor.active=len(prefix);editor.anchor_pos=editor.active
e.after_chord=wrong_collapse;refused(e)

# Copy-only trailing line breaks are not proof of a selected paragraph mark:
# shrinking such a range must fail rather than silently drop its final letter.
class SyntheticBreak(Editor):
    def chord(self,*keys):
        super().chord(*keys)
        if keys==(k.CTRL,ord('C')) and self.lease.text is not None:
            self.lease.text+='\n';self.copy_values[-1]=self.lease.text
e=SyntheticBreak(prefix+paragraph,len(prefix)+5);refused(e)

# Remove exactly one selected delimiter, not every trailing blank paragraph.
e=Editor('PRE\nONE\n\nPOST',4,selection=(4,9))
snapshot=k.Driver(e,e.factory).capture(7)
assert snapshot.text=='ONE\n' and e.text=='PRE\nONE\n\nPOST'

# A real interaction between collapse and backward selection cancels before the
# next navigation key. Source/focus/revision protections remain in force.
e=Editor(original,len(prefix)+5)
e.after_chord=lambda editor,keys:setattr(editor,'revision',8) if keys==(k.LEFT,) else None
refused(e)
assert e.events.count((k.CTRL,k.SHIFT,k.UP))==1

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

print('Paragraph direction: endpoint probe, observed HWP advancing-Right regression, bounded exact-source retry, asymmetric navigation, restoration, start/end/CRLF boundaries, synthetic copy breaks, user selections and no mouse input: PASS')
