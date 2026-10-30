import os, sys
# The windowed clipboard helper must enter before Qt/UIA, hooks, settings, or
# singleton initialization. Its inherited private pipes are its only interface.
if __name__=='__main__' and sys.argv[1:]==['--clipboard-worker']:
 import clipboard_worker
 sys.exit(clipboard_worker.run())
import json, time, threading, hashlib, zipfile, urllib.request, tempfile, shutil, re, ctypes, subprocess, unicodedata, functools
import singleton
import range_access
import clipboard_process as clipboard_lease
import chunking
import focus_guard
import engine_readiness
import input_settle
import model_packs
import tsf_bridge
import update_control
import release_updates
import keyboard_access
import input_diagnostics
import windows_identity
import native_decode
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer, QUrl
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSystemTrayIcon, QMenu, QMessageBox, QFileDialog, QStackedWidget, QFrame, QProgressBar
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QDesktopServices
from pynput import keyboard, mouse
from pywinauto.uia_defines import IUIA
from pywinauto.uia_element_info import UIAElementInfo
from pywinauto.controls.uiawrapper import UIAWrapper

APP = Path(os.environ['LOCALAPPDATA']) / 'STOOMShiftTranslator05'
MODELS = APP / 'models'
PACKS = {
 'en_ja': ('16300cc4eaa85320520cabcf433b63d01be40ef6966251de72043a083408f716',120470284),
 'en_ko': ('e03d8e65e6d44525ec5808c3409fcf8728c76c2c76925372b6d3dc3278de17fc',120789009),
 'ja_en': ('623e3477959a815eb0a5ef53e09079ae8f1f9d3bbcd230473baf28c03fb83335',117155716),
 'ko_en': ('6da8f3db6ca40f42b1875570a1c06856f6e17c7ef62845d85de217ba548c1471',118852077)}
LANGS={'한국어':'ko','영어':'en','일본어':'ja'}
VARIANTS={}
APP.mkdir(parents=True,exist_ok=True); MODELS.mkdir(exist_ok=True)
class Bridge(QObject):
 trigger=Signal(object); done=Signal(object); error=Signal(str); download_done=Signal(str); startup=Signal(object); download_progress=Signal(str)
 tsf_captured=Signal(object); tsf_applied=Signal(object); tsf_status=Signal(str)
 release_event=Signal(object); release_progress=Signal(object)
 keyboard_captured=Signal(object); keyboard_applied=Signal(object)

_INPUT_ERROR_MESSAGES=frozenset((
 '텍스트 입력 위치를 확인하지 못했습니다.','Windows가 입력 전달을 허용하지 않았습니다.',
 '화면 좌표를 확인하지 못했습니다.','마우스 위치가 바뀌어 자동 선택을 취소했습니다.',
 '입력창의 포커스가 바뀌어 번역을 취소했습니다.','새 키보드 입력이나 클릭·스크롤이 감지되어 번역을 취소했습니다.',
 '단축키에서 손을 뗀 뒤 다시 시도하세요.','조합 확정용 공백의 추가를 확인하지 못했습니다. 입력창을 확인하세요.',
 '조합 확정용 공백을 확인하지 못했습니다. 입력창을 확인하세요.','선택·복사할 글이 없습니다. 글을 선택한 뒤 다시 시도하세요.',
 '번역할 글이 없습니다.','문단을 자동으로 인식하지 못했습니다. 원하는 문장을 드래그해 직접 선택한 뒤 다시 시도해 주세요.',
 '선택한 텍스트가 너무 길거나 텍스트 이외의 개체가 포함되어 있습니다.','복사된 원문이 바뀌어 번역을 취소했습니다.',
 '번역 결과가 비어 있거나 너무 깁니다.','새 키보드 입력이 있어 교체를 취소했습니다.',
 '선택 위치가 바뀌어 교체를 취소했습니다.','선택된 원문이 바뀌어 교체를 취소했습니다.',
 '클립보드가 바뀌어 교체를 취소했습니다.','키보드 입력 위치가 바뀌어 취소했습니다.',
 '키보드 입력 위치가 바뀌어 교체하지 않았습니다.','현재 입력 영역에 번역할 문장이 없습니다.',
 '입력창의 응답 확인 시간이 초과되었습니다. 다시 시도할 수 있습니다.',
 '필요한 언어팩이 없습니다. 설정에서 다운로드하세요.','원문과 목표 언어가 같습니다.',
 '사용자 번역 엔진 실행 파일을 선택하세요.','원문 언어를 판별할 수 없습니다.',
 '번역 엔진 실행 중 오류가 발생했습니다.','번역 엔진을 준비하고 있습니다.',
 '번역문은 전달했지만 결과를 확인하지 못했습니다. 입력창을 확인해 주세요.',
 '번역문을 붙여넣었으나 이전 클립보드를 복원하지 못했습니다.'))

def _input_error_message(message):
 # Engine exceptions can include a sentence or an executable path. Retain
 # fixed input toasts verbatim, and use one generic message for everything else.
 return message if isinstance(message,str) and message in _INPUT_ERROR_MESSAGES else '번역 작업을 완료하지 못했습니다.'

def _input_record(app,phase,**details):
 trace=getattr(app,'_input_trace',None)
 if trace is None:return
 try:
  details.setdefault('job',getattr(app,'_input_active_job',None))
  trace.record(phase,**details)
 except Exception:pass

def _input_activity_cause(app,message=None):
 if message in ('입력창의 포커스가 바뀌어 번역을 취소했습니다.',
                '키보드 입력 위치가 바뀌어 취소했습니다.',
                '키보드 입력 위치가 바뀌어 교체하지 않았습니다.'):return 'focus'
 try:return app.tap.activity_cause()
 except Exception:return 'unknown'

def _input_current_focus():
 try:return focus_guard.capture()
 except Exception:return None

def keyboard_safety():
 # The common route verifies the foreground window and recopies the actual
 # source before paste. Child focus/caret identity may change inside an editor;
 # provider COM metadata is not needed for this keyboard/clipboard route.
 return True

def focused_element():
 raw=IUIA().iuia.GetFocusedElement()
 if not raw: raise ValueError('현재 입력창을 확인할 수 없습니다.')
 info=UIAElementInfo(raw)
 if not raw.GetCurrentPropertyValue(30010) or raw.GetCurrentPropertyValue(30019):
  raise ValueError('보안 입력창 또는 사용할 수 없는 입력창입니다.')
 rid=tuple(info.runtime_id)
 if not rid: raise ValueError('입력창을 식별할 수 없습니다.')
 return rid,info,UIAWrapper(info)

def focused():
 rid,info,wrapper=focused_element()
 try:
  value=wrapper.iface_value
 except Exception as e:
  raise ValueError('입력창의 값을 확인할 수 없습니다.') from e
 if value.CurrentIsReadOnly: raise ValueError('읽기 전용 입력창입니다.')
 return rid,value.CurrentValue,value

def capture_input():
 rid,info,wrapper=focused_element()
 value=None
 try:
  value=wrapper.iface_value
  if value.CurrentIsReadOnly: raise ValueError('읽기 전용 입력창입니다.')
 except ValueError: raise
 except Exception: value=None
 # A document is a structured editor, so operate on selection/paragraph,
 # never the entire document's ValuePattern.
 document_mode=info.control_type == 'Document'
 try:
  snapshot=range_access.capture(rid,wrapper.iface_text,document_mode)
  if value is None:
   read_only=snapshot.target.GetAttributeValue(40015)
   if not isinstance(read_only,(bool,int)) or bool(read_only):
    raise ValueError('편집 가능 여부를 확인할 수 없습니다.')
  return rid,snapshot.text,('range',snapshot)
 except Exception as e:
  # Some native text boxes offer only ValuePattern. Structured documents
  # must never be replaced as a whole through ValuePattern.
  if not document_mode and value is not None and value.CurrentValue.strip():
   return rid,value.CurrentValue,('value',None)
  raise ValueError('이 편집 영역의 텍스트 범위를 읽을 수 없습니다.') from e

def move_caret_to_end(hwnd, expected_runtime_id):
 """Place the caret at the end when the same focused edit supports TextPattern."""
 try:
  if ctypes.windll.user32.GetForegroundWindow() != hwnd: return False
  raw=IUIA().iuia.GetFocusedElement()
  if raw is None: return False
  info=UIAElementInfo(raw)
  if tuple(info.runtime_id) != expected_runtime_id: return False
  if raw.GetCurrentPropertyValue(30019): return False
  document=UIAWrapper(info).iface_text.DocumentRange
  end=document.Clone()
  end.MoveEndpointByRange(0,document,1)
  if ctypes.windll.user32.GetForegroundWindow() != hwnd: return False
  end.Select()
  return True
 except Exception:
  return False

def guess(s):
 if re.search('[가-힣]',s): return 'ko'
 if re.search('[ぁ-ゟ゠-ヿ]',s): return 'ja'
 if re.search('[一-鿿]',s): raise ValueError('한자가 포함되어 원문 언어를 자동 판별할 수 없습니다. 원문 언어를 직접 선택하세요.')
 if re.search('[a-zA-Z]',s): return 'en'
 raise ValueError('원문 언어를 판별할 수 없습니다.')

def pack_installed(k):
 if k not in PACKS:return model_packs.installed(MODELS,k)
 return (MODELS/k/'model'/'model.bin').is_file() and (MODELS/k/'sentencepiece.model').is_file()

def path_for(src,dst):
 exists=pack_installed
 if src==dst: raise ValueError('원문과 목표 언어가 같습니다.')
 direct=src+'_'+dst
 selected=selected_model(direct)
 if selected in model_packs.CATALOG and exists(selected): return [selected]
 if src!='en' and dst!='en':
  route=[selected_model(pair) for pair in (src+'_en','en_'+dst)]
  if all(exists(k) for k in route): return route
 raise ValueError('필요한 언어팩이 없습니다. 설정에서 다운로드하세요.')

def default_model(pair):
 return pair+'_opus_big' if pair in ('ko_en','en_ko') else pair

def selected_model(pair):
 selected=VARIANTS.get(pair,default_model(pair))
 spec=model_packs.CATALOG.get(selected)
 return selected if spec and spec.source_language+'_'+spec.target_language==pair else default_model(pair)

def translate_external(executable,text,src,dst):
 payload=json.dumps({'text':text,'source':src,'target':dst},ensure_ascii=False).encode('utf-8')
 proc=subprocess.run([executable],input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 if proc.returncode: raise ValueError('외부 번역 엔진이 오류를 반환했습니다.')
 if len(proc.stdout)>2_000_000: raise ValueError('외부 엔진 출력이 너무 큽니다.')
 data=json.loads(proc.stdout.decode('utf-8'))
 result=data.get('translation')
 if not isinstance(result,str) or not result.strip(): raise ValueError('외부 엔진의 번역 결과가 올바르지 않습니다.')
 return result

class PairedTokenizer:
 def __init__(self,source,target):self.source=source;self.target=target
 def encode(self,*args,**kwargs):return self.source.encode(*args,**kwargs)
 def decode(self,*args,**kwargs):return self.target.decode(*args,**kwargs)

def load_sentencepiece(path):
 import sentencepiece
 try:return sentencepiece.SentencePieceProcessor(model_file=str(path))
 except RuntimeError:
  # SentencePiece's Windows narrow-path loader can reject Korean user paths.
  return sentencepiece.SentencePieceProcessor(model_proto=Path(path).read_bytes())

@functools.lru_cache(maxsize=2)
def _load_model_cached(model_path,model_stamp,tokenizer_stamp,target_path=None,target_stamp=None):
 import ctranslate2, sentencepiece
 p=Path(model_path)
 tokenizer=load_sentencepiece(p/('source.spm' if target_path else 'sentencepiece.model'))
 if target_path:
  tokenizer=PairedTokenizer(tokenizer,load_sentencepiece(target_path))
 translator=ctranslate2.Translator(str(p/'model'),compute_type='int8',intra_threads=4)
 return tokenizer,translator

def load_model(k):
 p=MODELS/k
 model_stamp=(p/'model'/'model.bin').stat().st_mtime_ns
 if k not in PACKS:
  files=model_packs.runtime_files(MODELS,k)
  return _load_model_cached(str(p),model_stamp,files.source_spm.stat().st_mtime_ns,str(files.target_spm),files.target_spm.stat().st_mtime_ns)
 tokenizer_stamp=(p/'sentencepiece.model').stat().st_mtime_ns
 return _load_model_cached(str(p),model_stamp,tokenizer_stamp)

def translate(text,src,dst):
 return translate_route(text,path_for(src,dst))

def translate_route(text,route):
 for k in route:
  sp,tr=load_model(k)
  output=[]
  for should_translate,part in chunking.chunks(text,sp):
   if not should_translate:
    output.append(part); continue
   translated=native_decode.translate_part(k,sp,tr,part)
   output.append(translated)
  text=''.join(output)
  if not text.strip(): raise ValueError('번역 결과가 비어 있어 교체하지 않습니다.')
 return text

def install_pack(k,progress=None):
 return model_packs.install(k,MODELS,progress=progress)

class Tap:
 def __init__(self,bridge):
  self.bridge=bridge; self.down=set(); self.last={}; self.used=set(); self.pending=set(); self.started={}; self._activity=(0,0.0);self._pointer_buttons=set();self._activity_cause='unknown'
  self.listener=keyboard.Listener(on_press=self.press,on_release=self.release,win32_event_filter=self.event_filter)
  self.mouse_listener=mouse.Listener(on_click=self.pointer_click,on_scroll=self.pointer_activity,on_move=self.pointer_move,win32_event_filter=self.event_filter)
 def event_filter(self,msg,data):
  return getattr(data,'dwExtraInfo',0)!=keyboard_access.INPUT_TAG
 def pointer_move(self,*args):
  # pynput 1.8 passes (x, y, injected), older versions passed (x, y).
  # Free motion does not alter a selection. A real held-button drag does.
  if self._pointer_buttons:self.pointer_activity();self._activity_cause='drag'
 def pointer_click(self,x,y,button,pressed,*extra):
  if pressed:self._pointer_buttons.add(button)
  else:self._pointer_buttons.discard(button)
  self.pointer_activity()
  self._activity_cause='click'
 def pointer_activity(self,*args):
  revision,_=self._activity;self._activity=(revision+1,time.monotonic())
  self._activity_cause='scroll'
  self.last.clear();self.pending.clear()
 def kind(self,k):
  if k in (keyboard.Key.shift,keyboard.Key.shift_l,keyboard.Key.shift_r): return 'shift'
  if k in (keyboard.Key.ctrl,keyboard.Key.ctrl_l,keyboard.Key.ctrl_r): return 'ctrl'
  return None
 def other_key_physically_down(self,kind):
  # Query Windows for current physical state. Do not retain printable-key
  # names, because layouts/IME can report different values on key up.
  ignore={0x10,0xA0,0xA1} if kind=='shift' else {0x11,0xA2,0xA3}
  try:
   getstate=ctypes.windll.user32.GetAsyncKeyState
   return any(getstate(vk) & 0x8000 for vk in range(8,255) if vk not in ignore)
  except Exception:
   return True
 def press(self,k):
  kind=self.kind(k); now=time.monotonic()
  if kind is None:
   revision,_=self._activity; self._activity=(revision+1,now)
   self._activity_cause='typing'
   self.last.clear(); self.used.update(self.down); self.pending.clear()
   return
  if kind in self.down: return
  if self.down or self.other_key_physically_down(kind):
   self.used.update(self.down); self.used.add(kind); self.pending.clear(); self.last.clear()
  if kind not in self.used and kind in self.last and 0 <= now-self.last[kind] <= .35:
   self.last.clear(); self.pending.add(kind)
  self.down.add(kind); self.started[kind]=now
 def activity_snapshot(self):
  return self._activity
 def activity_cause(self):
  return self._activity_cause
 def release(self,k):
  kind=self.kind(k); now=time.monotonic()
  if kind is None:
   revision,_=self._activity; self._activity=(revision,now)
   return
  if kind not in self.down: return
  self.down.discard(kind)
  valid=kind not in self.used and now-self.started.get(kind,now)<=.35
  fire=valid and kind in self.pending
  self.pending.discard(kind); self.started.pop(kind,None); self.used.discard(kind)
  if fire:
   self.last.clear(); self.bridge.trigger.emit((kind,self._activity[0],now))
  elif valid:self.last[kind]=now
  else:self.last.pop(kind,None)

class App(QWidget):
 def __init__(self):
  super().__init__(); self.setWindowTitle('STOOM Shift Translator — 설정'); self.resize(850,590); self.setMinimumSize(720,520)
  self._input_trace=input_diagnostics.Trace(APP/'input-diagnostics.jsonl');self._input_job_counter=0;self._input_active_job=None
  self.setStyleSheet("""
   QWidget { background: #fff; color: #172f3e; font-family: 'Malgun Gothic'; font-size: 10pt; }
   QFrame#sidebar { background: #f7f8fa; border-right: 1px solid #e6e9ed; }
   QFrame#sidebar QLabel, QFrame#sidebar QPushButton { background: transparent; }
   QLabel { background: transparent; }
   QPushButton#nav { border: 0; text-align: left; color: #6a7380; padding: 12px 15px; }
   QPushButton#nav:checked { background: #edf2f4; color: #17394c; font-weight: 700; border-left: 3px solid #17394c; }
   QPushButton#nav:hover { background: #edf2f4; }
   QComboBox { min-width: 160px; background: #fff; border: 1px solid #d8dce2; border-radius: 4px; padding: 7px 10px; }
   QComboBox:hover { border-color: #758c9a; }
   QComboBox::drop-down { border: 0; width: 22px; }
   QComboBox QAbstractItemView { background: #fff; selection-background-color: #e9eff1; color: #172f3e; }
   QPushButton#action { background: #17394c; color: white; border: 1px solid #17394c; border-radius: 4px; padding: 8px 16px; }
   QPushButton#action:hover { background: #28546b; }
   QPushButton#secondary { background: #fff; color: #17394c; border: 1px solid #cfd6dc; border-radius: 4px; padding: 8px 14px; }
   QPushButton#secondary:hover { background: #f4f7f8; }
   QCheckBox { spacing: 9px; padding: 9px 0; }
  """)
  self.bridge=Bridge(); self.bridge.trigger.connect(self.run_translation); self.bridge.done.connect(self.apply_result); self.bridge.error.connect(self.error); self.bridge.download_done.connect(self.download_done); self.bridge.startup.connect(self.engine_preflight_done)
  self.busy=False; self.downloading=False; self.external_path=''; self.engine_initializing=True; self._startup_wait_notified=False; self._clipboard_lease=None; self._pending_input=None; self._quitting=False;self._keyboard_request=None;self._keyboard_workers=0;self._quit_requested=False
  self.bridge.keyboard_captured.connect(self.keyboard_captured);self.bridge.keyboard_applied.connect(self.keyboard_applied)
  root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
  sidebar=QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(220); side=QVBoxLayout(sidebar); side.setContentsMargins(0,30,0,20); side.setSpacing(0)
  icon_path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'stoom.ico'
  brandrow=QHBoxLayout(); brandrow.setContentsMargins(20,0,12,0)
  brandicon=QLabel();brandicon.setObjectName('brandLockup');brandicon.setAccessibleName('STOOM SST')
  lockup=QPixmap(str(icon_path.parent/'branding'/'sst'/'lockup-light-3x.png'));lockup.setDevicePixelRatio(3)
  brandicon.setPixmap(lockup);brandicon.setFixedSize(158,48)
  brandrow.addWidget(brandicon);brandrow.addStretch();side.addLayout(brandrow)
  caption=QLabel('     Shift Translator'); caption.setStyleSheet('font-size: 9pt; color: #7b8790;'); side.addWidget(caption); side.addSpacing(34)
  self.stack=QStackedWidget(); self.nav=[]
  for i,name in enumerate(['단축키 설정','언어팩 관리','번역 엔진','업데이트']):
   btn=QPushButton(name); btn.setObjectName('nav'); btn.setCheckable(True); btn.clicked.connect(lambda checked,idx=i:self.select_page(idx)); side.addWidget(btn); self.nav.append(btn)
  side.addStretch(); foot=QLabel(f'     v{release_updates.VERSION}  ·  {release_updates.BUILD}'); foot.setStyleSheet('color:#8a929b; font-size:9pt;'); side.addWidget(foot)
  root.addWidget(sidebar); root.addWidget(self.stack,1)
  def page(title,description):
   w=QWidget(); layout=QVBoxLayout(w); layout.setContentsMargins(44,40,44,30); layout.setSpacing(12)
   heading=QLabel(title); heading.setStyleSheet('font-size: 17pt; font-weight: 700; color:#172f3e;'); layout.addWidget(heading)
   note=QLabel(description); note.setStyleSheet('color:#7d8791;'); note.setWordWrap(True); layout.addWidget(note); layout.addSpacing(20)
   self.stack.addWidget(w); return layout
  settings=page('단축키 설정','번역할 언어를 각 단축키에 지정하세요.')
  self.target={}
  for name,key in [('Shift 두 번','shift'),('Ctrl 두 번','ctrl')]:
   row=QHBoxLayout(); label=QLabel(name); label.setMinimumWidth(190); row.addWidget(label); box=QComboBox(); box.addItems(['사용 안 함','한국어','영어','일본어']); row.addWidget(box); settings.addLayout(row); self.target[key]=box
  self.target['shift'].setCurrentText('영어')
  row=QHBoxLayout(); row.addWidget(QLabel('원문 언어')); self.source=QComboBox(); self.source.addItems(['자동','한국어','영어','일본어']); row.addWidget(self.source); settings.addLayout(row); settings.addSpacing(15)
  info=QLabel('두 키는 각각 다른 언어로 설정하거나 끌 수 있습니다.'); info.setStyleSheet('color:#7d8791;'); info.setWordWrap(True); settings.addWidget(info); self.engine_readiness=QLabel('번역 엔진 준비 중…'); self.engine_readiness.setStyleSheet('color:#7d8791;'); self.engine_readiness.setWordWrap(True); settings.addWidget(self.engine_readiness); settings.addStretch()
  self.input_readiness=QLabel('Windows 입력 지원 확인 중…'); self.input_readiness.setWordWrap(True); self.input_readiness.setStyleSheet('color:#7d8791;'); settings.addWidget(self.input_readiness)
  packs=page('언어팩 관리','OPUS-MT Big는 방향별 별도 모델입니다. 한국어↔영어는 두 방향을 각각 설치하세요. 설치 후에는 오프라인으로 번역합니다.')
  self.checks={}; self.pack_select={}
  labels={'en_ja':'영어 → 일본어 · Argos','en_ko':'영어 → 한국어 · Argos','ja_en':'일본어 → 영어 · Argos','ko_en':'한국어 → 영어 · Argos',
          'ko_en_opus_big':'한국어 → 영어 · OPUS-MT Big','en_ko_opus_big':'영어 → 한국어 · OPUS-MT Big'}
  self.pack_labels=labels
  for pair,label in [('ko_en','한국어 → 영어'),('en_ko','영어 → 한국어'),('ja_en','일본어 → 영어'),('en_ja','영어 → 일본어')]:
   row=QHBoxLayout(); box=QCheckBox(label); box.setMinimumWidth(190); row.addWidget(box)
   options=QComboBox()
   for spec in model_packs.choices(*pair.split('_')): options.addItem(spec.label,spec.id)
   row.addWidget(options,1); packs.addLayout(row); self.checks[pair]=box; self.pack_select[pair]=options
  self.status=QLabel('각 방향에서 사용할 모델을 하나 선택하세요. 내려받을 방향은 체크합니다.\nArgos: 약 112~115 MiB · OPUS-MT Big: 방향당 약 741 MiB 다운로드 후 변환'); self.status.setStyleSheet('color:#7d8791;'); self.status.setWordWrap(True); packs.addSpacing(8); packs.addWidget(self.status)
  self.pack_engine_status=QLabel('번역 엔진 준비 중…');self.pack_engine_status.setStyleSheet('color:#526b79;');self.pack_engine_status.setWordWrap(True);packs.addWidget(self.pack_engine_status)
  self.progress=QProgressBar(); self.progress.setVisible(False); packs.addWidget(self.progress)
  self.progress_time=QLabel(); self.progress_time.setStyleSheet('color:#7d8791;'); self.progress_time.setVisible(False); packs.addWidget(self.progress_time)
  self.progress_timer=QTimer(self);self.progress_timer.setInterval(1000);self.progress_timer.timeout.connect(self.update_download_time)
  self.bridge.download_progress.connect(self.show_download_progress)
  row=QHBoxLayout(); row.addStretch(); self.download_button=QPushButton('선택한 언어팩 다운로드'); self.download_button.setObjectName('action'); self.download_button.clicked.connect(self.download); row.addWidget(self.download_button); packs.addLayout(row); packs.addStretch()
  enginepage=page('번역 엔진','기본 엔진 또는 호환되는 사용자 엔진을 선택합니다.')
  self.engine=QComboBox(); self.engine.addItems(['기본 오프라인 엔진','사용자 외부 엔진']); enginepage.addWidget(self.engine)
  self.model_choices={}
  for pair,label in [('ko_en','한국어 → 영어'),('en_ko','영어 → 한국어')]:
   row=QHBoxLayout();row.addWidget(QLabel(label));box=QComboBox()
   for spec in model_packs.choices(*pair.split('_')):box.addItem(spec.label,spec.id)
   box.setCurrentIndex(box.findData(default_model(pair)))
   row.addWidget(box);enginepage.addLayout(row);self.model_choices[pair]=box
  model_note=QLabel('방향마다 다른 모델을 선택할 수 있습니다. 미설치 모델은 언어팩 관리에서 먼저 받으세요. 영어↔일본어는 Argos를 사용합니다.\nOPUS-MT: University of Helsinki · CC-BY-4.0 · INT8 변환');model_note.setWordWrap(True);model_note.setStyleSheet('color:#7d8791;');enginepage.addWidget(model_note)
  warning=QLabel('외부 엔진에는 원문이 전달됩니다. 인터넷 사용 여부는 선택한 엔진에 따라 다릅니다.'); warning.setWordWrap(True); warning.setStyleSheet('color:#7d8791;'); enginepage.addWidget(warning)
  row=QHBoxLayout(); engine_btn=QPushButton('엔진 EXE 선택'); engine_btn.setObjectName('secondary'); engine_btn.clicked.connect(self.choose_engine); row.addWidget(engine_btn); row.addStretch(); enginepage.addLayout(row)
  self.engine_path_label=QLabel('선택된 외부 엔진 없음'); self.engine_path_label.setWordWrap(True); self.engine_path_label.setStyleSheet('color:#7d8791;'); enginepage.addWidget(self.engine_path_label); enginepage.addStretch()
  updates=page('업데이트',f'현재 버전 {release_updates.VERSION} · 빌드 {release_updates.BUILD}')
  self.check_updates=QCheckBox('새 버전 자동 확인');self.check_updates.setChecked(True);updates.addWidget(self.check_updates)
  self.auto_install_updates=QCheckBox('새 버전 자동 설치');updates.addWidget(self.auto_install_updates)
  update_note=QLabel('기존 프로그램 위에 업데이트하며 받은 언어팩과 설정은 유지됩니다.\n자동 설치를 켜면 번역과 언어팩 다운로드가 끝난 뒤 설치합니다.\nWindows 입력 지원(TSF)을 업데이트할 때 관리자 승인이 필요할 수 있습니다.');update_note.setWordWrap(True);update_note.setStyleSheet('color:#7d8791;');updates.addWidget(update_note)
  self.release_status=QLabel('새 버전은 GitHub에서 확인합니다.');self.release_status.setWordWrap(True);updates.addWidget(self.release_status)
  self.release_progress=QProgressBar();self.release_progress.hide();updates.addWidget(self.release_progress)
  update_actions=QHBoxLayout();self.release_check_button=QPushButton('지금 확인');self.release_check_button.setObjectName('secondary');self.release_check_button.clicked.connect(lambda:self.check_release(True));update_actions.addWidget(self.release_check_button)
  self.release_install_button=QPushButton('다운로드 후 업데이트');self.release_install_button.setObjectName('action');self.release_install_button.setEnabled(False);self.release_install_button.clicked.connect(lambda:self.download_release(True));update_actions.addWidget(self.release_install_button);updates.addLayout(update_actions)
  self.release_notes_button=QPushButton('변경 내용 보기');self.release_notes_button.setObjectName('secondary');self.release_notes_button.setEnabled(False);self.release_notes_button.clicked.connect(self.open_release_notes);updates.addWidget(self.release_notes_button);updates.addStretch()
  self._release_check_inflight=False;self._release_download_inflight=False;self._release_installing=False;self._release_candidate=None;self._release_ready=None;self._release_notified='';self._saved_settings={}
  self.bridge.release_event.connect(self.release_event);self.bridge.release_progress.connect(self.release_download_progress)
  self._release_wait_timer=QTimer(self);self._release_wait_timer.setInterval(1000);self._release_wait_timer.timeout.connect(self.install_ready_release)
  self._engine_dialog=None
  self.load(); self.update_variants(); self.refresh(); self.update_engine_label()
  self.check_updates.toggled.connect(lambda checked:self.release_preferences_changed('check',checked));self.auto_install_updates.toggled.connect(lambda checked:self.release_preferences_changed('install',checked))
  for pair,box in self.model_choices.items():
   self.pack_select[pair].setCurrentIndex(self.pack_select[pair].findData(box.currentData()))
   self.pack_select[pair].currentIndexChanged.connect(lambda _,p=pair:self.sync_model_choice(p,True))
   box.currentIndexChanged.connect(lambda _,p=pair:self.sync_model_choice(p,False))
  for box in list(self.target.values())+[self.source,self.engine]: box.currentTextChanged.connect(self.config_changed)
  for box in self.model_choices.values():box.currentIndexChanged.connect(self.config_changed)
  icon_path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'stoom.ico'; icon=QIcon(str(icon_path)); self.setWindowIcon(icon)
  self.tray=QSystemTrayIcon(icon,self); menu=QMenu(); self.menu=menu; menu.addAction('설정',self.show_settings);menu.addAction('업데이트 확인',self.show_update_page); menu.addAction('종료',self.quit); self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.show_settings() if reason in (QSystemTrayIcon.ActivationReason.Trigger,QSystemTrayIcon.ActivationReason.DoubleClick) else None); self.tray.show()
  self.tray.setToolTip(f'STOOM Shift Translator {release_updates.VERSION} ({release_updates.BUILD})')
  self.tsf=tsf_bridge.Client(int(self.winId()));self._tsf_request=None
  self.bridge.tsf_captured.connect(self.tsf_captured);self.bridge.tsf_applied.connect(self.tsf_applied);self.bridge.tsf_status.connect(self.input_readiness.setText)
  self._update_request=update_control.UpdateRequest();self._update_timer=QTimer(self);self._update_timer.setInterval(150);self._update_timer.timeout.connect(self.check_update_request);self._update_timer.start()
  self.select_page(0); self.tap=Tap(self.bridge); self.tap.listener.start()
  if hasattr(self.tap,'mouse_listener'):self.tap.mouse_listener.start()
  QTimer.singleShot(0,self.begin_engine_preflight)
  threading.Thread(target=lambda:self.bridge.tsf_status.emit(tsf_bridge.activate_installed()),daemon=True).start()
  self._release_start_timer=QTimer(self);self._release_start_timer.setSingleShot(True);self._release_start_timer.timeout.connect(lambda:self.check_release(False));self._release_start_timer.start(15000)
  self._release_timer=QTimer(self);self._release_timer.setInterval(6*60*60*1000);self._release_timer.timeout.connect(lambda:self.check_release(False));self._release_timer.start()
  _input_record(self,'app.ready.v'+release_updates.VERSION+'.b'+release_updates.BUILD)
 def check_update_request(self):
  if self._update_request.requested() and not self.busy and not self.downloading and not getattr(self,'_keyboard_workers',0):self.quit()
 def select_page(self,index):
  self.stack.setCurrentIndex(index)
  for i,b in enumerate(self.nav): b.setChecked(i==index)
 def show_settings(self):
  if self.isMinimized():self.showNormal()
  else:self.show()
  self.raise_();self.activateWindow()
 def show_update_page(self):
  self.select_page(3);self.show_settings();self.check_release(True)
 def open_release_notes(self):
  if self._release_candidate:QDesktopServices.openUrl(QUrl(self._release_candidate.url))
 def release_preferences_changed(self,which,checked):
  if which=='install' and checked and not self.check_updates.isChecked():
   self.check_updates.blockSignals(True);self.check_updates.setChecked(True);self.check_updates.blockSignals(False)
  if which=='check' and not checked:
   self.auto_install_updates.blockSignals(True);self.auto_install_updates.setChecked(False);self.auto_install_updates.blockSignals(False)
  self.save()
  if self._quitting:return
  if self.auto_install_updates.isChecked():
   if self._release_ready:self.install_ready_release()
   elif self._release_candidate:self.download_release(False)
   else:self.check_release(False)
  elif self._release_ready and not self._release_ready['manual']:
   self._release_wait_timer.stop();self.release_status.setText('업데이트를 내려받았습니다. 자동 설치가 꺼져 있어 설치하지 않았습니다.');self.release_install_button.setEnabled(True)
 def check_release(self,manual=False):
  if self._quitting or self._release_check_inflight or self._release_download_inflight or self._release_installing:return
  if not manual and not self.check_updates.isChecked():return
  self._release_check_inflight=True;self.release_check_button.setEnabled(False);self.release_install_button.setEnabled(False);self.release_status.setText('새 버전 확인 중…')
  def worker():
   if self._quitting:return
   try:event={'kind':'checked','manual':manual,'release':release_updates.check_latest(current_version=release_updates.VERSION),'error':''}
   except Exception as error:event={'kind':'checked','manual':manual,'release':None,'error':str(error)}
   if not self._quitting:self.bridge.release_event.emit(event)
  threading.Thread(target=worker,daemon=True).start()
 def download_release(self,manual=False):
  if self._quitting or self._release_check_inflight or self._release_download_inflight or self._release_installing:return
  if not manual and not(self.check_updates.isChecked() and self.auto_install_updates.isChecked()):return
  release=self._release_candidate
  if release is None:return
  if self._release_ready and self._release_ready['release'].tag==release.tag:
   if manual:self._release_ready['manual']=True
   self.install_ready_release();return
  self._release_download_inflight=True;self.release_check_button.setEnabled(False);self.release_install_button.setEnabled(False);self.release_progress.setRange(0,0);self.release_progress.show();self.release_status.setText(f'{release.version} 다운로드 중…')
  def worker():
   if self._quitting:return
   def progress(done,total):
    if not self._quitting:self.bridge.release_progress.emit((release.tag,done,total))
   try:event={'kind':'downloaded','release':release,'manual':manual,'path':release_updates.download_verified(release,APP/'updates',progress=progress),'error':''}
   except Exception as error:event={'kind':'downloaded','release':release,'manual':manual,'path':None,'error':str(error)}
   if not self._quitting:self.bridge.release_event.emit(event)
  threading.Thread(target=worker,daemon=True).start()
 def release_download_progress(self,payload):
  if self._quitting or not self._release_download_inflight:return
  tag,done,total=payload
  if not self._release_candidate or self._release_candidate.tag!=tag:return
  if total>0:self.release_progress.setRange(0,100);self.release_progress.setValue(min(100,max(0,round(done*100/total))))
  self.release_status.setText(f'업데이트 다운로드 중 · {done/1048576:.1f} / {total/1048576:.1f} MiB')
 def release_event(self,event):
  if self._quitting:return
  kind=event['kind']
  if kind=='checked':
   self._release_check_inflight=False
   if self._release_installing:return
   self.release_check_button.setEnabled(True)
   if event['error']:
    self.release_status.setText('새 버전 확인 실패: '+event['error']);self.release_install_button.setEnabled(self._release_candidate is not None)
    if self._release_ready:self.install_ready_release()
    return
   release=event['release'];self._release_candidate=release
   if release is None:
    self._release_ready=None;self._release_wait_timer.stop();self.release_install_button.setEnabled(False);self.release_notes_button.setEnabled(False);self.release_status.setText('새 업데이트가 없습니다.');return
   if self._release_ready and self._release_ready['release'].tag!=release.tag:self._release_ready=None;self._release_wait_timer.stop()
   self.release_status.setText(f'새 버전 {release.version}을 사용할 수 있습니다.');self.release_install_button.setEnabled(True);self.release_notes_button.setEnabled(True)
   if self._release_notified!=release.tag and(event['manual'] or self.check_updates.isChecked()):
    self._release_notified=release.tag;self.save();self.tray.showMessage('STOOM 업데이트',f'새 버전 {release.version}이 있습니다. 설정의 업데이트에서 설치할 수 있습니다.',QSystemTrayIcon.MessageIcon.Information,4000)
   if self._release_ready:self.install_ready_release()
   elif self.auto_install_updates.isChecked() and self.check_updates.isChecked():self.download_release(False)
  elif kind=='downloaded':
   self._release_download_inflight=False;self.release_check_button.setEnabled(True);self.release_install_button.setEnabled(True);self.release_progress.hide()
   if event['error']:self.release_status.setText('업데이트 다운로드 실패: '+event['error']);return
   self._release_ready={'release':event['release'],'path':event['path'],'manual':event['manual']};self.release_install_button.setText('다운로드한 업데이트 설치')
   self.install_ready_release()
  elif kind=='launched':
   if event['error']:
    self._release_installing=False;self.check_updates.setEnabled(True);self.auto_install_updates.setEnabled(True);self.release_check_button.setEnabled(True);self.release_install_button.setEnabled(True);self.release_status.setText('업데이트 설치를 시작하지 못했습니다: '+event['error'])
   elif event.get('package_kind')=='msi':
    self.release_status.setText('MSI 업데이트를 위해 번역기를 종료합니다. 설치 후 새 버전을 실행하세요.')
    self.quit()
   else:self.release_status.setText('설치 프로그램을 실행했습니다. 업데이트 요청을 기다리고 있습니다.')
  elif kind=='installer_exited':
   self._release_installing=False;self.check_updates.setEnabled(True);self.auto_install_updates.setEnabled(True);self.release_check_button.setEnabled(True);self.release_install_button.setEnabled(True)
   self.release_status.setText('설치 프로그램이 종료되었습니다. 업데이트가 완료되었다면 새 버전을 실행하세요.' if event['code']==0 else '업데이트가 완료되지 않았습니다. 다시 설치할 수 있습니다.')
 def release_idle(self):
  return not(self.busy or self.downloading or self.engine_initializing or self._clipboard_lease is not None or self._pending_input is not None or getattr(self,'_tsf_request',None) is not None or getattr(self,'_keyboard_workers',0))
 def install_ready_release(self):
  if self._quitting or self._release_installing or not self._release_ready:return
  ready=self._release_ready
  if not ready['manual'] and not(self.check_updates.isChecked() and self.auto_install_updates.isChecked()):
   self._release_wait_timer.stop();self.release_status.setText('업데이트를 내려받았습니다. 자동 설치가 꺼져 있어 설치하지 않았습니다.');return
  if self._release_check_inflight or self._release_download_inflight:
   self._release_wait_timer.start();return
  if not self.release_idle():
   self.release_status.setText('업데이트 준비 완료 · 번역과 언어팩 작업이 끝나면 설치합니다.');self._release_wait_timer.start();return
  self._release_wait_timer.stop();self._release_installing=True;self.check_updates.setEnabled(False);self.auto_install_updates.setEnabled(False);self.release_check_button.setEnabled(False);self.release_install_button.setEnabled(False);self.release_status.setText('업데이트 파일 확인 후 설치를 시작합니다…')
  def worker():
   if self._quitting:return
   try:
    # Revalidation and process creation can perform disk IO. Keep both off Qt.
    process=release_updates.launch_installer(ready['path'])
    if not self._quitting:self.bridge.release_event.emit({'kind':'launched','error':'','package_kind':Path(ready['path']).suffix.lower().lstrip('.')})
    code=process.wait()
    if not self._quitting:self.bridge.release_event.emit({'kind':'installer_exited','code':code})
   except Exception as error:
    if not self._quitting:self.bridge.release_event.emit({'kind':'launched','error':str(error)})
  threading.Thread(target=worker,daemon=True).start()
 def engine_configuration(self):
  return (self.engine.currentText(),self.source.currentText(),tuple(self.target[k].currentText() for k in ('shift','ctrl')),self.external_path,
          tuple((pair,box.currentData()) for pair,box in getattr(self,'model_choices',{}).items()))
 def begin_engine_preflight(self):
  self.engine_initializing=True
  configuration=self.engine_configuration()
  self.engine_readiness.setText('번역 엔진 준비 중…')
  self.pack_engine_status.setText('번역 엔진 준비 중… 잠시 기다려 주세요.')
  engine,source,targets,external_path,variants=configuration
  if engine=='사용자 외부 엔진':
   self.engine_preflight_done((configuration,None,'사용자 엔진은 첫 번역 시 실행 상태를 확인합니다.'))
   return
  enabled=[LANGS[t] for t in targets if t in LANGS]
  if not enabled:
   self.engine_preflight_done((configuration,None,'사용할 번역 단축키를 설정하세요.'))
   return
  source_code='auto' if source=='자동' else LANGS.get(source,'auto')
  try: probes=engine_readiness.choose_probes(source_code,enabled,path_for)
  except ValueError:
   self.engine_preflight_done((configuration,False,'설정된 번역 방향과 언어팩을 확인하세요.'))
   return
  def worker():
   try:
    for src,dst in probes: engine_readiness.warm(src,dst,translate)
    self.bridge.startup.emit((configuration,True,''))
   except Exception:
    self.bridge.startup.emit((configuration,False,'번역 엔진을 시작하지 못했습니다. 언어팩과 설정을 확인하세요.'))
  threading.Thread(target=worker,daemon=True).start()
 def engine_preflight_done(self,result):
  configuration,ready,detail=result
  if configuration!=self.engine_configuration():
   QTimer.singleShot(0,self.begin_engine_preflight); return
  self.engine_initializing=False
  if ready is True:
   self.engine_readiness.setText('번역 엔진 준비 완료')
   self.pack_engine_status.setText('번역 엔진 준비 완료')
   self.tray.showMessage('STOOM','번역 엔진 준비가 완료되었습니다.',QSystemTrayIcon.MessageIcon.Information,3000)
  else:
   self.engine_readiness.setText(detail)
   self.pack_engine_status.setText(detail)
   if ready is False:self.tray.showMessage('STOOM 엔진 준비 실패',detail,QSystemTrayIcon.MessageIcon.Warning,4000)
 def load(self):
  try:
   d=json.loads((APP/'settings.json').read_text(encoding='utf-8'))
   if not isinstance(d,dict):return
   self._saved_settings=d.copy()
   for k in self.target: self.target[k].setCurrentText(d.get(k,self.target[k].currentText()))
   self.source.setCurrentText(d.get('source','자동')); self.external_path=d.get('external_path',''); self.engine.setCurrentText(d.get('engine','기본 오프라인 엔진'))
   for pair,box in self.model_choices.items():
    models=d.get('models',{});models=models if isinstance(models,dict) else {}
    index=box.findData(models.get(pair,default_model(pair)))
    box.setCurrentIndex(index if index>=0 else box.findData(default_model(pair)))
   self.check_updates.setChecked(d.get('check_updates',True) is not False);self.auto_install_updates.setChecked(d.get('auto_install_updates',False) is True and self.check_updates.isChecked())
   self._release_notified=d.get('notified_release','') if isinstance(d.get('notified_release',''),str) else ''
  except (OSError,ValueError): pass
 def save(self,*args):
  settings={**getattr(self,'_saved_settings',{}),**{k:v.currentText() for k,v in self.target.items()},'source':self.source.currentText(),'engine':self.engine.currentText(),'external_path':self.external_path,'models':{pair:box.currentData() for pair,box in self.model_choices.items()}}
  if hasattr(self,'check_updates'):settings.update(check_updates=self.check_updates.isChecked(),auto_install_updates=self.auto_install_updates.isChecked(),notified_release=self._release_notified)
  temporary=APP/'settings.json.tmp';temporary.write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8');temporary.replace(APP/'settings.json');self._saved_settings=settings
 def update_variants(self):
  VARIANTS.clear();VARIANTS.update({pair:box.currentData() for pair,box in self.model_choices.items()})
 def sync_model_choice(self,pair,from_pack):
  source=self.pack_select[pair] if from_pack else self.model_choices[pair]
  target=self.model_choices[pair] if from_pack else self.pack_select[pair]
  index=target.findData(source.currentData())
  if index>=0 and target.currentIndex()!=index:target.setCurrentIndex(index)
 def config_changed(self,*args):
  self.update_variants();self.save()
  if not self.engine_initializing:
   self.engine_initializing=True;self.pack_engine_status.setText('선택한 번역 엔진을 준비하고 있습니다…');QTimer.singleShot(0,self.begin_engine_preflight)
 def choose_engine(self):
  if self._engine_dialog is not None:
   self._engine_dialog.raise_(); self._engine_dialog.activateWindow(); return
  dialog=QFileDialog(self,'사용자 번역 엔진 선택')
  dialog.setOption(QFileDialog.Option.DontUseNativeDialog,True)
  dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
  dialog.setNameFilter('Windows 실행 파일 (*.exe)')
  dialog.fileSelected.connect(self.engine_selected)
  dialog.finished.connect(self.engine_dialog_closed)
  self._engine_dialog=dialog
  dialog.open()
 def engine_selected(self,path):
  self.external_path=path; self.update_engine_label(); self.engine.setCurrentText('사용자 외부 엔진'); self.save()
 def update_engine_label(self):
  self.engine_path_label.setText('선택된 엔진: '+self.external_path if self.external_path else '선택된 외부 엔진 없음')
 def engine_dialog_closed(self,result):
  dialog=self._engine_dialog; self._engine_dialog=None
  if dialog is not None: dialog.deleteLater()
 def refresh(self):
  for box in self.pack_select.values():
   for i in range(box.count()):
    k=box.itemData(i);box.setItemText(i,model_packs.CATALOG[k].label+(' · 설치됨' if pack_installed(k) else ' · 미설치'))
  for box in self.model_choices.values():
   for i in range(box.count()):
    k=box.itemData(i);box.setItemText(i,model_packs.CATALOG[k].label+(' · 설치됨' if pack_installed(k) else ' · 미설치'))
 def download(self):
  if self.downloading or getattr(self,'_release_installing',False): return
  chosen=[self.pack_select[k].currentData() if hasattr(self,'pack_select') else k for k,b in self.checks.items() if b.isChecked()]
  if not chosen: self.status.setText('먼저 언어팩을 선택하세요.'); return
  self.downloading=True; self.status.setText('언어팩 다운로드 중입니다. 시간이 걸릴 수 있습니다.')
  if hasattr(self,'progress'):
   self._download_started=time.monotonic();self.progress.setRange(0,0);self.progress.show();self.progress_time.show();self.update_download_time();self.progress_timer.start();self.download_button.setEnabled(False);self.download_button.setText('설치 중…')
  def worker():
   try:
    for k in chosen:
     if not pack_installed(k): install_pack(k,progress=lambda msg,p=self.pack_labels[k]:self.bridge.download_progress.emit(p+' · '+msg))
    self.bridge.download_done.emit('언어팩을 확인했습니다. 설치된 항목은 다시 받지 않았습니다.')
   except Exception as e: self.bridge.download_done.emit('언어팩 설치 실패: '+str(e))
  threading.Thread(target=worker,daemon=True).start()
 def download_done(self,s):
  self.downloading=False; self.status.setText(s); self.refresh()
  if hasattr(self,'progress'):
   self.progress_timer.stop();self.progress.hide();self.progress_time.hide();self.download_button.setEnabled(True);self.download_button.setText('선택한 언어팩 다운로드')
  if s.startswith('언어팩을 확인') and not self.engine_initializing:
   self.engine_initializing=True; QTimer.singleShot(0,self.begin_engine_preflight)
 def show_download_progress(self,message):
  self.status.setText(message)
  match=re.search(r'다운로드\s+(\d+)\s*/\s*(\d+)\s*MiB',message)
  if match and int(match.group(2)):
   self.progress.setRange(0,100);self.progress.setValue(min(100,round(100*int(match.group(1))/int(match.group(2)))))
  else:self.progress.setRange(0,0)
 def update_download_time(self):
  elapsed=max(0,int(time.monotonic()-self._download_started))
  self.progress_time.setText(f'진행 중 · {elapsed//60}분 {elapsed%60}초 경과  |  완료될 때까지 기다려 주세요.')
 def run_translation(self,gesture):
  key,revision,started=gesture if isinstance(gesture,tuple) else (gesture,self.tap.activity_snapshot()[0],time.monotonic())
  self._input_job_counter=getattr(self,'_input_job_counter',0)+1;job=self._input_job_counter
  _input_record(self,'gesture.received',job=job,revision=revision)
  ignored=''
  if self._quitting or getattr(self,'_quit_requested',False):ignored='shutdown'
  elif getattr(self,'_release_installing',False):ignored='updating'
  elif self.busy or getattr(self,'_keyboard_workers',0):ignored='busy'
  elif self.isActiveWindow():ignored='settings'
  elif self.target[key].currentText()=='사용 안 함':ignored='disabled'
  if ignored:
   _input_record(self,'gesture.ignored.'+ignored,job=job,revision=revision);return
  if self.engine_initializing:
   _input_record(self,'gesture.ignored.preparing',job=job,revision=revision,error_message='번역 엔진을 준비하고 있습니다.')
   if not self._startup_wait_notified:
    self._startup_wait_notified=True
    self.tray.showMessage('STOOM','번역 엔진을 준비하고 있습니다.',QSystemTrayIcon.MessageIcon.Information,2000)
   return
  try:
   # Carry the hook's revision/time through the Qt queue: text typed after
   # the gesture must not silently become part of this request.
   current_revision=self.tap.activity_snapshot()[0]
   if current_revision!=revision:
    _input_record(self,'gesture.ignored.input',job=job,revision=revision,current_revision=current_revision,cause=_input_activity_cause(self));return
   self._input_active_job=job
   native_focus=focus_guard.capture()
   if not focus_guard.same_foreground(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 취소했습니다.')
   self.begin_keyboard_capture(key,revision,started,native_focus)
  except Exception as e:self.error(str(e))
 def begin_keyboard_capture(self,key,revision,started,focus):
  if getattr(self,'_input_active_job',None) is None:
   self._input_job_counter=getattr(self,'_input_job_counter',0)+1;self._input_active_job=self._input_job_counter
  request={'key':key,'revision':revision,'focus':focus,'configuration':self.engine_configuration(),'job':self._input_active_job,'started':started}
  self._keyboard_request=request;self.busy=True
  _input_record(self,'capture.requested',job=request['job'],revision=revision,focus=focus)
  self._keyboard_workers=getattr(self,'_keyboard_workers',0)+1
  QTimer.singleShot(4000,lambda:self.keyboard_capture_timeout(request))
  self.input_readiness.setText('현재 입력창 · 선택·복사 확인 중')
  def worker():
   try:
    activity=lambda:(-1,0.0) if self._quitting or getattr(self,'_quit_requested',False) or self._keyboard_request is not request else self.tap.activity_snapshot()
    env=keyboard_access.Windows(focus,activity,keyboard_safety)
    if env is not None:env.activity_cause=lambda:_input_activity_cause(self)
    report=lambda phase,**details:_input_record(self,phase,job=request['job'],**details)
    driver=keyboard_access.Driver(env,report=report)
    # Selection/navigation can commit composition without modifying the text.
    # Some editors do not copy a lone space, so it cannot be a prerequisite.
    snapshot=driver.capture(revision,commit_space=False)
    _input_record(self,'capture.completed',job=request['job'],revision=revision,source_chars=len(snapshot.text),duration_ms=(time.monotonic()-started)*1000)
    outcome=(snapshot,'')
   except Exception as error:
    message=str(error)
    _input_record(self,'capture.failed',job=request['job'],revision=revision,cause=_input_activity_cause(self,message),error_message=_input_error_message(message))
    outcome=(None,message)
   finally:self._keyboard_workers-=1
   self.bridge.keyboard_captured.emit((request,outcome))
  threading.Thread(target=worker,daemon=True).start()
 def keyboard_capture_timeout(self,request):
  if not self._quitting and self._keyboard_request is request:
   self.error('입력창의 응답 확인 시간이 초과되었습니다. 다시 시도할 수 있습니다.')
 def keyboard_captured(self,payload):
  request,(snapshot,error)=payload
  if self._quitting or self._keyboard_request is not request:
   _input_record(self,'capture.dropped.stale',job=request.get('job'),revision=request['revision'],cause='shutdown' if self._quitting else 'cancel');return
  if error:self.error(error);return
  current_revision=self.tap.activity_snapshot()[0]
  reason='';cause='unknown'
  if request['configuration']!=self.engine_configuration():reason='configuration';cause='configuration'
  elif current_revision!=request['revision']:reason='input';cause=_input_activity_cause(self)
  elif not focus_guard.same_foreground(request['focus']):reason='focus';cause='focus'
  if reason:
   _input_record(self,'capture.dropped.'+reason,job=request.get('job'),revision=request['revision'],current_revision=current_revision,focus=request['focus'],current_focus=_input_current_focus(),cause=cause)
   self._keyboard_request=None;self.busy=False;return
  _input_record(self,'capture.accepted',job=request.get('job'),revision=request['revision'],source_chars=len(snapshot.text))
  self._keyboard_request=None
  self.start_translation(request['key'],request['focus'],(),snapshot.text,('keyboard',snapshot))
 def keyboard_applied(self,result):
  if self._quitting:return
  success,message=result;self.busy=False
  if success:self.input_readiness.setText(message)
  else:self.error(message)
 def begin_legacy_capture(self,key,revision,started,native_focus):
  """Optional provider diagnostic route; the default shortcut uses keys."""
  self.busy=True
  request={'key':key,'focus':native_focus,'rid':None,'configuration':self.engine_configuration(),
           'gate':input_settle.Settler(started,revision,quiet_seconds=.12,stable_seconds=.08,min_delay=.04),
           'modifier_activity':0.0,'last_error':''}
  self._pending_input=request
  QTimer.singleShot(40,lambda:self.poll_input(request))
 def cancel_pending_input(self):
  if getattr(self,'_keyboard_request',None) is not None:
   self._keyboard_request=None;self.busy=False
  if self._pending_input is not None:
   self._pending_input=None; self.busy=False
  if getattr(self,'_tsf_request',None) is not None:
   self._tsf_request=None;self.busy=False
 def begin_tsf_capture(self,key,revision,started,focus,server):
  request={'key':key,'revision':revision,'started':started,'focus':focus,'server':server,'configuration':self.engine_configuration()}
  self._tsf_request=request;self.busy=True
  def worker():
   outcome=None
   try:
    deadline=time.monotonic()+1.2
    while time.monotonic()<deadline:
     current,last_activity=self.tap.activity_snapshot()
     if current!=revision or self._tsf_request is not request or not focus_guard.unchanged(focus):
      outcome=('cancel',None);break
     if time.monotonic()-last_activity<.12:
      time.sleep(.025);continue
     try:
      snapshot=self.tsf.capture(server,focus);outcome=('ready',snapshot);break
     except tsf_bridge.Pending:
      time.sleep(.04)
    if outcome is None:outcome=('error','입력 조합이 아직 진행 중입니다. 입력을 마친 뒤 다시 시도하세요.')
   except tsf_bridge.Unavailable:outcome=('fallback',None)
   except Exception as e:outcome=('error',str(e))
   self.bridge.tsf_captured.emit((request,outcome))
  threading.Thread(target=worker,daemon=True).start()
 def tsf_captured(self,payload):
  request,(kind,value)=payload
  if self._quitting or self._tsf_request is not request:return
  self._tsf_request=None
  if kind=='cancel' or request['configuration']!=self.engine_configuration() or self.tap.activity_snapshot()[0]!=request['revision'] or not focus_guard.unchanged(request['focus']):
   self.busy=False;return
  if kind=='error':self.error(value);return
  if kind=='fallback':
   self.begin_keyboard_capture(request['key'],request['revision'],request['started'],request['focus']);return
  self.input_readiness.setText('현재 입력창 · TSF 직접 교체')
  self.start_translation(request['key'],request['focus'],(),value.text,('tsf',value))
 def tsf_applied(self,result):
  if self._quitting:return
  success,message=result;self.busy=False
  if success:
   self.input_readiness.setText(message)
  else:self.error(message)
 def poll_input(self,request):
  if self._quitting or self._pending_input is not request:return
  try:
   if request['configuration']!=self.engine_configuration() or not focus_guard.unchanged(request['focus']):
    self.cancel_pending_input(); return
   now=time.monotonic();revision,last_activity=self.tap.activity_snapshot()
   if any(ctypes.windll.user32.GetAsyncKeyState(k) & 0x8000 for k in (0x10,0x11,0x12,0x5b,0x5c)):
    request['modifier_activity']=now
   last_activity=max(last_activity,request['modifier_activity'])
   decision=request['gate'].observe(now,revision,last_activity)
   if decision=='sample':
    try:
     rid,text,context=capture_input()
     if (request['rid'] is not None and rid!=request['rid']) or not focus_guard.unchanged(request['focus']):
      self.cancel_pending_input(); return
     request['rid']=rid
     fingerprint=(rid,context[0],context[1].fingerprint() if context[0]=='range' else range_access.normalize(text))
     revision,last_key_activity=self.tap.activity_snapshot()
     decision=request['gate'].observe(time.monotonic(),revision,max(last_key_activity,request['modifier_activity']),fingerprint)
    except Exception as e:
     request['last_error']=str(e)
     # A temporary unavailable range is never a stable valid sample.
     request['gate'].discard_sample()
     decision='wait'
    if decision=='ready':
     self._pending_input=None
     self.start_translation(request['key'],request['focus'],rid,text,context)
     return
   if decision=='cancel':
    self.cancel_pending_input(); return
   if decision=='timeout':
    self.error(request['last_error'] or '입력 내용이 아직 안정되지 않았습니다. 입력을 마친 뒤 다시 시도해 주세요.'); return
   QTimer.singleShot(40,lambda:self.poll_input(request))
  except Exception as e:self.error(str(e))
 def start_translation(self,key,native_focus,rid,text,context):
  job=getattr(self,'_input_active_job',None)
  try:
   hwnd=native_focus.foreground
   current=focus_guard.same_foreground(native_focus) if context[0]=='keyboard' else focus_guard.unchanged(native_focus)
   if not current:raise ValueError('키보드 입력 위치가 바뀌어 취소했습니다.')
   if not text.strip(): raise ValueError('현재 입력 영역에 번역할 문장이 없습니다.')
   src=guess(text) if self.source.currentText()=='자동' else LANGS[self.source.currentText()]
   dst=LANGS[self.target[key].currentText()]
   use_external=self.engine.currentText()=='사용자 외부 엔진'; external_path=self.external_path
   if use_external:
    if not external_path or not Path(external_path).is_file(): raise ValueError('사용자 번역 엔진 실행 파일을 선택하세요.')
   else: route=path_for(src,dst)
   self.busy=True
   model_ids=['external'] if use_external else list(route)
   _input_record(self,'model.started',job=job,focus=native_focus,source_chars=len(text),model_ids=model_ids)
   def worker():
    started=time.monotonic()
    try:
     result=translate_external(external_path,text,src,dst) if use_external else translate_route(text,route)
     _input_record(self,'model.completed',job=job,source_chars=len(text),output_chars=len(result),same_output=result==text,model_ids=model_ids,duration_ms=(time.monotonic()-started)*1000)
     self.bridge.done.emit((hwnd,rid,text,result,context,native_focus))
    except Exception:
     message='번역 엔진 실행 중 오류가 발생했습니다.'
     _input_record(self,'model.failed',job=job,source_chars=len(text),model_ids=model_ids,duration_ms=(time.monotonic()-started)*1000,error_message=message)
     self.bridge.error.emit(message)
   threading.Thread(target=worker,daemon=True).start()
  except Exception as e: self.error(str(e))
 def apply_result(self,payload):
  if self._quitting:return
  try:
   hwnd,rid,old,new,context,native_focus=payload
   if context[0]=='keyboard':
    if not focus_guard.same_foreground(native_focus):raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   elif ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus):raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   if context[0]=='keyboard':
    job=getattr(self,'_input_active_job',None)
    _input_record(self,'paste.requested',job=job,focus=native_focus,source_chars=len(old),output_chars=len(new),same_output=old==new)
    self._keyboard_workers=getattr(self,'_keyboard_workers',0)+1
    def worker():
     try:
      activity=lambda:(-1,0.0) if self._quitting or getattr(self,'_quit_requested',False) else self.tap.activity_snapshot()
      env=keyboard_access.Windows(native_focus,activity,keyboard_safety)
      if env is not None:env.activity_cause=lambda:_input_activity_cause(self)
      report=lambda phase,**details:_input_record(self,phase,job=job,**details)
      message=keyboard_access.Driver(env,report=report).apply(context[1],new)
      _input_record(self,'paste.delivery.completed',job=job,output_chars=len(new))
      self.bridge.keyboard_applied.emit((True,message))
     except Exception as error:
      message=str(error)
      _input_record(self,'paste.delivery.failed',job=job,cause=_input_activity_cause(self,message),error_message=_input_error_message(message))
      self.bridge.keyboard_applied.emit((False,message))
     finally:self._keyboard_workers-=1
    threading.Thread(target=worker,daemon=True).start();return
   if context[0]=='tsf':
    def worker():
     try:
      status=self.tsf.apply(native_focus,context[1],new)
      self.bridge.tsf_applied.emit((True,'TSF 교체 완료' if status==0 else 'TSF 교체 완료 · 커서 위치는 확인이 필요합니다.'))
     except Exception as e:self.bridge.tsf_applied.emit((False,str(e)))
    threading.Thread(target=worker,daemon=True).start();return
   if context[0]=='range':
    self.paste_range(hwnd,rid,context[1],new,20,native_focus)
    return
   current_rid,current,value=focused()
   if current_rid!=rid or current!=old: raise ValueError('입력창 또는 원문이 바뀌어 교체하지 않았습니다.')
   value.SetValue(new)
   QTimer.singleShot(100,lambda:self.verify_result(hwnd,rid,new,4))
  except Exception as e: self.error(str(e))
 def paste_range(self,hwnd,rid,snapshot,new,remaining,native_focus):
  lease=None
  try:
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.unchanged(snapshot,current_rid,wrapper.iface_text):
    raise ValueError('입력 위치 또는 원문이 바뀌어 교체하지 않았습니다.')
   # Wait for the gesture modifier to be released before sending Ctrl+V.
   if any(ctypes.windll.user32.GetAsyncKeyState(k) & 0x8000 for k in (0x10,0x11,0x12,0x5b,0x5c)):
    if remaining<=1: raise ValueError('단축키에서 손을 뗀 후 다시 시도해 주세요.')
    QTimer.singleShot(100,lambda:self.paste_range(hwnd,rid,snapshot,new,remaining-1,native_focus)); return
   lease=clipboard_lease.ClipboardLease(); lease.put(new); self._clipboard_lease=lease
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.unchanged(snapshot,current_rid,wrapper.iface_text): raise ValueError('입력 위치 또는 원문이 바뀌어 교체하지 않았습니다.')
   kb=keyboard.Controller()
   if snapshot.document_mode:
    fresh=range_access.capture(current_rid,wrapper.iface_text,True)
    fresh.target.Select()
   else:
    with kb.pressed(keyboard.Key.ctrl): kb.press('a'); kb.release('a')
   selected_rid,selected_info,selected_wrapper=focused_element()
   if selected_rid!=rid or not focus_guard.unchanged(native_focus): raise ValueError('입력창이 바뀌어 교체하지 않았습니다.')
   # Copy is non-destructive. Verify the real selected text before pasting;
   # some browser providers report UIA selection that is visually collapsed.
   with kb.pressed(keyboard.Key.ctrl): kb.press('c'); kb.release('c')
   QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,12))
  except Exception as e:
   if lease:
    try: lease.restore()
    except Exception: pass
   self._clipboard_lease=None
   self.error(str(e))
 def confirm_range_copy(self,hwnd,rid,snapshot,new,lease,native_focus,remaining,verified=False):
  try:
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text):
    if remaining<=1:raise ValueError('선택한 원문과 위치를 확인하지 못해 교체하지 않았습니다.')
    QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,remaining-1,verified));return
   result='matched' if verified else lease.confirm_selection_and_put(snapshot.text,new)
   if result=='pending':
    if remaining<=1: raise ValueError('선택된 글을 복사해 확인하지 못했습니다.')
    QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,remaining-1)); return
   if result!='matched': raise ValueError('실제 선택된 글이 번역 대상과 달라 교체하지 않았습니다.')
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text):
    if remaining<=1:raise ValueError('선택한 원문과 위치를 확인하지 못해 교체하지 않았습니다.')
    QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,remaining-1,True));return
   kb=keyboard.Controller()
   # Ordinary fields are reselected with their keyboard operation. A document
   # keeps the selection already verified by Ctrl+C; do not reuse a live range
   # that the provider may have moved after the deliberate selection change.
   if not snapshot.document_mode:
    with kb.pressed(keyboard.Key.ctrl): kb.press('a'); kb.release('a')
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text):
    if remaining<=1:raise ValueError('선택한 원문과 위치를 확인하지 못해 교체하지 않았습니다.')
    QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,remaining-1,True));return
   with kb.pressed(keyboard.Key.ctrl): kb.press('v'); kb.release('v')
   QTimer.singleShot(500,lambda:self.finish_range_paste(lease))
  except Exception as e:
   try: lease.restore()
   except Exception: pass
   self._clipboard_lease=None
   self.error(str(e))
 def finish_range_paste(self,lease):
  try:
   lease.restore()
   self._clipboard_lease=None; self.busy=False
  except Exception:
   self._clipboard_lease=None; self.busy=False
   self.error('번역문을 붙여넣었으나 이전 클립보드를 복원하지 못했습니다.')
 def verify_result(self,hwnd,rid,expected,remaining):
  try:
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd:
    self.busy=False; return
   current_rid,current,_=focused()
   if current_rid!=rid:
    self.busy=False; return
   def normalize(text):
    return unicodedata.normalize('NFC',text.replace('\r\n','\n').replace('\r','\n'))
   if normalize(current)==normalize(expected):
    move_caret_to_end(hwnd,rid); self.busy=False; return
   if remaining>1:
    QTimer.singleShot(100,lambda:self.verify_result(hwnd,rid,expected,remaining-1)); return
   self.busy=False
   self.error('번역문은 전달했지만 결과를 확인하지 못했습니다. 입력창을 확인해 주세요.')
  except Exception:
   self.busy=False
   self.error('번역문은 전달했지만 결과를 확인하지 못했습니다. 입력창을 확인해 주세요.')
 def error(self,msg):
  _input_record(self,'toast.error',error_message=_input_error_message(msg))
  self.cancel_pending_input(); self.busy=False; self.status.setText(msg); self.tray.showMessage('STOOM 번역 취소',msg)
 def closeEvent(self,event): event.ignore(); self.hide()
 def quit(self):
  if getattr(self,'_keyboard_workers',0):
   self._quit_requested=True;self._keyboard_request=None
   QTimer.singleShot(50,self.quit);return
  self._quitting=True; self.cancel_pending_input()
  for name in ('_release_start_timer','_release_timer','_release_wait_timer'):
   if hasattr(self,name):getattr(self,name).stop()
  if hasattr(self,'_update_timer'):self._update_timer.stop()
  if hasattr(self,'_update_request'):self._update_request.close()
  if self._clipboard_lease is not None:
   try:self._clipboard_lease.restore()
   except Exception:pass
   self._clipboard_lease=None
  self.tap.listener.stop()
  if hasattr(self.tap,'mouse_listener'):self.tap.mouse_listener.stop()
  self.tray.hide()
  _input_record(self,'app.shutdown',cause='shutdown')
  if getattr(self,'_input_trace',None) is not None:self._input_trace.close(timeout=1)
  QApplication.quit()

if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='--check-pack':
  import pack_diagnostics
  sys.exit(pack_diagnostics.run(sys.argv[2:],sys.modules[__name__]))
 windows_identity.set_taskbar_identity()
 if '--after-update' in sys.argv:
  deadline=time.monotonic()+15
  while update_control.installation_active() and time.monotonic()<deadline:time.sleep(.05)
 if update_control.installation_active():
  ctypes.windll.user32.MessageBoxW(None,'업데이트 중입니다. 설치 완료 후 실행하세요.','STOOM Shift Translator',0x40)
  sys.exit(0)
 handle=singleton.acquire()
 if not handle:
  if not singleton.show_existing():
   ctypes.windll.user32.MessageBoxW(None,'STOOM 번역기가 이미 실행 중이지만 설정 창을 찾지 못했습니다. 잠시 후 다시 시도하세요.','STOOM Shift Translator',0x40)
  sys.exit(0)
 try:
  threading.Thread(target=clipboard_lease.warmup,name='STOOM-clipboard-warmup',daemon=True).start()
  app=QApplication(sys.argv);app.setWindowIcon(QIcon(str(Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'stoom.ico')))
  app.setQuitOnLastWindowClosed(False); window=App(); window.show(); code=app.exec()
 finally:
  clipboard_lease.shutdown()
  singleton.release(handle)
 sys.exit(code)
