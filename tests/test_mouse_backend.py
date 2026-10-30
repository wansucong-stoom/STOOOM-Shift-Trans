"""Exercise installed pynput's actual Windows dispatch, without global hooks."""
import ctypes,os,pathlib,sys,tempfile,types
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
with tempfile.TemporaryDirectory() as root:
 old=os.environ.get('LOCALAPPDATA');os.environ['LOCALAPPDATA']=root
 import main
 if old is None:os.environ.pop('LOCALAPPDATA',None)
 else:os.environ['LOCALAPPDATA']=old
from pynput import mouse,keyboard

bridge=types.SimpleNamespace(trigger=types.SimpleNamespace(emit=lambda event:None))
tap=main.Tap(bridge)
listener=tap.mouse_listener
data=listener._MSLLHOOKSTRUCT()
data.pt.x=50;data.pt.y=60;data.dwExtraInfo=0
baseline=tap.activity_snapshot()
for _ in range(5):
 listener._handle_message(0,listener.WM_MOUSEMOVE,ctypes.addressof(data))
assert tap.activity_snapshot()==baseline,'native 3-argument motion changed input revision'

# Motion must not break the pending first/second modifier gesture either.
tap.down={'shift'};tap.pending={'shift'};tap.last={'ctrl':1.0}
listener._handle_message(0,listener.WM_MOUSEMOVE,ctypes.addressof(data))
assert tap.down=={'shift'} and tap.pending=={'shift'} and tap.last=={'ctrl':1.0}

# Reproduce the old adapter against the SAME installed backend. Its len==2
# assumption changes the revision on a normal 1.8 motion and cancels capture.
old_tap=main.Tap(bridge)
def previous_adapter(*args):
 if len(args)==2:return
 old_tap.pointer_activity(*args)
old_tap.mouse_listener.on_move=previous_adapter
old_revision=old_tap.activity_snapshot()[0]
old_tap.mouse_listener._handle_message(0,listener.WM_MOUSEMOVE,ctypes.addressof(data))
assert old_tap.activity_snapshot()[0]==old_revision+1
env=types.SimpleNamespace(current=lambda:True,activity=old_tap.activity_snapshot)
try:main.keyboard_access.Driver(env).guard(old_revision)
except main.keyboard_access.Cancelled:pass
else:raise AssertionError('old motion callback did not reproduce capture cancellation')
env.activity=tap.activity_snapshot
main.keyboard_access.Driver(env).guard(baseline[0])

# Button/scroll callbacks in 1.8 include injected metadata too. They must
# invalidate a stored selection; filtering must not mute real interaction.
listener._handle_message(0,listener.WM_LBUTTONDOWN,ctypes.addressof(data))
assert tap.activity_snapshot()[0]==baseline[0]+1 and not tap.pending and not tap.last
assert tap.activity_cause()=='click'
listener._handle_message(0,listener.WM_MOUSEMOVE,ctypes.addressof(data))
assert tap.activity_snapshot()[0]==baseline[0]+2,'held-button drag must invalidate selection'
assert tap.activity_cause()=='drag'
listener._handle_message(0,listener.WM_LBUTTONUP,ctypes.addressof(data))
assert tap.activity_snapshot()[0]==baseline[0]+3
listener._handle_message(0,listener.WM_MOUSEMOVE,ctypes.addressof(data))
assert tap.activity_snapshot()[0]==baseline[0]+3,'released-button motion must not invalidate selection'
data.mouseData=120<<16
listener._handle_message(0,listener.WM_MOUSEWHEEL,ctypes.addressof(data))
assert tap.activity_snapshot()[0]==baseline[0]+4
assert tap.activity_cause()=='scroll'

before=tap.activity_snapshot()
data.dwExtraInfo=main.keyboard_access.INPUT_TAG
listener._handle_message(0,listener.WM_LBUTTONDOWN,ctypes.addressof(data))
assert tap.activity_snapshot()==before,'tagged automatic click was treated as user input'

# Also check the actual typed keyboard hook record, rather than a fake object.
keydata=tap.listener._KBDLLHOOKSTRUCT()
keydata.vkCode=0x43;keydata.dwExtraInfo=main.keyboard_access.INPUT_TAG
assert tap.listener._convert(0,0x100,ctypes.addressof(keydata)) is None
keydata.dwExtraInfo=0
assert tap.listener._convert(0,0x100,ctypes.addressof(keydata)) is not None
tap.press(keyboard.KeyCode.from_char('x'))
assert tap.activity_cause()=='typing'
print('Installed Windows pynput dispatch: old motion cancellation reproduced; free motion ignored; clicks/drags/scrolls invalidate; tagged input ignored; pending taps survive motion: PASS')
