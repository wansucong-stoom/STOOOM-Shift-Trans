"""Selection preference, routing and persistence without live user input.

Mouse/keyboard/clipboard calls are synthetic. Settings run offscreen with no
hooks, tray notifications, TSF registration, models, or network operations.
"""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
from unittest.mock import patch

os.environ['QT_QPA_PLATFORM']='offscreen'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import keyboard_access as k


def forbidden(*args,**kwargs):raise AssertionError('unexpected external side effect')


class Call:
    def __call__(self,*args):return 1
class API:
    def __getattr__(self,name):
        value=Call();setattr(self,name,value);return value

# Exercise the production constructor's default, not only a fixture constant.
with patch.object(k.C,'WinDLL',return_value=API()):
    native=k.Windows(NS(foreground=1,keyboard_window=2),lambda:(7,0),lambda:True)
assert native.selection_mode=='triple_click'


class Lease:
    def __init__(self,env):self.env=env;self.text=None;self.kept=False
    def arm_copy(self):self.text=None;self.env.lease=self
    def read_copy(self,pids):return self.text
    def restore(self):return not self.kept
    def replace_owned(self,expected,text):assert self.text==expected;self.text=text
    def keep_translation(self):self.kept=True;return 1


class Editor:
    select=k.Windows.select
    select_by_click=k.Windows.select_by_click
    click=k.Windows.click
    def __init__(self,mode='triple_click',selection=None,point=(10,20)):
        self.text='BEFORE\nCurrent sentence.\nAFTER'
        self.start=len('BEFORE\n');self.end=self.start+len('Current sentence.')
        self.anchor_pos=self.active=self.end
        if selection is not None:self.anchor_pos,self.active=selection
        self.selection_mode=mode;self.point=point;self.pointer=(80,90)
        self.revision=7;self.focus=object();self.owner_pids=(123,)
        self.clock=0;self.clicks=[];self.moves=[];self.keys=[];self.sent=[];self.pastes=0
        self.u=NS(GetCursorPos=self.get_pointer)
    def get_pointer(self,output):
        output._obj.x,output._obj.y=self.pointer;return True
    def current(self):return True
    def activity(self):return self.revision,self.clock
    def modifiers(self):return False
    def safe(self):pass
    def now(self):return self.clock
    def sleep(self,seconds):self.clock+=seconds
    def anchor(self):return self.anchor_pos,self.active
    def caret_point(self):return self.point
    def click_point(self):return self.point
    def factory(self):return Lease(self)
    def _move(self,point):self.moves.append(point);self.pointer=point
    def _send(self,events):
        assert [event.mouse.flags for event in events]==[2,4]
        assert all(event.kind==0 and event.mouse.extra==k.INPUT_TAG for event in events)
        self.sent.extend(events);self.clicks.append(self.pointer)
        if len(self.clicks)==3:self.anchor_pos,self.active=self.start,self.end
    def chord(self,*keys):
        self.keys.append(keys)
        start,end=sorted((self.anchor_pos,self.active))
        if keys==(k.CTRL,ord('C')):self.lease.text=self.text[start:end] if start!=end else None
        elif keys==(k.SHIFT,k.HOME):self.active=self.start
        elif keys==(k.CTRL,ord('V')):
            self.text=self.text[:start]+self.lease.text+self.text[end:]
            self.anchor_pos=self.active=start+len(self.lease.text);self.pastes+=1
        else:raise AssertionError(('unexpected navigation',keys))


e=Editor();original=e.text;driver=k.Driver(e,e.factory)
snapshot=driver.capture(7)
assert snapshot.text=='Current sentence.' and snapshot.selected_automatically
assert e.clicks==[(10,20)]*3 and len(e.sent)==6 and e.pointer==(80,90)
assert e.text==original and all(keys==(k.CTRL,ord('C')) for keys in e.keys)
driver.apply(snapshot,'Translation.')
assert e.text=='BEFORE\nTranslation.\nAFTER' and e.pastes==1 and len(e.clicks)==3

e=Editor('current_line');e.active=e.anchor_pos=e.start+7
driver=k.Driver(e,e.factory);snapshot=driver.capture(7)
assert snapshot.text=='Current' and snapshot.selected_automatically
assert e.keys.count((k.SHIFT,k.HOME))==1 and not e.moves and not e.clicks

# Existing user ranges are honored in both modes, both selection directions,
# and when a manual selection includes a paragraph delimiter.
for mode in ('triple_click','current_line'):
    for include_break in (0,1):
        for backward in (False,True):
            e=Editor(mode);start,end=e.start,e.end+include_break
            e.anchor_pos,e.active=(end,start) if backward else (start,end)
            original=e.text;anchor=e.anchor();driver=k.Driver(e,e.factory)
            snapshot=driver.capture(7)
            assert snapshot.text==original[start:end] and not snapshot.selected_automatically
            assert e.anchor()==anchor and not e.clicks and not e.moves
            assert all(keys==(k.CTRL,ord('C')) for keys in e.keys)

# An unrelated pointer is never used when caret lookup fails, and there is
# no fallback to Home or paragraph movement after the failed lookup.
e=Editor(point=None);original=e.text
try:k.Driver(e,e.factory).capture(7)
except k.KeyboardError:pass
else:raise AssertionError('missing caret was accepted')
assert e.text==original and not e.clicks and not e.moves
assert e.keys==[(k.CTRL,ord('C'))]


class Listener:
    def start(self):pass
    def stop(self):pass
class Tap:
    def __init__(self,bridge):self.listener=Listener()
    def activity_snapshot(self):return 7,0
    def activity_cause(self):return 'unknown'
class Tray:
    ActivationReason=NS(Trigger=1,DoubleClick=2)
    MessageIcon=NS(Information=1,Warning=2)
    def __init__(self,*args):self.activated=NS(connect=lambda callback:None)
    def setContextMenu(self,menu):pass
    def setToolTip(self,text):pass
    def show(self):pass
    def hide(self):pass
    def showMessage(self,*args):forbidden()
class Request:
    def requested(self):return False
    def close(self):pass
class Client:
    def __init__(self,*args):pass
    def close(self):pass
class Signal:
    def __init__(self):self.values=[]
    def emit(self,value):self.values.append(value)


with tempfile.TemporaryDirectory() as directory:
    with patch.dict(os.environ,{'LOCALAPPDATA':directory}):import main
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication,QEvent,QTimer
    from PySide6.QtGui import QFontDatabase
    qt=QApplication.instance() or QApplication([])
    # Offscreen Qt does not reliably enumerate Windows system fonts.
    font=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'malgun.ttf'
    if font.is_file():QFontDatabase.addApplicationFont(str(font))
    main.APP=Path(directory)/'settings';main.APP.mkdir()
    main.MODELS=main.APP/'models';main.MODELS.mkdir()
    settings_path=main.APP/'settings.json'
    preflights=[]
    preview=os.environ.get('SST_SELECTION_PREVIEW')
    def preflight(window):
        preflights.append(window);window.engine_initializing=False
    def dispose(window):
        window._quitting=True
        for timer in window.findChildren(QTimer):timer.stop()
        window._input_trace.close();window.deleteLater()
        QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    with patch.object(main,'Tap',Tap),patch.object(main,'QSystemTrayIcon',Tray), \
         patch.object(main.App,'begin_engine_preflight',preflight), \
         patch.object(main.tsf_bridge,'Client',Client), \
         patch.object(main.tsf_bridge,'activate_installed',lambda:'test'), \
         patch.object(main.update_control,'UpdateRequest',Request), \
         patch.object(main.urllib.request,'urlopen',forbidden), \
         patch.object(main.caret_locator,'warmup',lambda:None):
        for stored in ({},{'selection_mode':'unsupported'}, {'selection_mode':None},
                       {'selection_mode':'triple_click'},{'selection_mode':'current_line'}):
            settings_path.write_text(json.dumps(stored),encoding='utf-8')
            window=main.App();qt.processEvents()
            expected='current_line' if stored.get('selection_mode')=='current_line' else 'triple_click'
            assert window.selection_mode.currentData()==expected
            assert {window.selection_mode.itemData(i) for i in range(window.selection_mode.count())}=={'triple_click','current_line'}
            assert not window.isVisible()
            if preview:
                destination=Path(preview).resolve();destination.parent.mkdir(parents=True,exist_ok=True)
                window.resize(850,590);window.show();qt.processEvents()
                assert window.grab().save(str(destination))
                window.hide();preview=None
            # Choice changes save without rewarming the translation model.
            configuration=window.engine_configuration();count=len(preflights)
            selected='current_line' if expected=='triple_click' else 'triple_click'
            window.selection_mode.setCurrentIndex(window.selection_mode.findData(selected))
            qt.processEvents()
            assert window.engine_configuration()==configuration and len(preflights)==count
            assert json.loads(settings_path.read_text(encoding='utf-8'))['selection_mode']==selected
            dispose(window)
            window=main.App();qt.processEvents()
            assert window.selection_mode.currentData()==selected
            dispose(window)

        # Capture the choice on the GUI thread. Changing the setting before a
        # queued worker starts must not make it read Qt widgets from that worker.
        settings_path.write_text('{"selection_mode":"current_line"}',encoding='utf-8')
        window=main.App();qt.processEvents()
        choice=window.selection_mode.currentData;gui_thread=threading.get_ident()
        def gui_choice(*args):
            assert threading.get_ident()==gui_thread,'worker read a Qt setting'
            return choice(*args)
        window.selection_mode.currentData=gui_choice
        pending=[];envs=[]
        class DeferredThread:
            def __init__(self,target,**kwargs):self.target=target
            def start(self):pending.append(self.target)
        class Driver:
            def __init__(self,env,report=None):self.env=env
            def capture(self,revision,commit_space=False):
                assert self.env.selection_mode=='current_line'
                return k.Snapshot('Source',focus,revision,None,True)
        def environment(*args):
            value=NS();envs.append(value);return value
        focus=NS(foreground=1,keyboard_window=2,thread_id=3)
        signal=Signal();window.bridge=NS(keyboard_captured=signal)
        with patch.object(main,'threading',NS(Thread=DeferredThread)), \
             patch.object(main.keyboard_access,'Windows',environment), \
             patch.object(main.keyboard_access,'Driver',Driver):
            window.begin_keyboard_capture('shift',7,time.monotonic(),focus)
            request=window._keyboard_request
            assert request['selection_mode']=='current_line' and len(pending)==1
            window.selection_mode.setCurrentIndex(window.selection_mode.findData('triple_click'))
            worker=threading.Thread(target=pending.pop());worker.start();worker.join(timeout=3)
            assert not worker.is_alive() and len(signal.values)==1
            received,(snapshot,error)=signal.values[0]
            assert received is request and snapshot.text=='Source' and not error
            assert envs[0].selection_mode=='current_line' and not window._keyboard_workers
        dispose(window)

print('selection mode: default triple click, explicit line choice, manual range priority, missing-caret refusal, settings persistence and GUI-thread snapshot: PASS')
