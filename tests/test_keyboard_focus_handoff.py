"""Internal focus handoffs are allowed only on the common keyboard route.

All focus, threads, input, engine work and clipboard delivery are simulated.
The worker must continue in the same top-level application across changed child
HWND/thread/caret metadata, while a different foreground still refuses it.
"""
import ast
from pathlib import Path
import time
from types import SimpleNamespace as NS

source=Path(__file__).resolve().parents[1]/'main.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
helpers={'_input_record','_input_error_message','_input_activity_cause','_input_current_focus'}
methods={'run_translation','begin_keyboard_capture','keyboard_captured','start_translation','apply_result'}
nodes=[]
for node in tree.body:
    if isinstance(node,ast.FunctionDef) and node.name in helpers:nodes.append(node)
    elif isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='_INPUT_ERROR_MESSAGES' for target in node.targets):nodes.append(node)
    elif isinstance(node,ast.ClassDef) and node.name=='App':
        nodes.append(ast.ClassDef(name='App',bases=[],keywords=[],decorator_list=[],body=[item for item in node.body if isinstance(item,ast.FunctionDef) and item.name in methods]))


class Signal:
    def __init__(self):self.values=[]
    def emit(self,value):self.values.append(value)
class Thread:
    def __init__(self,target,**kwargs):self.target=target
    def start(self):self.target()


before=NS(foreground=100,keyboard_window=101,thread_id=102,caret=(1,2,3,4))
child_changed=NS(foreground=100,keyboard_window=201,thread_id=202,caret=(9,8,7,6))
child_changed_again=NS(foreground=100,keyboard_window=301,thread_id=302,caret=None)
other_app=NS(foreground=900,keyboard_window=901,thread_id=902,caret=None)
state={'focus':before,'capture_change':None,'revision':7,'configuration':('same',)}
deliveries=[];captures=[];scheduled=[]


def capture_focus():
    value=state['focus']
    if state['capture_change'] is not None:state['focus']=state['capture_change']
    return value


class Driver:
    def __init__(self,env,report):self.env=env
    def capture(self,revision,commit_space):
        captures.append(revision)
        state['focus']=child_changed
        return NS(text='source',revision=revision,focus=before,anchor=(50,60,70,80))
    def apply(self,snapshot,text):
        assert state['focus'].foreground==snapshot.focus.foreground
        deliveries.append(text)
        return 'sent'


ns={'time':time,'Path':Path,'LANGS':{'한국어':'ko','영어':'en'},'keyboard_safety':lambda:True,
    'path_for':lambda src,dst:['ko_en_opus_big'],'translate_route':lambda text,route:'translation',
    'QTimer':NS(singleShot=lambda delay,callback:scheduled.append(callback)),
    'QSystemTrayIcon':NS(MessageIcon=NS(Information=1)),
    'threading':NS(Thread=Thread),'keyboard_access':NS(Windows=lambda *args:NS(),Driver=Driver),
    'focus_guard':NS(capture=capture_focus,
        same_foreground=lambda expected:state['focus'].foreground==expected.foreground,
        unchanged=lambda expected:state['focus']==expected),
    'ctypes':NS(windll=NS(user32=NS(GetForegroundWindow=lambda:state['focus'].foreground)))}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source),'exec'),ns)


def app():
    state.update(focus=before,capture_change=None,revision=7,configuration=('same',))
    deliveries.clear();captures.clear();scheduled.clear()
    a=ns['App']();a._quitting=False;a.busy=False;a.engine_initializing=False
    a._keyboard_request=None;a._pending_input=None;a._input_active_job=None;a.errors=[]
    a.target={'shift':NS(currentText=lambda:'영어')};a.source=NS(currentText=lambda:'한국어')
    a.engine=NS(currentText=lambda:'기본 오프라인 엔진');a.external_path=''
    a.tap=NS(activity_snapshot=lambda:(state['revision'],0.0),activity_cause=lambda:'typing')
    a.engine_configuration=lambda:state['configuration'];a.isActiveWindow=lambda:False
    a.input_readiness=NS(setText=lambda text:None)
    a.bridge=NS(keyboard_captured=Signal(),keyboard_applied=Signal(),done=Signal(),error=Signal())
    a.tray=NS(showMessage=lambda *args:None)
    a.keyboard_capture_timeout=lambda request:None
    def error(message):a.errors.append(message);a.busy=False;a._keyboard_request=None
    a.error=error
    return a


# A child/thread handoff may already happen between capture() and its immediate
# check. It may happen again at GUI handoff and at model/paste completion.
a=app();state['capture_change']=child_changed
a.run_translation(('shift',7,time.monotonic()))
assert captures==[7] and not a.errors
assert a._keyboard_request['focus'] is before
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
assert len(a.bridge.done.values)==1 and not a.errors
state['focus']=child_changed_again
a.apply_result(a.bridge.done.values[-1])
assert deliveries==['translation'] and a.bridge.keyboard_applied.values==[(True,'sent')]

# A different foreground at the immediate gesture check is refused.
a=app();state['capture_change']=other_app
a.run_translation(('shift',7,time.monotonic()))
assert a.errors and not captures and not a.bridge.done.values

# A different foreground at GUI handoff is dropped before model work.
a=app();a.run_translation(('shift',7,time.monotonic()));state['focus']=other_app
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
assert not a.bridge.done.values and not a.busy and not deliveries

# A different foreground just before model work or just before paste refuses.
a=app();state['focus']=other_app
a.start_translation('shift',before,(),'source',('keyboard',NS()))
assert a.errors and not a.bridge.done.values
a=app();a.run_translation(('shift',7,time.monotonic()))
a.keyboard_captured(a.bridge.keyboard_captured.values[-1]);state['focus']=other_app
a.apply_result(a.bridge.done.values[-1])
assert a.errors and not deliveries

# Provider ranges and TSF snapshots retain strict child/thread identity checks.
for route in ('tsf','range','value'):
    a=app();state['focus']=child_changed
    a.start_translation('shift',before,(),'source',(route,NS()))
    assert a.errors and not a.bridge.done.values
    a=app();state['focus']=child_changed
    a.apply_result((100,(),'source','translation',(route,NS()),before))
    assert a.errors and not deliveries

# Real user input, configuration changes and shutdown still invalidate capture.
for change in ('input','configuration','shutdown'):
    a=app();a.run_translation(('shift',7,time.monotonic()))
    if change=='input':state['revision']=8
    elif change=='configuration':state['configuration']=('changed',)
    else:a._quitting=True
    a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
    assert not a.bridge.done.values and not deliveries

print('Keyboard foreground handoff: internal child/thread/caret changes accepted; different app, actual input/config/shutdown and strict provider routes refused: PASS')
