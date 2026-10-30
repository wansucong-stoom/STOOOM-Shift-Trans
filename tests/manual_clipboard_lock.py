"""Non-destructive Windows clipboard contention test: opens/closes only."""
import pathlib,sys,threading,time,json,subprocess
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import clipboard_lease as c
import win32clipboard
if '--holder' in sys.argv:
 import clipboard_worker
 user,window=clipboard_worker._create_owner_window();c.OWNER_WINDOW=window
 c._open_clipboard()
 try:
  print('locked',flush=True);sys.stdin.readline()
 finally:win32clipboard.CloseClipboard();user.DestroyWindow(window)
 sys.exit(0)
child=subprocess.Popen([sys.executable,__file__,'--holder'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                      creationflags=subprocess.CREATE_NO_WINDOW,text=True)
try:
 assert child.stdout.readline().strip()=='locked'
 def release():
  child.stdin.write('release\n');child.stdin.flush()
 timer=threading.Timer(.08,release);timer.start()
 start=time.perf_counter()
 c._open_clipboard()
 elapsed=time.perf_counter()-start
 win32clipboard.CloseClipboard();timer.join(1)
finally:
 child.stdin.close();child.wait(timeout=2);child.stdout.close()
assert .04<elapsed<.5,elapsed
print(json.dumps({'ok':True,'lock_milliseconds':80,'recovered_milliseconds':round(elapsed*1000,1),'contents_changed':False}))

