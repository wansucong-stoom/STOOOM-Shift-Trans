"""Reproducible STOOM product marks from the approved CSS and pinned Inter.

Vector geometry/colour remains common. Product strings are the only variation.
No global font installation, user UI, or existing application files are used.
"""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import hashlib,json,math,shutil,struct,sys
from pathlib import Path
import numpy as np
from PySide6.QtCore import QByteArray,QBuffer,QIODevice,QRectF,Qt
from PySide6.QtGui import QGuiApplication,QFontDatabase,QFont,QPainterPath,QTransform,QImage,QPainter,QColor,QPen

ROOT=Path(__file__).resolve().parent
OUT=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'product-identity-v1'
assert OUT!=ROOT, 'Choose a separate output directory; do not overwrite the source kit.'
FONT=ROOT/'font'/'Inter[opsz,wght].ttf' if (ROOT/'font').is_dir() else ROOT/'Inter-variable.ttf'
CANON=ROOT/'stoom-mark-original.css' if (ROOT/'stoom-mark-original.css').is_file() else Path('C:/Users/wansucong/.stoom/branding/stoom-mark-original.css')
app=QGuiApplication.instance() or QGuiApplication([])
font_id=QFontDatabase.addApplicationFont(str(FONT))
families=QFontDatabase.applicationFontFamilies(font_id)
assert 'Inter' in families
OUT.mkdir(parents=True,exist_ok=True)
shutil.copy2(FONT,OUT/'Inter-variable.ttf')
shutil.copy2(ROOT/'font'/'OFL.txt' if (ROOT/'font').is_dir() else ROOT/'OFL-Inter.txt',OUT/'OFL-Inter.txt')
shutil.copy2(ROOT/'font'/'provenance.json' if (ROOT/'font').is_dir() else ROOT/'font-provenance.json',OUT/'font-provenance.json')
shutil.copy2(CANON,OUT/'stoom-mark-original.css')
if (ROOT/'README.md').is_file():shutil.copy2(ROOT/'README.md',OUT/'README.md')
BG='#071019';INK='#e3faff';CYAN='#67d8ff'
SIZES=(16,20,24,32,40,48,64,96,128,256)
PRODUCTS={'sst':'SST','pwh':'Pwh','original':''}

def font(size):
    f=QFont('Inter');f.setPixelSize(round(size))
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    f.setVariableAxis(QFont.Tag('wght'),850.)
    f.setVariableAxis(QFont.Tag('opsz'),14.)
    return f

def glyph(label,size,cx,cy):
    p=QPainterPath()
    if not label:return p
    p.addText(0,0,font(size*100),label)
    p=QTransform.fromScale(.01,.01).map(p)
    box=p.boundingRect()
    return QTransform.fromTranslate(cx-box.center().x(),cy-box.center().y()).map(p)

def png(image):
    data=QByteArray();buffer=QBuffer(data);buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer,'PNG')
    return bytes(data)

def glow(width,logical,x,y,blur):
    mask=QImage(width,width,QImage.Format.Format_RGBA8888);mask.fill(0)
    p=QPainter(mask);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(width/logical,width/logical);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('white'))
    p.drawEllipse(QRectF(x,y,29,29));p.end()
    a=np.frombuffer(mask.constBits(),np.uint8).reshape(width,mask.bytesPerLine())[:,:width*4].reshape(width,width,4)[:,:,3].astype(np.float32)/255
    sigma=blur/2*width/logical
    radius=math.ceil(sigma*3.5)
    t=np.arange(-radius,radius+1,dtype=np.float32)
    kernel=np.exp(-.5*(t/sigma)**2);kernel/=kernel.sum()
    b=np.apply_along_axis(lambda row:np.convolve(row,kernel,mode='same'),1,a)
    b=np.apply_along_axis(lambda row:np.convolve(row,kernel,mode='same'),0,b)
    result=np.zeros((width,width,4),dtype=np.uint8);result[:,:,:3]=(103,216,255)
    result[:,:,3]=np.rint(np.clip(b*(1-a)*.38,0,1)*255).astype(np.uint8)
    return QImage(result.data,width,width,width*4,QImage.Format.Format_RGBA8888).copy()

def draw_geometry(p,x,y,label,label_size=10.5):
    p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor(INK),2))
    p.drawEllipse(QRectF(x+1,y+1,27,27))
    p.save();p.translate(x+28,y+8);p.rotate(-35)
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(INK));p.drawRect(QRectF(-7,-1,14,2));p.restore()
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(INK))
    p.drawPath(glyph(label,label_size,x+14.5,y+17))

def image(label,size,full=False,backing=True):
    logical=96 if full else 40
    x,y=(32,33.5) if full else (3,5.5)
    blur=18 if full else 4.5
    width=max(128,size*4) if not full else size
    result=QImage(width,width,QImage.Format.Format_RGBA8888);result.fill(0)
    p=QPainter(result);p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(width/logical,width/logical)
    if backing:
        plate=QPainterPath();plate.addRoundedRect(QRectF(0,0,logical,logical),logical*.2,logical*.2)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(BG));p.drawPath(plate);p.setClipPath(plate)
    p.save();p.resetTransform();p.drawImage(0,0,glow(width,logical,x,y,blur));p.restore()
    # At16px the common five-pixel label floor is applied to BOTH products.
    label_size=max(10.5,5*logical/size) if not full else 10.5
    draw_geometry(p,x,y,label,label_size);p.end()
    return result.scaled(size,size,Qt.AspectRatioMode.IgnoreAspectRatio,Qt.TransformationMode.SmoothTransformation) if width!=size else result

def svg_path(path):
    parts=[];i=0
    while i<path.elementCount():
        e=path.elementAt(i)
        if e.isMoveTo():parts.append(f'M{e.x:.5f},{e.y:.5f}')
        elif e.isLineTo():parts.append(f'L{e.x:.5f},{e.y:.5f}')
        elif e.isCurveTo():
            b,c=path.elementAt(i+1),path.elementAt(i+2)
            parts.append(f'C{e.x:.5f},{e.y:.5f} {b.x:.5f},{b.y:.5f} {c.x:.5f},{c.y:.5f}');i+=2
        i+=1
    return ' '.join(parts)

def svg(label,full):
    logical=96 if full else 40;x,y=(32,33.5) if full else (3,5.5);blur=18 if full else 4.5
    plate='' if full else f'<rect width="40" height="40" rx="8" fill="{BG}"/>'
    clip='' if full else '<clipPath id="plate"><rect width="40" height="40" rx="8"/></clipPath>'
    group='<g>' if full else '<g clip-path="url(#plate)">'
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {logical} {logical}"><title>STOOM {label or 'original'} mark</title>
<defs>{clip}<filter id="halo" x="-180%" y="-180%" width="460%" height="460%" color-interpolation-filters="sRGB"><feGaussianBlur in="SourceAlpha" stdDeviation="{blur/2}" result="blur"/><feComposite in="blur" in2="SourceAlpha" operator="out" result="outer"/><feFlood flood-color="{CYAN}" flood-opacity=".38"/><feComposite in2="outer" operator="in"/></filter></defs>
{plate}{group}<circle cx="{x+14.5}" cy="{y+14.5}" r="14.5" filter="url(#halo)"/>
<circle cx="{x+14.5}" cy="{y+14.5}" r="13.5" fill="none" stroke="{INK}" stroke-width="2"/>
<rect x="{x+21}" y="{y+7}" width="14" height="2" fill="{INK}" transform="rotate(-35 {x+28} {y+8})"/>
<path fill="{INK}" d="{svg_path(glyph(label,10.5,x+14.5,y+17))}"/></g></svg>'''

spec={'schema':1,'id':'stoom-product-identity-v1','reference':'https://stoom.win/',
      'font':{'family':'Inter','file':'Inter-variable.ttf','wght':850,'opsz':14,'code_px':10.5,'code_center_from_circle_origin':[14.5,17],'letter_spacing_em':0},
      'geometry':{'icon_canvas':40,'circle_outer_diameter':29,'circle_origin':[3,5.5],'stroke':2,
                  'diagonal_size':[14,2],'diagonal_center_from_circle_origin':[28,8],'diagonal_degrees':-35},
      'colour':{'mark':INK,'glow':CYAN,'backing':BG,'glow_opacity':.38},
      'original_glow':{'blur_px':18,'transparent_canvas':96,'circle_origin':[32,33.5]},
      'icon_medium':{'blur_px':4.5,'backing_radius':8,'sizes':list(SIZES),'minimum_code_pixels':5,
                     'limitation':'Compact icon halo is bounded by its dark backing; full transparent export retains original18px halo.16px text legibility is limited.'},
      'lockup':{'icon_px':48,'gap_px':10,'word_family':'Inter','word_px':20,'word_wght':850,'word_opsz':14,'word_letter_spacing_em':.11},
      'products':PRODUCTS,'files':{}}

for key,label in PRODUCTS.items():
    directory=OUT/key;directory.mkdir(exist_ok=True)
    frames=[]
    for size in SIZES:
        im=image(label,size);data=png(im);(directory/f'icon-{size}.png').write_bytes(data);frames.append((size,data))
    offset=6+16*len(frames);entries=[];payload=[]
    for size,data in frames:
        entries.append(struct.pack('<BBBBHHII',0 if size==256 else size,0 if size==256 else size,0,0,1,32,len(data),offset))
        payload.append(data);offset+=len(data)
    (directory/'stoom.ico').write_bytes(struct.pack('<HHH',0,1,len(entries))+b''.join(entries)+b''.join(payload))
    (directory/'mark.svg').write_text(svg(label,False),encoding='utf-8')
    (directory/'mark-full-glow.svg').write_text(svg(label,True),encoding='utf-8')
    # Frozen wordmark outlines prevent machine-dependent font substitution.
    wf=font(2000);wf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing,220)
    wp=QPainterPath();wp.addText(0,0,wf,'STOOM');wp=QTransform.fromScale(.01,.01).map(wp)
    wb=wp.boundingRect();wp=QTransform.fromTranslate(-wb.x(),24-wb.center().y()).map(wp)
    for colour,theme in (('#17394c','light'),(INK,'dark')):
        for ratio in (1,3):
            im=QImage(158*ratio,48*ratio,QImage.Format.Format_RGBA8888);im.fill(0)
            p=QPainter(im);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.scale(ratio,ratio)
            p.drawImage(0,0,image(label,48));p.translate(58,0);p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor(colour));p.drawPath(wp);p.end()
            im.save(str(directory/f'lockup-{theme}-{ratio}x.png'))
        word=svg_path(wp)
        badge=svg(label,False)
        inner=badge[badge.index('<defs>'):badge.rindex('</svg>')]
        lockup=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 158 48"><g transform="scale(1.2)">{inner}</g><path fill="{colour}" transform="translate(58)" d="{word}"/></svg>'
        (directory/f'lockup-{theme}.svg').write_text(lockup,encoding='utf-8')
    for background,suffix in ((False,'alpha'),(True,'dark')):
        im=image(label,512,full=True,backing=background);im.save(str(directory/f'mark-full-glow-{suffix}.png'))
        if not background:
            a=np.frombuffer(im.constBits(),np.uint8).reshape(im.height(),im.bytesPerLine())[:,:im.width()*4].reshape(im.height(),im.width(),4)[:,:,3]
            assert not any((a[0].any(),a[-1].any(),a[:,0].any(),a[:,-1].any())), 'transparent glow clipped'
    # Common Inno image framing; artwork retains the same master geometry.
    for width,height,name,marksize in ((164,314,'installer.bmp',112),(55,55,'installer-small.bmp',48)):
        im=QImage(width,height,QImage.Format.Format_RGB32);im.fill(QColor(BG))
        p=QPainter(im);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        mark=image(label,marksize);p.drawImage((width-marksize)//2,28 if height>100 else (height-marksize)//2,mark)
        if height>100:
            p.setPen(QColor(INK));p.setFont(font(20));p.drawText(QRectF(0,155,width,30),Qt.AlignmentFlag.AlignCenter,'STOOM')
            p.setFont(font(12));p.setPen(QColor('#8299ad'));p.drawText(QRectF(0,188,width,28),Qt.AlignmentFlag.AlignCenter,label or 'STOOM')
        p.end();assert im.save(str(directory/name),'BMP')

css='''@font-face{font-family:STOOM Inter;src:url('./Inter-variable.ttf') format('truetype');font-weight:100 900;font-style:normal;font-display:block}
.stoom-product-mark{box-sizing:border-box;display:inline-grid;place-items:center;width:29px;height:29px;position:relative;flex:0 0 29px;font-family:"STOOM Inter",Inter,sans-serif;font-size:10.5px;font-weight:850;font-variation-settings:"wght" 850,"opsz" 14;font-optical-sizing:none;line-height:1;letter-spacing:0;color:#e3faff}
.stoom-product-mark.stoom-mark{box-sizing:border-box}
.stoom-product-code{position:absolute;inset:0;transform:translateY(2.5px);display:grid;place-items:center;font:inherit;letter-spacing:0}
.stoom-brand-lockup{display:flex;align-items:center;gap:10px}
.stoom-brand-lockup>img{width:48px;height:48px;flex:0 0 48px}
.stoom-brand-word{font-family:"STOOM Inter",Inter,sans-serif;font-size:20px;font-weight:850;font-variation-settings:"wght" 850,"opsz" 14;font-optical-sizing:none;letter-spacing:.11em;line-height:1}
'''
(OUT/'stoom-product-marks.css').write_text(css,encoding='utf-8')
shutil.copy2(Path(__file__),OUT/'build_product_identity.py')
for file in sorted(OUT.rglob('*')):
    if file.is_file() and file.name!='brand-spec.json':spec['files'][file.relative_to(OUT).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
(OUT/'brand-spec.json').write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')

# Inspection sheet: native display sizes and both light/dark surrounding surfaces.
sheet=QImage(1120,600,QImage.Format.Format_RGB32);sheet.fill(QColor('#f5f7fa'))
p=QPainter(sheet);p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setFont(font(18));p.setPen(QColor(BG))
p.drawText(24,30,'STOOM shared product identity: Inter850 / opsz14')
for row,(key,label) in enumerate((('sst','SST'),('pwh','Pwh'))):
    y=64+row*250;p.fillRect(560,y-12,536,218,QColor(BG))
    for start,dark in ((24,False),(584,True)):
        p.setPen(QColor(INK if dark else BG));p.setFont(font(14));p.drawText(start,y+5,label)
        x=start
        for size in (16,20,24,32,48,64,128):
            p.drawImage(x,y+36,image(label,size))
            p.setFont(font(11));p.drawText(x,y+190,str(size))
            x+=max(size+16,48)
p.end();preview=OUT.parent/(OUT.name+'-preview.png');sheet.save(str(preview))
print(json.dumps({'out':str(OUT),'font_family':families,'products':PRODUCTS,'preview':str(preview)},ensure_ascii=True))
