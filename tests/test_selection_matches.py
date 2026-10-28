import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from range_access import selection_matches
class R:
 def __init__(self,text,start,force_mismatch=False):self.text=text;self.start=start;self.force_mismatch=force_mismatch
 def GetText(self,n):return self.text
 def CompareEndpoints(self,*a):return 1 if self.force_mismatch else 0
class Prefix:
 def __init__(self,full):self.full=full;self.end=0
 def Clone(self):return Prefix(self.full)
 def MoveEndpointByRange(self,a,r,b):self.end=r.start
 def GetText(self,n):return self.full[:self.end]
class A:
 def __init__(self,r,count=1):self.r=r;self.Length=count
 def GetElement(self,n):return self.r
doc=Prefix('zero abc then abc');target=R('abc',5,True)
assert selection_matches(A(R('abc',5,True)),target,'abc',doc)
assert not selection_matches(A(R('abc',14,True)),target,'abc',doc)
assert not selection_matches(A(R('ab',5,True)),target,'abc',doc)
assert not selection_matches(A(R('',0),0),target,'abc',doc)
print('selection text and location, including duplicate occurrence: PASS')
