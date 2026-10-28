import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]));from chunking import chunks
class T:
 def encode(self,s,out_type=str):return list(s)
t=T()
for s in ['hello world  \r\n  next row ', '가'*250, 'abc. def ghi jkl mno', '']:
 c=list(chunks(s,t,limit=6)); assert ''.join(x for _,x in c)==s,(s,c)
 assert all(len(t.encode(x))<=6 for trans,x in c if trans)
print('long text chunks, whitespace and line boundaries: PASS')

