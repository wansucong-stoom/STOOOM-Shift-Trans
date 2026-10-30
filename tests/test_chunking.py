import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));from chunking import chunks
class T:
 def encode(self,s,out_type=str):return list(s)
t=T()
for s in ['hello world  \r\n  next row ', '가'*250, 'abc. def ghi jkl mno', '']:
 c=list(chunks(s,t,limit=6)); assert ''.join(x for _,x in c)==s,(s,c)
 assert all(len(t.encode(x))<=6 for trans,x in c if trans)
for boundary in ('\r\n','\r','\n','\v','\f','\x85','\u2028','\u2029'):
 original='First sentence.'+boundary+'Second sentence.'
 parts=list(chunks(original,t,limit=100))
 assert parts==[(True,'First sentence.'),(False,boundary),(True,'Second sentence.')]
 # A model can normalize all whitespace; it must never receive the boundary.
 result=''.join('Translated' if translate else part for translate,part in parts)
 assert result=='Translated'+boundary+'Translated'
print('long text chunks, whitespace and line boundaries: PASS')

