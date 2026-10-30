"""App routing contract: native TSF must never become a duplicate paste."""
import os,pathlib,sys,tempfile,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as root:
    original=os.environ.get('LOCALAPPDATA');os.environ['LOCALAPPDATA']=root
    import main
    if original is None:os.environ.pop('LOCALAPPDATA',None)
    else:os.environ['LOCALAPPDATA']=original

class Signal:
    def __init__(self):self.values=[]
    def emit(self,value):self.values.append(value)
class Label:
    def __init__(self):self.values=[]
    def setText(self,value):self.values.append(value)
class Box:
    def currentText(self):return '영어'
class App:
    run_translation=main.App.run_translation
    begin_tsf_capture=main.App.begin_tsf_capture
    tsf_captured=main.App.tsf_captured
    tsf_applied=main.App.tsf_applied
    apply_result=main.App.apply_result
    def __init__(self):
        self._quitting=False;self.busy=False;self._tsf_request=None;self._pending_input=None
        self.engine_initializing=False;self.target={'shift':Box()}
        self.tap=types.SimpleNamespace(activity_snapshot=lambda:(4,0.0))
        self.input_readiness=Label();self.bridge=types.SimpleNamespace(tsf_captured=Signal(),tsf_applied=Signal())
        self.tsf=types.SimpleNamespace(locate=lambda focus:123,capture=lambda server,focus:snapshot,apply=lambda *a:0)
        self.errors=[];self.starts=[];self.pastes=[]
        self.keyboard_requests=[]
    def begin_keyboard_capture(self,*args):self.keyboard_requests.append(args)
    def isActiveWindow(self):return False
    def engine_configuration(self):return ('unchanged',)
    def error(self,message):self.errors.append(message);self.busy=False
    def start_translation(self,*args):self.starts.append(args)
    def poll_input(self,request):raise AssertionError('UIA called during TSF path')
    def paste_range(self,*a):self.pastes.append(a)

focus=types.SimpleNamespace(foreground=5,keyboard_window=6,thread_id=7)
snapshot=main.tsf_bridge.Snapshot(123,b'A'*16,'안녕하세요')
main.focus_guard.capture=lambda:focus
main.focus_guard.unchanged=lambda f:f is focus
main.focus_guard.same_foreground=lambda f:f is focus
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(GetForegroundWindow=lambda:5)))
main.capture_input=lambda:(_ for _ in ()).throw(AssertionError('UIA read during TSF route'))
main.focused=lambda:(_ for _ in ()).throw(AssertionError('ValuePattern read during TSF route'))
class Thread:
    def __init__(self,target,**kwargs):self.target=target
    def start(self):self.target()
main.threading=types.SimpleNamespace(Thread=Thread)
scheduled=[];main.QTimer=types.SimpleNamespace(singleShot=lambda ms,fn:scheduled.append(fn))

a=App();a.begin_tsf_capture('shift',4,main.time.monotonic(),focus,123)
assert len(a.bridge.tsf_captured.values)==1 and not a.errors
a.tsf_captured(a.bridge.tsf_captured.values[-1])
assert len(a.starts)==1 and a.starts[0][4]==('tsf',snapshot) and not scheduled
a.apply_result((5,(),snapshot.text,'Hello',('tsf',snapshot),focus))
assert a.bridge.tsf_applied.values==[(True,'TSF 교체 완료')] and not a.pastes
a.tsf_applied(a.bridge.tsf_applied.values[-1]);assert not a.busy

# Unknown commit outcome is an error, never fallback/retranslation/paste.
a.tsf.apply=lambda *x:(_ for _ in ()).throw(main.tsf_bridge.TsfError('timeout'))
a.apply_result((5,(),snapshot.text,'Hello',('tsf',snapshot),focus))
assert a.bridge.tsf_applied.values[-1]==(False,'timeout') and not a.pastes

# Read-only failure cannot be retried through less restrictive UIA.
a=App();a.tsf.capture=lambda *x:(_ for _ in ()).throw(main.tsf_bridge.TsfError('secure'))
a.begin_tsf_capture('shift',4,main.time.monotonic(),focus,123);a.tsf_captured(a.bridge.tsf_captured.values[-1])
assert a.errors==['secure'] and not a.starts and not scheduled

# Only a missing native document context is eligible for the old reader.
a=App();a.tsf.capture=lambda *x:(_ for _ in ()).throw(main.tsf_bridge.Unavailable())
a.begin_tsf_capture('shift',4,main.time.monotonic(),focus,123);a.tsf_captured(a.bridge.tsf_captured.values[-1])
assert a.keyboard_requests and not scheduled and not a.errors and not a.starts
scheduled.clear()

# Text typed after the gesture makes the completed capture stale.
a=App();a.begin_tsf_capture('shift',4,main.time.monotonic(),focus,123);a.tap.activity_snapshot=lambda:(5,0.0)
a.tsf_captured(a.bridge.tsf_captured.values[-1]);assert not a.starts and not a.busy
print('TSF routing: direct native path, no duplicate paste, secure refusal, unavailable-only fallback and stale capture: PASS')
