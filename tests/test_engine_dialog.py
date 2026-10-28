import os,sys,tempfile,pathlib
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
import main
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtCore import QTimer
class Listener:
 def start(self):pass
 def stop(self):pass
class FakeTap:
 def __init__(self,b):self.listener=Listener()
main.Tap=FakeTap
app=QApplication([])
with tempfile.TemporaryDirectory() as d:
 main.APP=pathlib.Path(d);main.MODELS=main.APP/'models';main.MODELS.mkdir()
 w=main.App();w.show();w.select_page(2);app.processEvents()
 w.choose_engine();app.processEvents()
 assert w._engine_dialog is not None and w._engine_dialog.isVisible()
 assert w._engine_dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
 alive=[];QTimer.singleShot(0,lambda:alive.append(True));app.processEvents();assert alive,'event loop blocked'
 w._engine_dialog.reject();app.processEvents();assert w._engine_dialog is None
 p=str(pathlib.Path(d)/'engine.exe');pathlib.Path(p).write_bytes(b'test')
 w.engine_selected(p);assert w.external_path==p and w.engine.currentText()=='사용자 외부 엔진'
 assert p in w.engine_path_label.text() and (main.APP/'settings.json').exists()
 w.tray.hide();w.deleteLater();app.processEvents()
print('Non-native file chooser remains responsive, closes, and saves selection: PASS')
