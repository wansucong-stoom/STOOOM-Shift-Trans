import sys
sys.path.insert(0,str(__import__('pathlib').Path(__file__).resolve().parents[1]))
from range_access import capture,unchanged
class R:
 def __init__(self,doc,start,end): self.doc=doc; self.start=start; self.end=end
 def Clone(self): return R(self.doc,self.start,self.end)
 def GetText(self,n): return self.doc[0][self.start:self.end]
 def ExpandToEnclosingUnit(self,u):
  assert u==4
  x=self.doc[0]; self.start=x.rfind('\n',0,self.start)+1; self.end=x.find('\n',self.end)
  if self.end<0:self.end=len(x)
 def CompareEndpoints(self,a,other,b): return (self.start if a==0 else self.end)-(other.start if b==0 else other.end)
class Array:
 Length=1
 def __init__(self,r): self.r=r
 def GetElement(self,n): return self.r
class P:
 def __init__(self,doc,anchor): self.doc=doc;self.anchor=anchor
 def GetSelection(self): return Array(self.anchor)
 @property
 def DocumentRange(self): return R(self.doc,0,len(self.doc[0]))
doc=['first\nsecond\nthird']; pat=P(doc,R(doc,7,7)); snap=capture((1,2),pat,True)
assert snap.text=='second' and not snap.selected and unchanged(snap,(1,2),pat)
pat.anchor=R(doc,8,8); assert not unchanged(snap,(1,2),pat)
pat.anchor=R(doc,7,9); snap=capture((1,2),pat,True); assert snap.text=='ec' and snap.selected
pat.anchor=R(doc,0,0); snap=capture((1,2),pat,False); assert snap.text==doc[0]
doc[0]='other'; assert not unchanged(snap,(1,2),pat)
print('selection, paragraph, input field, changed cursor and changed text: PASS')

