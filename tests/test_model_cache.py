import sys,pathlib,tempfile,types,os
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import main
created=[]
class SP:
 def __init__(self,model_file):created.append(('tokenizer',model_file))
class Translator:
 def __init__(self,path,**kw):created.append(('translator',path))
sys.modules['sentencepiece']=types.SimpleNamespace(SentencePieceProcessor=SP)
sys.modules['ctranslate2']=types.SimpleNamespace(Translator=Translator)
with tempfile.TemporaryDirectory() as d:
 main.MODELS=pathlib.Path(d);p=main.MODELS/'ko_en';(p/'model').mkdir(parents=True)
 m=p/'model'/'model.bin';m.write_bytes(b'x');(p/'sentencepiece.model').write_bytes(b'y')
 main._load_model_cached.cache_clear()
 a=main.load_model('ko_en');b=main.load_model('ko_en');assert a is b and len(created)==2
 st=m.stat().st_mtime_ns;os.utime(m,ns=(st+1000000000,st+1000000000))
 c=main.load_model('ko_en');assert c is not a and len(created)==4
 main._load_model_cached.cache_clear()
print('loaded model is reused; changed model is reloaded: PASS')
