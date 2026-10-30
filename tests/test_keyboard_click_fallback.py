"""Caret-click failures have no keyboard fallback; line mode stays separate."""
from pathlib import Path
import sys
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import keyboard_access as k

def forbidden(*args,**kwargs):raise AssertionError('unexpected mouse/vertical fallback')

# Missing diagnostic caret is not permission to try a different strategy.
env=NS(caret_point=lambda:None,chord=forbidden,_move=forbidden,click=forbidden)
try:k.Windows.select_by_click(env,lambda:None,lambda seconds:None)
except k.KeyboardError:pass
else:raise AssertionError('diagnostic helper silently changed strategy')

# Explicit line mode never queries geometry or invokes caret clicks.
events=[];guards=[];pauses=[]
env=NS(selection_mode='current_line',caret_point=forbidden,select_by_click=forbidden,_move=forbidden,click=forbidden,
       chord=lambda *keys:events.append(keys))
strategy=k.Windows.select(env,lambda:guards.append(1),pauses.append)
assert strategy=='current_line' and events==[(k.SHIFT,k.HOME)] and guards and pauses

# Cancel before selection means even the one Home chord is not delivered.
events=[]
def cancelled():raise k.Cancelled('test input changed')
env=NS(chord=lambda *keys:events.append(keys))
try:k.Windows.select(env,cancelled,lambda seconds:None)
except k.Cancelled:pass
else:raise AssertionError('cancelled selection continued')
assert not events
print('PASS: no fallback from caret clicks; explicit line mode never uses mouse/vertical navigation')
