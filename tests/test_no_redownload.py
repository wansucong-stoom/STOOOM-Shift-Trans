import sys,types
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1])); import main
class Signal:
 def emit(self,x): self.value=x
class Label:
 def setText(self,x): self.value=x
class Check:
 def isChecked(self): return True
class Immediate:
 def __init__(self,target,daemon): self.target=target
 def start(self): self.target()
main.threading.Thread=Immediate
main.pack_installed=lambda k: True
main.install_pack=lambda k: (_ for _ in ()).throw(AssertionError('download should be skipped'))
a=types.SimpleNamespace(downloading=False,checks={'ko_en':Check()},status=Label(),bridge=types.SimpleNamespace(download_done=Signal()))
main.App.download(a)
assert '다시 받지' in a.bridge.download_done.value
print('Installed language packs are not downloaded again: PASS')

