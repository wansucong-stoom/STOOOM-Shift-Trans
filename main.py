import os, sys, json, time, threading, hashlib, zipfile, urllib.request, tempfile, shutil, re, ctypes, subprocess, unicodedata, functools
import singleton
import range_access
import clipboard_lease
import chunking
import focus_guard
import engine_readiness
import input_settle
import model_packs
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QCheckBox, QSystemTrayIcon, QMenu, QMessageBox, QFileDialog, QStackedWidget, QFrame
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from pynput import keyboard
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
 selected=VARIANTS.get(direct,direct)
 if selected in model_packs.CATALOG and exists(selected): return [selected]
 if src!='en' and dst!='en':
  route=[VARIANTS.get(pair,pair) for pair in (src+'_en','en_'+dst)]
  if all(exists(k) for k in route): return route
 raise ValueError('필요한 언어팩이 없습니다. 설정에서 다운로드하세요.')

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
   tokens=sp.encode(part,out_type=str)
   result=tr.translate_batch([tokens],beam_size=4,max_decoding_length=256)[0].hypotheses[0]
   translated=sp.decode(result)
   if not translated.strip(): raise ValueError('일부 번역 결과가 비어 있어 교체하지 않습니다.')
   output.append(translated)
  text=''.join(output)
  if not text.strip(): raise ValueError('번역 결과가 비어 있어 교체하지 않습니다.')
 return text

def install_pack(k,progress=None):
 return model_packs.install(k,MODELS,progress=progress)

class Tap:
 def __init__(self,bridge):
  self.bridge=bridge; self.down=set(); self.last={}; self.used=set(); self.pending=set(); self.started={}; self._activity=(0,0.0)
  self.listener=keyboard.Listener(on_press=self.press,on_release=self.release)
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
  self.busy=False; self.downloading=False; self.external_path=''; self.engine_initializing=True; self._startup_wait_notified=False; self._clipboard_lease=None; self._pending_input=None; self._quitting=False
  root=QHBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
  sidebar=QFrame(); sidebar.setObjectName('sidebar'); sidebar.setFixedWidth(220); side=QVBoxLayout(sidebar); side.setContentsMargins(0,30,0,20); side.setSpacing(0)
  icon_path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'stoom.ico'
  brandrow=QHBoxLayout(); brandrow.setContentsMargins(20,0,12,0); brandicon=QLabel(); brandicon.setPixmap(QIcon(str(icon_path)).pixmap(32,32)); brandrow.addWidget(brandicon); brand=QLabel('STOOM'); brand.setStyleSheet('font-size: 16pt; font-weight: 700; color: #17394c;'); brandrow.addWidget(brand); brandrow.addStretch(); side.addLayout(brandrow)
  caption=QLabel('     Shift Translator'); caption.setStyleSheet('font-size: 9pt; color: #7b8790;'); side.addWidget(caption); side.addSpacing(34)
  self.stack=QStackedWidget(); self.nav=[]
  for i,name in enumerate(['단축키 설정','언어팩 관리','번역 엔진']):
   btn=QPushButton(name); btn.setObjectName('nav'); btn.setCheckable(True); btn.clicked.connect(lambda checked,idx=i:self.select_page(idx)); side.addWidget(btn); self.nav.append(btn)
  side.addStretch(); foot=QLabel('     v0.5  ·  실험판'); foot.setStyleSheet('color:#8a929b; font-size:9pt;'); side.addWidget(foot)
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
  packs=page('언어팩 관리','필요한 번역 방향만 선택해 내려받으세요. 번역은 설치 후 오프라인에서 실행됩니다.')
  self.checks={}; self.pack_select={}
  labels={'en_ja':'영어 → 일본어 · Argos','en_ko':'영어 → 한국어 · Argos','ja_en':'일본어 → 영어 · Argos','ko_en':'한국어 → 영어 · Argos',
          'ko_en_opus_big':'한국어 → 영어 · OPUS-MT Big','en_ko_opus_big':'영어 → 한국어 · OPUS-MT Big'}
  self.pack_labels=labels
  for pair,label in [('ko_en','한국어 → 영어'),('en_ko','영어 → 한국어'),('ja_en','일본어 → 영어'),('en_ja','영어 → 일본어')]:
   row=QHBoxLayout(); box=QCheckBox(label); box.setMinimumWidth(190); row.addWidget(box)
   options=QComboBox()
   for spec in model_packs.choices(*pair.split('_')): options.addItem(spec.label,spec.id)
   row.addWidget(options,1); packs.addLayout(row); self.checks[pair]=box; self.pack_select[pair]=options
  self.status=QLabel('각 방향에서 사용할 모델을 하나 선택하세요. 내려받을 방향은 체크합니다.\nArgos: 약 112~115 MiB · OPUS-MT Big: 약 741 MiB 다운로드 후 변환'); self.status.setStyleSheet('color:#7d8791;'); self.status.setWordWrap(True); packs.addSpacing(8); packs.addWidget(self.status)
  self.bridge.download_progress.connect(self.status.setText)
  row=QHBoxLayout(); row.addStretch(); button=QPushButton('선택한 언어팩 다운로드'); button.setObjectName('action'); button.clicked.connect(self.download); row.addWidget(button); packs.addLayout(row); packs.addStretch()
  enginepage=page('번역 엔진','기본 엔진 또는 호환되는 사용자 엔진을 선택합니다.')
  self.engine=QComboBox(); self.engine.addItems(['기본 오프라인 엔진','사용자 외부 엔진']); enginepage.addWidget(self.engine)
  self.model_choices={}
  for pair,label in [('ko_en','한국어 → 영어'),('en_ko','영어 → 한국어')]:
   row=QHBoxLayout();row.addWidget(QLabel(label));box=QComboBox()
   for spec in model_packs.choices(*pair.split('_')):box.addItem(spec.label,spec.id)
   row.addWidget(box);enginepage.addLayout(row);self.model_choices[pair]=box
  model_note=QLabel('방향마다 다른 모델을 선택할 수 있습니다. 미설치 모델은 언어팩 관리에서 먼저 받으세요. 영어↔일본어는 Argos를 사용합니다.\nOPUS-MT: University of Helsinki · CC-BY-4.0 · INT8 변환');model_note.setWordWrap(True);model_note.setStyleSheet('color:#7d8791;');enginepage.addWidget(model_note)
  warning=QLabel('외부 엔진에는 원문이 전달됩니다. 인터넷 사용 여부는 선택한 엔진에 따라 다릅니다.'); warning.setWordWrap(True); warning.setStyleSheet('color:#7d8791;'); enginepage.addWidget(warning)
  row=QHBoxLayout(); engine_btn=QPushButton('엔진 EXE 선택'); engine_btn.setObjectName('secondary'); engine_btn.clicked.connect(self.choose_engine); row.addWidget(engine_btn); row.addStretch(); enginepage.addLayout(row)
  self.engine_path_label=QLabel('선택된 외부 엔진 없음'); self.engine_path_label.setWordWrap(True); self.engine_path_label.setStyleSheet('color:#7d8791;'); enginepage.addWidget(self.engine_path_label); enginepage.addStretch()
  self._engine_dialog=None
  self.load(); self.update_variants(); self.refresh(); self.update_engine_label()
  for pair,box in self.model_choices.items():
   self.pack_select[pair].setCurrentIndex(self.pack_select[pair].findData(box.currentData()))
   self.pack_select[pair].currentIndexChanged.connect(lambda _,p=pair:self.sync_model_choice(p,True))
   box.currentIndexChanged.connect(lambda _,p=pair:self.sync_model_choice(p,False))
  for box in list(self.target.values())+[self.source,self.engine]: box.currentTextChanged.connect(self.config_changed)
  for box in self.model_choices.values():box.currentIndexChanged.connect(self.config_changed)
  icon_path=Path(getattr(sys,'_MEIPASS',Path(__file__).parent))/'stoom.ico'; icon=QIcon(str(icon_path)); self.setWindowIcon(icon)
  self.tray=QSystemTrayIcon(icon,self); menu=QMenu(); self.menu=menu; menu.addAction('설정',self.show); menu.addAction('종료',self.quit); self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason: self.show() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None); self.tray.show()
  self.select_page(0); self.tap=Tap(self.bridge); self.tap.listener.start(); QTimer.singleShot(0,self.begin_engine_preflight)
 def select_page(self,index):
  self.stack.setCurrentIndex(index)
  for i,b in enumerate(self.nav): b.setChecked(i==index)
 def engine_configuration(self):
  return (self.engine.currentText(),self.source.currentText(),tuple(self.target[k].currentText() for k in ('shift','ctrl')),self.external_path,
          tuple((pair,box.currentData()) for pair,box in getattr(self,'model_choices',{}).items()))
 def begin_engine_preflight(self):
  self.engine_initializing=True
  configuration=self.engine_configuration()
  self.engine_readiness.setText('번역 엔진 준비 중…')
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
   self.tray.showMessage('STOOM','번역 엔진 준비가 완료되었습니다.',QSystemTrayIcon.MessageIcon.Information,3000)
  else:
   self.engine_readiness.setText(detail)
   if ready is False:self.tray.showMessage('STOOM 엔진 준비 실패',detail,QSystemTrayIcon.MessageIcon.Warning,4000)
 def load(self):
  try:
   d=json.loads((APP/'settings.json').read_text(encoding='utf-8'))
   for k in self.target: self.target[k].setCurrentText(d.get(k,self.target[k].currentText()))
   self.source.setCurrentText(d.get('source','자동')); self.external_path=d.get('external_path',''); self.engine.setCurrentText(d.get('engine','기본 오프라인 엔진'))
   for pair,box in self.model_choices.items():
    index=box.findData(d.get('models',{}).get(pair,pair))
    if index>=0:box.setCurrentIndex(index)
  except (OSError,ValueError): pass
 def save(self,*args):
  (APP/'settings.json').write_text(json.dumps({**{k:v.currentText() for k,v in self.target.items()},'source':self.source.currentText(),'engine':self.engine.currentText(),'external_path':self.external_path,
                                           'models':{pair:box.currentData() for pair,box in self.model_choices.items()}},ensure_ascii=False),encoding='utf-8')
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
   self.engine_initializing=True;QTimer.singleShot(0,self.begin_engine_preflight)
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
  if self.downloading: return
  chosen=[self.pack_select[k].currentData() if hasattr(self,'pack_select') else k for k,b in self.checks.items() if b.isChecked()]
  if not chosen: self.status.setText('먼저 언어팩을 선택하세요.'); return
  self.downloading=True; self.status.setText('언어팩 다운로드 중입니다. 시간이 걸릴 수 있습니다.')
  def worker():
   try:
    for k in chosen:
     if not pack_installed(k): install_pack(k,progress=lambda msg,p=self.pack_labels[k]:self.bridge.download_progress.emit(p+' · '+msg))
    self.bridge.download_done.emit('언어팩을 확인했습니다. 설치된 항목은 다시 받지 않았습니다.')
   except Exception as e: self.bridge.download_done.emit('언어팩 설치 실패: '+str(e))
  threading.Thread(target=worker,daemon=True).start()
 def download_done(self,s):
  self.downloading=False; self.status.setText(s); self.refresh()
  if s.startswith('언어팩을 확인') and not self.engine_initializing:
   self.engine_initializing=True; QTimer.singleShot(0,self.begin_engine_preflight)
 def run_translation(self,gesture):
  key,revision,started=gesture if isinstance(gesture,tuple) else (gesture,self.tap.activity_snapshot()[0],time.monotonic())
  if self._quitting or self.busy or self.isActiveWindow() or self.target[key].currentText()=='사용 안 함': return
  if self.engine_initializing:
   if not self._startup_wait_notified:
    self._startup_wait_notified=True
    self.tray.showMessage('STOOM','번역 엔진을 준비하고 있습니다.',QSystemTrayIcon.MessageIcon.Information,2000)
   return
  try:
   # Carry the hook's revision/time through the Qt queue: text typed after
   # the gesture must not silently become part of this request.
   if self.tap.activity_snapshot()[0]!=revision:return
   native_focus=focus_guard.capture()
   if not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 취소했습니다.')
   self.busy=True
   request={'key':key,'focus':native_focus,'rid':None,'configuration':self.engine_configuration(),
            'gate':input_settle.Settler(started,revision,quiet_seconds=.12,stable_seconds=.08,min_delay=.04),
            'modifier_activity':0.0,'last_error':''}
   self._pending_input=request
   QTimer.singleShot(40,lambda:self.poll_input(request))
  except Exception as e:self.error(str(e))
 def cancel_pending_input(self):
  if self._pending_input is not None:
   self._pending_input=None; self.busy=False
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
  try:
   hwnd=native_focus.foreground
   if not focus_guard.unchanged(native_focus):raise ValueError('키보드 입력 위치가 바뀌어 취소했습니다.')
   if not text.strip(): raise ValueError('현재 입력 영역에 번역할 문장이 없습니다.')
   src=guess(text) if self.source.currentText()=='자동' else LANGS[self.source.currentText()]
   dst=LANGS[self.target[key].currentText()]
   use_external=self.engine.currentText()=='사용자 외부 엔진'; external_path=self.external_path
   if use_external:
    if not external_path or not Path(external_path).is_file(): raise ValueError('사용자 번역 엔진 실행 파일을 선택하세요.')
   else: route=path_for(src,dst)
   self.busy=True
   def worker():
    try: self.bridge.done.emit((hwnd,rid,text,translate_external(external_path,text,src,dst) if use_external else translate_route(text,route),context,native_focus))
    except Exception as e: self.bridge.error.emit(str(e))
   threading.Thread(target=worker,daemon=True).start()
  except Exception as e: self.error(str(e))
 def apply_result(self,payload):
  if self._quitting:return
  try:
   hwnd,rid,old,new,context,native_focus=payload
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
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
 def confirm_range_copy(self,hwnd,rid,snapshot,new,lease,native_focus,remaining):
  try:
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text): raise ValueError('입력창의 원문이 바뀌어 교체하지 않았습니다.')
   result=lease.confirm_selection_and_put(snapshot.text,new)
   if result=='pending':
    if remaining<=1: raise ValueError('선택된 글을 복사해 확인하지 못했습니다.')
    QTimer.singleShot(100,lambda:self.confirm_range_copy(hwnd,rid,snapshot,new,lease,native_focus,remaining-1)); return
   if result!='matched': raise ValueError('실제 선택된 글이 번역 대상과 달라 교체하지 않았습니다.')
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text): raise ValueError('입력창의 원문이 바뀌어 교체하지 않았습니다.')
   kb=keyboard.Controller()
   # Ordinary fields are reselected with their keyboard operation. A document
   # keeps the selection already verified by Ctrl+C; do not reuse a live range
   # that the provider may have moved after the deliberate selection change.
   if not snapshot.document_mode:
    with kb.pressed(keyboard.Key.ctrl): kb.press('a'); kb.release('a')
   if ctypes.windll.user32.GetForegroundWindow()!=hwnd or not focus_guard.unchanged(native_focus): raise ValueError('키보드 입력 위치가 바뀌어 교체하지 않았습니다.')
   current_rid,info,wrapper=focused_element()
   if not range_access.after_selection_source_matches(snapshot,current_rid,wrapper.iface_text): raise ValueError('입력창의 원문이 바뀌어 교체하지 않았습니다.')
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
  self.cancel_pending_input(); self.busy=False; self.status.setText(msg); self.tray.showMessage('STOOM 번역 취소',msg)
 def closeEvent(self,event): event.ignore(); self.hide()
 def quit(self):
  self._quitting=True; self.cancel_pending_input()
  if self._clipboard_lease is not None:
   try:self._clipboard_lease.restore()
   except Exception:pass
   self._clipboard_lease=None
  self.tap.listener.stop(); self.tray.hide(); QApplication.quit()

if __name__=='__main__':
 if len(sys.argv)>1 and sys.argv[1]=='--check-pack':
  import pack_diagnostics
  sys.exit(pack_diagnostics.run(sys.argv[2:],sys.modules[__name__]))
 handle=singleton.acquire()
 if not handle:
  ctypes.windll.user32.MessageBoxW(None,'STOOM 번역기가 이미 실행 중입니다. 작업 표시줄의 알림 영역에서 설정을 열 수 있습니다.','STOOM Shift Translator',0x40)
  sys.exit(0)
 try:
  app=QApplication(sys.argv); app.setQuitOnLastWindowClosed(False); window=App(); window.show(); code=app.exec()
 finally:
  singleton.release(handle)
 sys.exit(code)
