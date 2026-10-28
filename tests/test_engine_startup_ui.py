import os,sys,tempfile,pathlib
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import main
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
class Listener:
 def start(self):pass
 def stop(self):pass
class Tap:
 def __init__(self,b):self.listener=Listener()
main.Tap=Tap
class Tray:
 def __init__(self):self.messages=[]
 def showMessage(self,*a):self.messages.append(a)
 def hide(self):pass
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
 main.APP=pathlib.Path(d);main.MODELS=main.APP/'models';main.MODELS.mkdir()
 w=main.App();w.tray.hide();spy=Tray();w.tray=spy
 main.path_for=lambda src,dst:['test-model']
 main.engine_readiness.warm=lambda src,dst,translate:'test translated'
 w.show();loop=QEventLoop();QTimer.singleShot(500,loop.quit);loop.exec()
 assert not w.engine_initializing and w.engine_readiness.text()=='번역 엔진 준비 완료'
 assert len(spy.messages)==1 and '준비가 완료되었습니다' in spy.messages[0][1]
 # A failed probe never claims readiness.
 config=w.engine_configuration();spy.messages.clear();w.engine_initializing=True
 w.engine_preflight_done((config,False,'시험 실패'))
 assert not w.engine_initializing and w.engine_readiness.text()=='시험 실패'
 assert all('준비가 완료되었습니다' not in m[1] for m in spy.messages)
 w.deleteLater();app.processEvents()
print('startup warm-up success, readiness toast and failure reporting: PASS')
