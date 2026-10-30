import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1])); import main
from pynput import keyboard
class Trigger:
 def __init__(self): self.events=[]
 def emit(self,k): self.events.append(k)
class Bridge:
 def __init__(self): self.trigger=Trigger()
def kinds(bridge): return [event[0] for event in bridge.trigger.events]
held=set(); main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(GetAsyncKeyState=lambda vk:0x8000 if vk in held else 0)))
clock=[0.]; main.time.monotonic=lambda:clock[0]
b=Bridge(); t=main.Tap(b)
def pair(key):
 t.press(key); clock[0]+=.05; t.release(key); clock[0]+=.08; t.press(key); clock[0]+=.05; t.release(key); clock[0]+=.08
for _ in range(4):
 t.press(keyboard.KeyCode.from_char('A')); t.release(keyboard.KeyCode.from_char('a')); pair(keyboard.Key.shift_l)
assert kinds(b)==['shift']*4,b.trigger.events
assert [event[1] for event in b.trigger.events]==[1,2,3,4], 'payload must preserve the input revision at each gesture'
assert all(len(event)==3 and isinstance(event[2],float) for event in b.trigger.events)
pair(keyboard.Key.ctrl_l); assert kinds(b)[-1]=='ctrl'
held.add(0x41); pair(keyboard.Key.shift); held.clear(); assert kinds(b).count('shift')==4
# An intervening normal key invalidates the first tap.
t.press(keyboard.Key.shift); t.release(keyboard.Key.shift); t.press(keyboard.KeyCode.from_char('a')); t.release(keyboard.KeyCode.from_char('a')); t.press(keyboard.Key.shift); t.release(keyboard.Key.shift)
assert kinds(b).count('shift')==4
# Mixed left/generic release cannot leave a modifier permanently stuck.
t.press(keyboard.Key.ctrl_l); t.release(keyboard.Key.ctrl); assert 'ctrl' not in t.down

# A completed double tap fires only after the second key has been released.
b2=Bridge(); t2=main.Tap(b2); clock[0]=10.
t2.press(keyboard.Key.shift_l); clock[0]+=.05; t2.release(keyboard.Key.shift_l)
clock[0]+=.08; t2.press(keyboard.Key.shift_l)
assert b2.trigger.events==[], 'second key down must not capture an active modifier/IME gesture'
clock[0]+=.05; t2.release(keyboard.Key.shift_l)
assert b2.trigger.events==[('shift',0,clock[0])], 'second key up sends gesture kind, input revision and release time'

# A held first tap cannot prime a double tap.
b3=Bridge(); t3=main.Tap(b3); clock[0]=20.
t3.press(keyboard.Key.shift); clock[0]+=.4; t3.release(keyboard.Key.shift)
clock[0]+=.08; t3.press(keyboard.Key.shift); clock[0]+=.05; t3.release(keyboard.Key.shift)
assert b3.trigger.events==[], 'held first key must cancel'

# A held second tap cannot fire a pending trigger on release.
b4=Bridge(); t4=main.Tap(b4); clock[0]=30.
t4.press(keyboard.Key.ctrl); clock[0]+=.05; t4.release(keyboard.Key.ctrl)
clock[0]+=.08; t4.press(keyboard.Key.ctrl); clock[0]+=.4; t4.release(keyboard.Key.ctrl)
assert b4.trigger.events==[], 'held second key must cancel'

# Ordinary input during the pending second tap cancels it and records activity.
b5=Bridge(); t5=main.Tap(b5); clock[0]=40.
t5.press(keyboard.Key.shift); clock[0]+=.05; t5.release(keyboard.Key.shift)
clock[0]+=.08; t5.press(keyboard.Key.shift)
revision,_=t5.activity_snapshot(); letter=keyboard.KeyCode.from_char('a')
clock[0]+=.01; t5.press(letter)
assert t5.activity_snapshot()==(revision+1,clock[0])
clock[0]+=.01; t5.release(letter)
assert t5.activity_snapshot()==(revision+1,clock[0]), 'release updates quiet time without adding a new key'
clock[0]+=.01; t5.release(keyboard.Key.shift)
assert b5.trigger.events==[], 'ordinary key during second tap must cancel'
print('Repeated taps, release-only trigger, held-key cancellation and activity revision: PASS')

# Our own SendInput events must never count as user typing or another tap.
assert t.event_filter(0,types.SimpleNamespace(dwExtraInfo=main.keyboard_access.INPUT_TAG)) is False
assert t.event_filter(0,types.SimpleNamespace(dwExtraInfo=0)) is True
revision=t.activity_snapshot()[0]
t.pointer_move(10,20)
assert t.activity_snapshot()[0]==revision, 'pointer movement alone does not change the selection'
t.pointer_move(10,20,False)
assert t.activity_snapshot()[0]==revision, 'pynput 1.8 movement includes an injected argument'
t.pointer_activity(10,20,'left',True)
assert t.activity_snapshot()[0]==revision+1, 'a real click must cancel a saved selection'
print('Own injected events ignored; real clicks invalidate selection; pointer movement allowed: PASS')

