"""Default gestures must not require a TSF/UIA text provider."""
import os,pathlib,sys,tempfile,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as directory:
    old=os.environ.get('LOCALAPPDATA');os.environ['LOCALAPPDATA']=directory
    import main
    if old is None:os.environ.pop('LOCALAPPDATA',None)
    else:os.environ['LOCALAPPDATA']=old

class Signal:
    def __init__(self):self.values=[]
    def emit(self,payload):self.values.append(payload)
class App:
    run_translation=main.App.run_translation
    begin_keyboard_capture=main.App.begin_keyboard_capture
    keyboard_captured=main.App.keyboard_captured
    keyboard_capture_timeout=main.App.keyboard_capture_timeout
    cancel_pending_input=main.App.cancel_pending_input
    apply_result=main.App.apply_result
    keyboard_applied=main.App.keyboard_applied
    def __init__(self):
        self._quitting=False;self.busy=False;self.engine_initializing=False
        self._keyboard_request=None;self._pending_input=None
        self.target={'shift':types.SimpleNamespace(currentText=lambda:'영어')}
        self.selection_mode=types.SimpleNamespace(currentData=lambda:'triple_click')
        self.tap=types.SimpleNamespace(activity_snapshot=lambda:(7,0.0))
        self.bridge=types.SimpleNamespace(keyboard_captured=Signal(),keyboard_applied=Signal())
        self.input_readiness=types.SimpleNamespace(setText=lambda text:None)
        self.errors=[];self.starts=[]
    def isActiveWindow(self):return False
    def engine_configuration(self):return ('same',)
    def error(self,error):self.errors.append(error);self.cancel_pending_input();self.busy=False
    def start_translation(self,*args):self.starts.append(args)

focus=types.SimpleNamespace(foreground=8)
main.focus_guard.capture=lambda:focus
main.focus_guard.unchanged=lambda f:f is focus
main.focus_guard.same_foreground=lambda f:f is focus
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(GetForegroundWindow=lambda:8)))
def forbidden(*args):raise AssertionError('default route asked for a provider text range')
main.capture_input=forbidden;main.focused=forbidden
scheduled=[];main.QTimer=types.SimpleNamespace(singleShot=lambda ms,fn:scheduled.append(fn))
class Thread:
    def __init__(self,target,**kwargs):self.target=target
    def start(self):self.target()
main.threading=types.SimpleNamespace(Thread=Thread)
snapshot=main.keyboard_access.Snapshot('안녕하세요',focus,7,None,False)
class Driver:
    def __init__(self,env,report=None):pass
    def capture(self,revision,commit_space):assert revision==7 and not commit_space;return snapshot
    def apply(self,snap,text):assert snap is snapshot and text=='Hello';return 'delivered once'
main.keyboard_access.Windows=lambda *args:None
main.keyboard_access.Driver=Driver
a=App();a.tsf=types.SimpleNamespace(locate=forbidden)
a.run_translation(('shift',7,main.time.monotonic()))
assert not a.errors and len(a.bridge.keyboard_captured.values)==1
request=a._keyboard_request
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
assert len(a.starts)==1 and a.starts[0][4]==('keyboard',snapshot)
a.apply_result((8,(),snapshot.text,'Hello',('keyboard',snapshot),focus))
assert a.bridge.keyboard_applied.values==[(True,'delivered once')]
a.keyboard_applied(a.bridge.keyboard_applied.values[-1]);assert not a.busy

# A stale queued result cannot translate a later selection or revive a job.
a=App();a.run_translation(('shift',7,main.time.monotonic()))
request=a._keyboard_request
a.keyboard_capture_timeout(request)
assert not a.busy and a._keyboard_request is None and a.errors
a.keyboard_captured(a.bridge.keyboard_captured.values[-1]);assert not a.starts
a.run_translation(('shift',7,main.time.monotonic()));assert a._keyboard_request is not None

print('Default keyboard routing: no TSF/UIA range dependency, one apply, bounded capture, stale result rejection and recovery: PASS')
