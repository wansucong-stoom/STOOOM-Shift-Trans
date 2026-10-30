"""Exercise the App diagnostic stages with AST mocks and no desktop/clipboard."""
import ast
from pathlib import Path
import time
from types import SimpleNamespace as NS

source=Path(__file__).resolve().parents[1]/'main.py'
tree=ast.parse(source.read_text(encoding='utf-8'))
helpers={'_input_error_message','_input_record','_input_activity_cause','_input_current_focus'}
methods={'run_translation','begin_keyboard_capture','keyboard_captured','start_translation',
         'apply_result','error','cancel_pending_input','keyboard_capture_timeout'}
nodes=[]
for node in tree.body:
    if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='_INPUT_ERROR_MESSAGES' for target in node.targets):nodes.append(node)
    elif isinstance(node,ast.FunctionDef) and node.name in helpers:nodes.append(node)
    elif isinstance(node,ast.ClassDef) and node.name=='App':
        selected=[method for method in node.body if isinstance(method,ast.FunctionDef) and method.name in methods]
        nodes.append(ast.ClassDef(name='App',bases=[],keywords=[],body=selected,decorator_list=[]))

class Signal:
    def __init__(self):self.values=[]
    def emit(self,value):self.values.append(value)
class Trace:
    def __init__(self):self.rows=[]
    def record(self,phase,**details):self.rows.append({'phase':phase,**details})
class Thread:
    def __init__(self,target,**details):self.target=target
    def start(self):self.target()
class Driver:
    def __init__(self,env,report):self.report=report;assert callable(env.activity_cause)
    def capture(self,revision,commit_space):
        assert not commit_space
        self.report('copy_done',revision=revision,source_chars=6)
        return NS(text='SOURCE',revision=revision)
    def apply(self,snapshot,text):self.report('paste_sent',output_chars=len(text));return 'delivered'
focus=NS(foreground=8,keyboard_window=9,thread_id=10)
revision=[7];configuration=[('same',)];queued=[]
ns={'time':time,'Path':Path,'LANGS':{'한국어':'ko','영어':'en'},
    'keyboard_safety':lambda:True,'path_for':lambda src,dst:['ko_en_opus_big'],
    'translate_route':lambda text,route:text,'translate_external':lambda *args:'translation',
    'QTimer':NS(singleShot=lambda delay,callback:queued.append(callback)),
    'QSystemTrayIcon':NS(MessageIcon=NS(Information=1)),
    'threading':NS(Thread=Thread),
    'keyboard_access':NS(Windows=lambda *args:NS(),Driver=Driver),
    'focus_guard':NS(capture=lambda:focus,unchanged=lambda expected:expected is focus,same_foreground=lambda expected:expected is focus),
    'ctypes':NS(windll=NS(user32=NS(GetForegroundWindow=lambda:8)))}
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(source),'exec'),ns)

def app():
    a=ns['App']();a._input_trace=Trace();a._input_active_job=None
    a._quitting=False;a.busy=False;a.engine_initializing=False
    a._keyboard_request=None;a._pending_input=None;a._startup_wait_notified=False
    a.tap=NS(activity_snapshot=lambda:(revision[0],0.0),activity_cause=lambda:'typing')
    a.target={'shift':NS(currentText=lambda:'영어')};a.source=NS(currentText=lambda:'한국어')
    a.selection_mode=NS(currentData=lambda:'triple_click')
    a.engine=NS(currentText=lambda:'기본 오프라인 엔진');a.external_path=''
    a.bridge=NS(keyboard_captured=Signal(),keyboard_applied=Signal(),done=Signal(),error=Signal())
    a.isActiveWindow=lambda:False;a.engine_configuration=lambda:configuration[0]
    a.input_readiness=NS(setText=lambda text:None)
    a.status=NS(setText=lambda message:None);a.tray=NS(showMessage=lambda *args:None)
    return a

a=app();a.run_translation(('shift',7,time.monotonic()))
assert a._input_active_job==1 and a._keyboard_workers==0
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
phases=[row['phase'] for row in a._input_trace.rows]
assert phases==['gesture.received','capture.requested','copy_done','capture.completed','capture.accepted','model.started','model.completed'],phases
model=a._input_trace.rows[-1]
assert model['same_output'] is True and model['source_chars']==model['output_chars']==6
assert model['model_ids']==['ko_en_opus_big'] and model['job']==1
a.apply_result(a.bridge.done.values[-1])
assert [row['phase'] for row in a._input_trace.rows[-3:]]==['paste.requested','paste_sent','paste.delivery.completed']
assert 'SOURCE' not in repr(a._input_trace.rows)

# User input between capture and GUI handling is retained as an explicit drop,
# without showing another error toast or translating a changed selection.
a=app();a.run_translation(('shift',7,time.monotonic()));revision[0]=8
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
drop=a._input_trace.rows[-1]
assert drop['phase']=='capture.dropped.input' and drop['cause']=='typing'
assert drop['revision']==7 and drop['current_revision']==8 and not a.busy
assert not a.bridge.done.values and not a.bridge.error.values
revision[0]=7
a=app();a.run_translation(('shift',7,time.monotonic()));configuration[0]=('different',)
a.keyboard_captured(a.bridge.keyboard_captured.values[-1])
assert a._input_trace.rows[-1]['phase']=='capture.dropped.configuration'
configuration[0]=('same',)

# Raw engine errors never become diagnostics or a toast, even if they echo text.
def failed_engine(text,route):raise RuntimeError('PRIVATE DOCUMENT and C:/secret/engine.exe')
ns['translate_route']=failed_engine
a=app();a._input_active_job=3
a.start_translation('shift',focus,(),'SOURCE',('keyboard',NS()))
assert a.bridge.error.values==['번역 엔진 실행 중 오류가 발생했습니다.']
assert a._input_trace.rows[-1]['phase']=='model.failed'
a.error('PRIVATE DOCUMENT and C:/secret/engine.exe')
assert a._input_trace.rows[-1]['error_message']=='번역 작업을 완료하지 못했습니다.'
assert 'PRIVATE' not in repr(a._input_trace.rows)
a.error('선택 위치가 바뀌어 교체를 취소했습니다.')
assert a._input_trace.rows[-1]['error_message']=='선택 위치가 바뀌어 교체를 취소했습니다.'

# Ignored requests get their own job without changing the running request ID.
a=app();a.busy=True;a._input_active_job=9
a.run_translation(('shift',7,time.monotonic()))
assert a._input_active_job==9 and a._input_trace.rows[-1]['phase']=='gesture.ignored.busy'
assert a._input_trace.rows[-1]['job']==1

# A failed focus acquisition belongs to the newly accepted request.
a=app();a._input_active_job=9
def no_focus():raise ValueError('텍스트 입력 위치를 확인하지 못했습니다.')
ns['focus_guard'].capture=no_focus
a.run_translation(('shift',7,time.monotonic()))
assert a._input_trace.rows[-1]['phase']=='toast.error' and a._input_trace.rows[-1]['job']==1

# Focus cancellation must not be misclassified as the last historical typing
# activity. Only exact known messages select that category; arbitrary exception
# text is still replaced by the generic diagnostic error.
failure=['입력창의 포커스가 바뀌어 번역을 취소했습니다.']
class FailedDriver(Driver):
    def capture(self,*args,**kwargs):raise RuntimeError(failure[0])
    def apply(self,*args,**kwargs):raise RuntimeError(failure[0])
ns['keyboard_access'].Driver=FailedDriver
a=app();a.begin_keyboard_capture('shift',7,time.monotonic(),focus)
assert a._input_trace.rows[-1]['phase']=='capture.failed' and a._input_trace.rows[-1]['cause']=='focus'
a=app();a.apply_result((8,(),'SOURCE','translation',('keyboard',NS()),focus))
assert a._input_trace.rows[-1]['phase']=='paste.delivery.failed' and a._input_trace.rows[-1]['cause']=='focus'
assert a.bridge.keyboard_applied.values==[(False,failure[0])]
failure[0]='PRIVATE DOCUMENT exception'
a=app();a.begin_keyboard_capture('shift',7,time.monotonic(),focus)
assert a._input_trace.rows[-1]['cause']=='typing'
assert a._input_trace.rows[-1]['error_message']=='번역 작업을 완료하지 못했습니다.'
print('App diagnostic AST mocks: request/capture/model/paste stages, identity output, silent drop causes, fixed safe errors and ignored jobs: PASS')
