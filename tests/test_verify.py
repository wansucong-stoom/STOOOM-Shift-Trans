import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));import main
pending=[]; main.QTimer=types.SimpleNamespace(singleShot=lambda delay,fn:pending.append(fn))
main.ctypes=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(GetForegroundWindow=lambda:7)))
moves=[];main.move_caret_to_end=lambda hwnd,rid:moves.append((hwnd,rid))
class TestApp:
 busy=True
 errors=[]
 def error(self,e): self.errors.append(e); self.busy=False
 verify_result=main.App.verify_result
app=TestApp(); values=iter(['old','old','hello\r\nworld'])
main.focused=lambda:((1,2),next(values),None)
app.verify_result(7,(1,2),'hello\nworld',4)
while pending: pending.pop(0)()
assert app.busy is False and not app.errors and moves==[(7,(1,2))]
app.busy=True;main.focused=lambda:((1,2),'unexpected',None)
app.verify_result(7,(1,2),'wanted',4)
while pending: pending.pop(0)()
assert len(app.errors)==1 and not app.busy
print('Delayed value, newline normalization, bounded failure: PASS')

