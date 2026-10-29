"""Bounded, private-pipe client for the clipboard STA helper process.

The GUI never receives COM pointers. Native failures in the helper become one
failed request, never an automatic replay of a clipboard write or paste.
"""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import uuid

REQUEST_SECONDS=3.0
MAX_FRAME=262144

class ClipboardWorkerError(RuntimeError):pass

def worker_command():
 if getattr(sys,'frozen',False):return [sys.executable,'--clipboard-worker']
 return [sys.executable,str(Path(__file__).with_name('main.py')),'--clipboard-worker']

class Broker:
 def __init__(self,command=None,timeout=REQUEST_SECONDS):
  self.command=command or worker_command();self.timeout=timeout
  self._lock=threading.RLock();self.process=None;self._responses=None;self.generation=None
 def _start(self):
  if self.process is not None and self.process.poll() is None:return
  if self.process is not None:self._failed()
  responses=queue.Queue()
  self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),bufsize=65536)
  self.generation=uuid.uuid4().hex
  self._responses=responses
  process=self.process
  def read():
   try:
    while True:
     line=process.stdout.readline(MAX_FRAME+1)
     if not line:break
     if len(line)>MAX_FRAME or not line.endswith(b'\n'):break
     responses.put(json.loads(line.decode('utf-8')))
   except (OSError,ValueError):pass
   finally:
    responses.put(None)
    process.stdout.close()
  threading.Thread(target=read,name='STOOM-clipboard-IPC',daemon=True).start()
  self._exchange('ping',None,[])
 def _failed(self):
  process=self.process;self.process=None
  if process is not None:
   try:process.stdin.close()
   except OSError:pass
   # Calls run on translation workers, not Qt. Ensure this process has stopped
   # before a new helper can start, so timed-out writes cannot arrive later.
   try:process.wait(timeout=.35)
   except subprocess.TimeoutExpired:
    try:process.kill();process.wait(timeout=.35)
    except (OSError,subprocess.TimeoutExpired):pass
 def _exchange(self,operation,lease,arguments):
  request=uuid.uuid4().hex
  frame=json.dumps({'id':request,'op':operation,'lease':lease,'args':arguments},ensure_ascii=True).encode()+b'\n'
  if len(frame)>MAX_FRAME:raise ClipboardWorkerError('클립보드 요청이 너무 큽니다.')
  try:
   self.process.stdin.write(frame);self.process.stdin.flush()
   response=self._responses.get(timeout=self.timeout)
  except (OSError,ValueError,queue.Empty):
   self._failed()
   raise ClipboardWorkerError('클립보드 보조 작업이 응답하지 않아 이번 번역을 중단했습니다. 다시 시도하세요.') from None
  if not isinstance(response,dict) or response.get('id')!=request:
   self._failed()
   raise ClipboardWorkerError('클립보드 보조 작업이 종료되어 이번 번역을 중단했습니다. 다시 시도하세요.')
  if not response.get('ok'):
   message=response.get('error','클립보드 작업을 완료하지 못했습니다.')
   if response.get('kind')=='busy':raise ClipboardWorkerError(message)
   raise ClipboardWorkerError(message)
  return response.get('value')
 def request(self,operation,lease=None,arguments=(),generation=None):
  with self._lock:
   if generation is not None and (self.generation!=generation or self.process is None or self.process.poll() is not None):
    raise ClipboardWorkerError('클립보드 보조 작업이 종료되어 이번 번역을 중단했습니다. 다시 시도하세요.')
   self._start()
   return self._exchange(operation,lease,list(arguments))
 def close(self):
  with self._lock:self._failed()

_broker=Broker()

def warmup():
 try:_broker.request('ping')
 except ClipboardWorkerError:pass  # A fresh gesture can start a new helper.

def shutdown():_broker.close()
atexit.register(shutdown)

class ClipboardLease:
 def __init__(self,broker=None):
  self._broker=broker or _broker;self._closed=False
  self._lease=self._broker.request('begin')
  self._generation=self._broker.generation
 def _call(self,operation,*arguments):
  if self._closed:raise ClipboardWorkerError('클립보드 작업이 이미 끝났습니다.')
  return self._broker.request(operation,self._lease,arguments,generation=self._generation)
 def put(self,text):return self._call('put',text)
 def arm_copy(self):return self._call('arm_copy')
 def read_copy(self,owner_pids):return self._call('read_copy',list(owner_pids))
 def replace_owned(self,expected,text):return self._call('replace_owned',expected,text)
 def confirm_selection_and_put(self,expected,translation):return self._call('confirm',expected,translation)
 def restore(self):
  if self._closed:return False
  try:return self._call('end')
  finally:self._closed=True
