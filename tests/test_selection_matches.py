import sys,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from range_access import selection_matches
class R:
 def __init__(self,text):self.text=text
 def GetText(self,n):return self.text
 def CompareEndpoints(self,*a):return 1
class A:
 def __init__(self,text,count=1):self.text=text;self.Length=count
 def GetElement(self,n):return R(self.text)
assert selection_matches(A('안녕하세요'),R('unused'),'안녕하세요')
assert selection_matches(A('a\r\nb'),R('unused'),'a\nb')
assert not selection_matches(A('안녕'),R('unused'),'안녕하세요')
assert not selection_matches(A('안녕하세요\n'),R('unused'),'안녕하세요')
assert not selection_matches(A('',0),R('unused'),'안녕하세요')
print('exact selection text, newline normalization and rejection: PASS')
