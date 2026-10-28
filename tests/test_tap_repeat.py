import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1])); import main
from pynput import keyboard
class Trigger:
 def __init__(self): self.events=[]
 def emit(self,k): self.events.append(k)
class Bridge:
 def __init__(self): self.trigger=Trigger()
held=set(); main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(GetAsyncKeyState=lambda vk:0x8000 if vk in held else 0)))
clock=[0.]; main.time.monotonic=lambda:clock[0]
b=Bridge(); t=main.Tap(b)
def pair(key):
 t.press(key); clock[0]+=.05; t.release(key); clock[0]+=.08; t.press(key); clock[0]+=.05; t.release(key); clock[0]+=.08
for _ in range(4):
 t.press(keyboard.KeyCode.from_char('A')); t.release(keyboard.KeyCode.from_char('a')); pair(keyboard.Key.shift_l)
assert b.trigger.events==['shift']*4,b.trigger.events
pair(keyboard.Key.ctrl_l); assert b.trigger.events[-1]=='ctrl'
held.add(0x41); pair(keyboard.Key.shift); held.clear(); assert b.trigger.events.count('shift')==4
# An intervening normal key invalidates the first tap.
t.press(keyboard.Key.shift); t.release(keyboard.Key.shift); t.press(keyboard.KeyCode.from_char('a')); t.release(keyboard.KeyCode.from_char('a')); t.press(keyboard.Key.shift); t.release(keyboard.Key.shift)
assert b.trigger.events.count('shift')==4
# Mixed left/generic release cannot leave a modifier permanently stuck.
t.press(keyboard.Key.ctrl_l); t.release(keyboard.Key.ctrl); assert 'ctrl' not in t.down
print('Repeated mixed key-up, Ctrl, shortcuts, intervening key, and modifier release: PASS')

