"""Real pipes/process failure plus real STA startup; no clipboard changes."""
import pathlib,sys,tempfile,time
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_process as c

stub=[sys.executable,str(pathlib.Path(__file__).with_name('fixtures')/'clipboard_stub.py')]
b=c.Broker(stub,timeout=1)
try:
 first=b.request('ping')['pid']
 text='번역😀'*8000
 assert b.request('echo',arguments=[text])==text
 with tempfile.TemporaryDirectory() as root:
  path=pathlib.Path(root)/'mutations.txt'
  started=time.monotonic()
  try:b.request('mutate_and_die',arguments=[str(path)])
  except c.ClipboardWorkerError:pass
  else:raise AssertionError('child death was not reported')
  assert time.monotonic()-started<2
  assert b.request('ping')['pid']!=first
  assert path.read_text().splitlines()==['one simulated write'],'a write was replayed'
 b.timeout=.05;started=time.monotonic()
 try:b.request('hang')
 except c.ClipboardWorkerError:pass
 else:raise AssertionError('hung child did not time out')
 assert time.monotonic()-started<1.5
 b.timeout=1
 assert b.request('ping')['pid']
finally:b.close()

# The production early entry starts only the helper. Empty begin/end has no
# clipboard calls. The same process/STA serves every session.
b=c.Broker(timeout=2)
try:
 first=b.request('ping')['pid']
 for _ in range(30):
  lease=c.ClipboardLease(b);assert lease.restore() is False
 assert b.request('ping')['pid']==first
 abandoned=c.ClipboardLease(b)
 launcher=b.process.pid
 b.process.kill();b.process.wait(timeout=2)
 try:abandoned.restore()
 except c.ClipboardWorkerError:pass
 else:raise AssertionError('a dead session was reused')
 assert b.process.pid==launcher,'cleanup started a new worker for a dead session'
 assert b.request('ping')['pid']!=first
finally:b.close()
print('Clipboard worker: native STA reuse, Unicode pipes, child death and hang contained, next request recovers, no mutating replay; no clipboard changes: PASS')
