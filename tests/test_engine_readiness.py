import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]));import engine_readiness as e
available={('ko','en'),('en','ja')}
def resolve(a,b):
 if (a,b) not in available:raise ValueError('missing')
 return ['model']
assert e.choose_probe('auto',['en'],resolve)==('ko','en')
assert e.choose_probe('en',['ja'],resolve)==('en','ja')
try:e.choose_probe('ja',['ko'],resolve);raise AssertionError('missing pack accepted')
except ValueError:pass
assert e.warm('ko','en',lambda text,src,dst:'Hello')=='Hello'
try:e.warm('ko','en',lambda *a:'');raise AssertionError('empty result accepted')
except ValueError:pass
print('ready probe requires configured direction and nonempty translation: PASS')
