"""Pinned, common product identity survives copying and all native icon sizes."""
from pathlib import Path
import hashlib,json,struct,xml.etree.ElementTree as ET
from PySide6.QtGui import QImage

root=Path(__file__).resolve().parents[1]
kit=root/'branding'
spec=json.loads((kit/'brand-spec.json').read_text(encoding='utf-8'))
for name,expected in spec['files'].items():
    assert hashlib.sha256((kit/name).read_bytes()).hexdigest()==expected,name
assert spec['font']['family']=='Inter' and spec['font']['wght']==850 and spec['font']['opsz']==14
assert spec['font']['code_px']==10.5
assert spec['products']=={'sst':'SST','pwh':'Pwh','original':''}
assert (root/'stoom.ico').read_bytes()==(kit/'sst'/'stoom.ico').read_bytes()

def frames(path):
    data=path.read_bytes();reserved,kind,count=struct.unpack_from('<HHH',data)
    assert reserved==0 and kind==1 and count==10
    result={}
    for n in range(count):
        w,h,_,_,planes,bits,length,offset=struct.unpack_from('<BBBBHHII',data,6+n*16)
        size=w or 256;assert size==(h or 256) and planes==1 and bits==32
        payload=data[offset:offset+length]
        assert payload.startswith(b'\x89PNG\r\n\x1a\n')
        image=QImage.fromData(payload,'PNG');assert not image.isNull()
        assert image.width()==size and image.height()==size
        result[size]=payload
    return result

for product in ('sst','pwh','original'):
    directory=kit/product
    ico=frames(directory/'stoom.ico')
    assert sorted(ico)==[16,20,24,32,40,48,64,96,128,256]
    for size,payload in ico.items():assert payload==(directory/f'icon-{size}.png').read_bytes()
    alpha=QImage(str(directory/'mark-full-glow-alpha.png'))
    assert alpha.hasAlphaChannel()
    for n in range(alpha.width()):
        assert alpha.pixelColor(n,0).alpha()==alpha.pixelColor(n,alpha.height()-1).alpha()==0
        assert alpha.pixelColor(0,n).alpha()==alpha.pixelColor(alpha.width()-1,n).alpha()==0
    lockup=QImage(str(directory/'lockup-light-3x.png'))
    assert (lockup.width(),lockup.height())==(474,144)

ns={'s':'http://www.w3.org/2000/svg'}
sst=ET.parse(kit/'sst'/'mark.svg').getroot();pwh=ET.parse(kit/'pwh'/'mark.svg').getroot()
for tag in ('circle','rect','filter'):
    assert [x.attrib for x in sst.findall('.//s:'+tag,ns)]==[x.attrib for x in pwh.findall('.//s:'+tag,ns)]
assert sst.find('s:g/s:path',ns).attrib['d']!=pwh.find('s:g/s:path',ns).attrib['d']
print('Brand kit: pinned assets/font, common circle/diagonal/glow, labels,10ICO sizes, transparent glow edges and158x48 lockups: PASS')
