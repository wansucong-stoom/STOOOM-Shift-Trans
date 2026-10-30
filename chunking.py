"""Split long text into bounded token chunks while preserving line boundaries."""
import re

def chunks(text, tokenizer, limit=96):
 for part in re.split(r'(\r\n|[\r\n\v\f\x85\u2028\u2029])',text):
  if not part: continue
  if part in ('\r\n','\r','\n','\v','\f','\x85','\u2028','\u2029'):
   yield False,part
   continue
  remaining=part
  while remaining:
   match=re.match(r'\s+',remaining)
   if match:
    raw=match.group();yield False,raw;remaining=remaining[len(raw):];continue
   if len(tokenizer.encode(remaining,out_type=str)) <= limit:
    trailing=re.search(r'\s+$',remaining)
    if trailing:
     body=remaining[:trailing.start()]
     if body: yield True,body
     yield False,trailing.group()
    else: yield True,remaining
    break
   lo,hi=1,len(remaining)
   while lo<hi:
    mid=(lo+hi+1)//2
    if len(tokenizer.encode(remaining[:mid],out_type=str))<=limit:lo=mid
    else:hi=mid-1
   if len(tokenizer.encode(remaining[:lo],out_type=str))>limit:
    raise ValueError('번역할 수 없는 긴 문자가 있습니다.')
   # Prefer a sentence or word boundary, but avoid tiny fragments.
   cut=lo
   for i in range(lo-1,max(0,lo//2)-1,-1):
    if remaining[i].isspace():cut=i;break
    if remaining[i] in '.!?。！？':cut=i+1;break
   yield True,remaining[:cut]
   remaining=remaining[cut:]
