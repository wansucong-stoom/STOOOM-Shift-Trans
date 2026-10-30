"""Selection/copy/paste contract without any application-specific bindings."""
import ctypes
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import keyboard_access as k


class Lease:
    def __init__(self,env):self.env=env;self.text=None;self.armed=False;self.restored=False;self.kept=False
    def arm_copy(self):self.text=None;self.armed=True;self.env.current_lease=self
    def read_copy(self,pids):return self.text
    def replace_owned(self,expected,text):
        assert self.text==expected
        self.text=text
    def keep_translation(self):self.kept=True
    def restore(self):self.restored=not self.kept


class Env:
    def __init__(self,text,selection=None):
        self.text=text;self.selection=selection;self.caret=len(text);self.revision=7
        self.focus=object();self.owner_pids=(12,);self.clock=0.;self.focused=True
        self.events=[];self.leases=[];self.current_lease=None;self.security=True
        self.after_copy=None;self.fail_space=False;self.pasted=0;self.selected=0;self.include_marker=False
    def activity(self):return self.revision,self.clock
    def current(self):return self.focused
    def modifiers(self):return False
    def now(self):return self.clock
    def sleep(self,seconds):self.clock+=seconds
    def safe(self):
        if not self.security:raise k.KeyboardError('secure')
    def anchor(self):return self.selection,self.caret
    def factory(self):
        lease=Lease(self);self.leases.append(lease);return lease
    def chord(self,*keys):
        self.events.append(keys)
        if keys==(k.CTRL,ord('C')):
            if self.selection:
                self.current_lease.text=self.text[slice(*self.selection)]
            if self.after_copy:self.after_copy(self)
        elif keys==(0x20,):
            assert not self.selection
            if not self.fail_space:
                self.text=self.text[:self.caret]+' '+self.text[self.caret:];self.caret+=1
        elif keys==(k.SHIFT,k.LEFT):
            if self.selection:
                start,end=self.selection;self.selection=(start,max(start,end-1));self.caret=end-1
            else:self.selection=(max(0,self.caret-1),self.caret)
        elif keys==(0x08,):
            assert self.selection
            start,end=self.selection;assert self.text[start:end]==' '
            self.text=self.text[:start]+self.text[end:];self.caret=start;self.selection=None
        elif keys==(k.CTRL,ord('V')):
            start,end=self.selection
            replacement=self.current_lease.text
            self.text=self.text[:start]+replacement+self.text[end:]
            self.caret=start+len(replacement);self.selection=None;self.pasted+=1
        else:raise AssertionError(('unexpected shortcut',keys))
    def select(self,guard,pause):
        guard();self.selected+=1
        start=self.text.rfind('\n',0,self.caret)+1
        end=self.text.find('\n',self.caret)
        if end<0:end=len(self.text)
        elif self.include_marker:end+=1
        self.selection=(start,end);self.caret=end;pause(.075)


def raises(kind,call):
    try:call()
    except kind:return
    raise AssertionError('expected '+kind.__name__)


# The selected text stays in place while the engine computes its translation.
e=Env('앞 안녕하세요 뒤',(2,7));d=k.Driver(e,e.factory)
s=d.capture(7)
assert s.text=='안녕하세요' and e.text=='앞 안녕하세요 뒤'
assert not e.selected and (0x20,) not in e.events
assert e.leases[-1].restored
d.apply(s,'Hello 😀')
assert e.text=='앞 Hello 😀 뒤' and e.caret==len('앞 Hello 😀') and e.pasted==1
assert e.leases[0].restored and e.leases[-1].kept and not e.leases[-1].restored

# A collapsed caret selects its paragraph without changing source text.
# No temporary whitespace, Backspace, cut or full-document select is sent.
e=Env('보존할 첫 문단\n저는 누구일까요?');d=k.Driver(e,e.factory)
s=d.capture(7)
assert s.text=='저는 누구일까요?' and s.selected_automatically
assert e.text=='보존할 첫 문단\n저는 누구일까요?' and e.selected==1
assert (0x20,) not in e.events and (0x08,) not in e.events
d.apply(s,'Who am I?')
assert e.text=='보존할 첫 문단\nWho am I?' and e.pasted==1
assert (k.CTRL,ord('X')) not in e.events and (k.CTRL,ord('A')) not in e.events

# A paragraph mark selected by a triple click must remain in the original
# document so its paragraph-level formatting is not replaced by paste.
e=Env('앞 문단\n번역 문단\n뒤 문단');e.caret=len('앞 문단\n번역 문단');e.include_marker=True
d=k.Driver(e,e.factory);s=d.capture(7)
assert s.text=='번역 문단' and e.text=='앞 문단\n번역 문단\n뒤 문단'
d.apply(s,'Translated paragraph')
assert e.text=='앞 문단\nTranslated paragraph\n뒤 문단' and e.pasted==1

for change in ('focus','typing','position','source'):
    e=Env('original',(0,8));d=k.Driver(e,e.factory);s=d.capture(7)
    if change=='focus':e.focused=False
    elif change=='typing':e.revision+=1
    elif change=='position':e.caret=2
    else:e.text='modified'
    raises(k.Cancelled,lambda:d.apply(s,'new'))
    assert e.pasted==0 and all(x.restored for x in e.leases)

# If the space cannot be proved, Backspace is never sent to the source.
e=Env('원문');e.fail_space=True;d=k.Driver(e,e.factory)
raises(k.KeyboardError,lambda:d.capture(7,commit_space=True))
assert e.text=='원문' and (0x08,) not in e.events and all(x.restored for x in e.leases)

# An already present trailing space is not proof that our Space was inserted.
e=Env('원문 ');e.fail_space=True;d=k.Driver(e,e.factory)
raises(k.KeyboardError,lambda:d.capture(7,commit_space=True))
assert e.text=='원문 ' and (0x08,) not in e.events

# Rich editors may not publish whitespace-only selections to the clipboard.
# That host limitation must not prevent the default paragraph path.
class WhitespaceHost(Env):
    def chord(self,*keys):
        super().chord(*keys)
        if keys==(k.CTRL,ord('C')) and self.current_lease.text is not None and not self.current_lease.text.strip():
            self.current_lease.text=None
e=WhitespaceHost('앞 문단\n번역하는법');d=k.Driver(e,e.factory)
s=d.capture(7)
assert s.text=='번역하는법' and e.text=='앞 문단\n번역하는법'
assert (0x20,) not in e.events and (0x08,) not in e.events
d.apply(s,'How to translate')
assert e.text=='앞 문단\nHow to translate' and e.pasted==1

# A provider without a Windows caret cannot prove the temporary insertion;
# use selection/navigation directly instead of guessing what to erase.
e=Env('원문');e.anchor=lambda:None;d=k.Driver(e,e.factory)
assert d.capture(7).text=='원문' and (0x20,) not in e.events

# User input arriving during copy invalidates the operation before any paste.
e=Env('원문',(0,2));e.after_copy=lambda env:setattr(env,'revision',8)
raises(k.Cancelled,lambda:k.Driver(e,e.factory).capture(7));assert e.pasted==0

e=Env('secret',(0,6));e.security=False
raises(k.KeyboardError,lambda:k.Driver(e,e.factory).capture(7))
assert not e.events and not e.leases

for text in (' ', 'x'*8001, 'a\0b', 'a\ufffcb'):
    e=Env(text,(0,len(text)));d=k.Driver(e,e.factory)
    raises(k.KeyboardError,lambda:d.capture(7));assert not e.pasted

assert ctypes.sizeof(k.INPUT)==(40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)
sent=[]
native=type('Native',(),{'_send':lambda self,events:sent.extend(events)})()
k.Windows.chord(native,k.CTRL,ord('V'))
assert [(e.key.vk,e.key.flags) for e in sent]==[(k.CTRL,0),(ord('V'),0),(ord('V'),2),(k.CTRL,2)]
assert all(e.kind==1 and e.key.extra==k.INPUT_TAG for e in sent)
sent.clear();k.Windows.chord(native,k.SHIFT,k.LEFT)
assert sent[1].key.flags==1 and sent[2].key.flags==3

# Stage reports distinguish an actual paste command from a capture-only run,
# while keeping source/output contents out of the diagnostic callback.
reports=[]
e=Env('private source',(0,14))
d=k.Driver(e,e.factory,report=lambda phase,**details:reports.append((phase,details)))
s=d.capture(7);d.apply(s,'private translation')
assert 'source_confirmed' in [phase for phase,_ in reports]
assert [phase for phase,_ in reports].count('paste_sent')==1
assert 'private source' not in repr(reports) and 'private translation' not in repr(reports)
e.revision+=1;e.activity_cause=lambda:'scroll'
raises(k.Cancelled,lambda:d.apply(s,'private translation'))
assert reports[-1][0]=='guard_cancelled' and reports[-1][1]['cause']=='scroll'

# A failed logger cannot interrupt selection or paste.
def broken_report(*args,**details):raise OSError('disk unavailable')
e=Env('원문',(0,2));d=k.Driver(e,e.factory,report=broken_report)
d.apply(d.capture(7),'Translated')
assert e.text=='Translated' and e.pasted==1
print('Common keyboard path: source-preserving paragraph selection, hosts without whitespace-only copy, optional legacy space check, one paste, Unicode and stale-input rejection: PASS')
