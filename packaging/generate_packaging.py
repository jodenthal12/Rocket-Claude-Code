#!/usr/bin/env python3
# Generates Bloom solar-panel phone case packaging artwork as a vector PDF
# with real OCG layers + axial/radial gradient shadings (opens editable in Illustrator).
import math, struct

MM = 2.834645669  # mm -> pt

# ---------- Helvetica / Helvetica-Bold widths (units/1000) ----------
HELV = {' ':278,'!':278,'"':355,'#':556,'$':556,'%':889,'&':667,"'":191,'(':333,')':333,'*':389,'+':584,',':278,'-':333,'.':278,'/':278,'0':556,'1':556,'2':556,'3':556,'4':556,'5':556,'6':556,'7':556,'8':556,'9':556,':':278,';':278,'<':584,'=':584,'>':584,'?':556,'@':1015,'A':667,'B':667,'C':722,'D':722,'E':667,'F':611,'G':778,'H':722,'I':278,'J':500,'K':667,'L':556,'M':833,'N':722,'O':778,'P':667,'Q':778,'R':722,'S':667,'T':611,'U':722,'V':667,'W':944,'X':667,'Y':667,'Z':611,'[':278,'\\':278,']':278,'^':469,'_':556,'`':333,'a':556,'b':556,'c':500,'d':556,'e':556,'f':278,'g':556,'h':556,'i':222,'j':222,'k':500,'l':222,'m':833,'n':556,'o':556,'p':556,'q':556,'r':333,'s':500,'t':278,'u':556,'v':500,'w':722,'x':500,'y':500,'z':500,'{':334,'|':260,'}':334,'~':584}
HELVB = {' ':278,'!':333,'"':474,'#':556,'$':556,'%':889,'&':722,"'":238,'(':333,')':333,'*':389,'+':584,',':278,'-':333,'.':278,'/':278,'0':556,'1':556,'2':556,'3':556,'4':556,'5':556,'6':556,'7':556,'8':556,'9':556,':':333,';':333,'<':584,'=':584,'>':584,'?':611,'@':975,'A':722,'B':722,'C':722,'D':722,'E':667,'F':611,'G':778,'H':722,'I':278,'J':556,'K':722,'L':611,'M':833,'N':722,'O':778,'P':667,'Q':778,'R':722,'S':667,'T':611,'U':722,'V':667,'W':944,'X':667,'Y':667,'Z':611,'[':333,'\\':278,']':333,'^':584,'_':556,'`':333,'a':556,'b':611,'c':556,'d':611,'e':556,'f':333,'g':611,'h':611,'i':278,'j':278,'k':556,'l':278,'m':889,'n':611,'o':611,'p':611,'q':611,'r':389,'s':556,'t':333,'u':611,'v':556,'w':778,'x':556,'y':556,'z':500}

def textw(s, size, bold=False, tc=0.0):
    t = HELVB if bold else HELV
    w = sum(t.get(c, 556)/1000.0*size for c in s)
    if len(s) > 1: w += tc*(len(s)-1)
    return w

def esc(s):
    s=s.replace('’',"'").replace('‘',"'").replace('“','"').replace('”','"')
    s=s.replace('•','\x95').replace('–','-').replace('—','-')
    s=s.replace('☀','').replace('•','\x95')
    s=''.join(c if ord(c)<256 else '?' for c in s)
    return s.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')

def f(x):
    return ('%.3f' % x).rstrip('0').rstrip('.') if isinstance(x,float) else str(x)

# ---------- PDF object store ----------
class PDF:
    def __init__(self):
        self.objs = {}   # num -> bytes
        self.n = 0
    def alloc(self):
        self.n += 1
        return self.n
    def put(self, num, data):
        if isinstance(data, str): data = data.encode('latin-1')
        self.objs[num] = data
    def add(self, data):
        num = self.alloc(); self.put(num, data); return num
    def stream(self, num, dictstr, content):
        if isinstance(content, str): content = content.encode('latin-1')
        body = ('<<%s /Length %d>>\nstream\n' % (dictstr, len(content))).encode('latin-1')
        body += content + b'\nendstream'
        self.put(num, body)
    def serialize(self):
        out = b'%PDF-1.6\n%\xe2\xe3\xcf\xd3\n'
        offsets = {}
        for i in range(1, self.n+1):
            offsets[i] = len(out)
            out += ('%d 0 obj\n' % i).encode('latin-1') + self.objs[i] + b'\nendobj\n'
        xref_off = len(out)
        out += ('xref\n0 %d\n' % (self.n+1)).encode('latin-1')
        out += b'0000000000 65535 f \n'
        for i in range(1, self.n+1):
            out += ('%010d 00000 n \n' % offsets[i]).encode('latin-1')
        out += ('trailer\n<</Size %d /Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n' % (self.n+1, xref_off)).encode('latin-1')
        return out

pdf = PDF()
ROOT = pdf.alloc()      # 1 catalog
PAGES = pdf.alloc()     # 2 pages

# Fonts
fontN = pdf.add('<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>')
fontB = pdf.add('<</Type/Font/Subtype/Type1/BaseFont/Helvetica-Bold/Encoding/WinAnsiEncoding>>')

# OCG layers (shared)
LAYER_NAMES = ['Background','Brand','Product','Content','Details']
ocg = {}
for nm in LAYER_NAMES:
    ocg[nm] = pdf.add('<</Type/OCG/Name(%s)>>' % nm)
ocg_refs = ' '.join('%d 0 R' % ocg[nm] for nm in LAYER_NAMES)
pdf.put(ROOT, ('<</Type/Catalog/Pages %d 0 R/OCProperties<</D<</Order[%s]/ON[%s]/OFF[]>>/OCGs[%s]>>>>'
    % (PAGES, ocg_refs, ocg_refs, ocg_refs)).encode())

# ---------- Page builder ----------
class Canvas:
    def __init__(self, w, h):
        self.w=w; self.h=h
        self.layers={nm:[] for nm in LAYER_NAMES}
        self.shadings={}   # name -> xref
        self.cur=None
    def layer(self, nm): self.cur=nm; return self
    def _e(self, s): self.layers[self.cur].append(s)

    # ----- gradients -----
    def _func2(self, c0, c1):
        return pdf.add('<</FunctionType 2/Domain[0 1]/C0[%s]/C1[%s]/N 1>>'
            % (' '.join(f(x) for x in c0), ' '.join(f(x) for x in c1)))
    def axial(self, x0,y0,x1,y1, c0,c1, ext=(True,True)):
        fn=self._func2(c0,c1)
        nm='Sh%d'%(len(self.shadings)+1)
        ref=pdf.add('<</ShadingType 2/ColorSpace/DeviceRGB/Coords[%s %s %s %s]/Function %d 0 R/Extend[%s %s]>>'
            %(f(x0),f(y0),f(x1),f(y1),fn,'true' if ext[0] else 'false','true' if ext[1] else 'false'))
        self.shadings[nm]=ref; return nm
    def radial(self, x0,y0,r0,x1,y1,r1, c0,c1, ext=(True,True)):
        fn=self._func2(c0,c1)
        nm='Sh%d'%(len(self.shadings)+1)
        ref=pdf.add('<</ShadingType 3/ColorSpace/DeviceRGB/Coords[%s %s %s %s %s %s]/Function %d 0 R/Extend[%s %s]>>'
            %(f(x0),f(y0),f(r0),f(x1),f(y1),f(r1),fn,'true' if ext[0] else 'false','true' if ext[1] else 'false'))
        self.shadings[nm]=ref; return nm

    # ----- path primitives -----
    def rect(self,x,y,w,h): return '%s %s %s %s re' % (f(x),f(y),f(w),f(h))
    def rrect_path(self,x,y,w,h,r):
        k=0.5523*r
        p=[]
        p.append('%s %s m'%(f(x+r),f(y)))
        p.append('%s %s l'%(f(x+w-r),f(y)))
        p.append('%s %s %s %s %s %s c'%(f(x+w-r+k),f(y),f(x+w),f(y+r-k),f(x+w),f(y+r)))
        p.append('%s %s l'%(f(x+w),f(y+h-r)))
        p.append('%s %s %s %s %s %s c'%(f(x+w),f(y+h-r+k),f(x+w-r+k),f(y+h),f(x+w-r),f(y+h)))
        p.append('%s %s l'%(f(x+r),f(y+h)))
        p.append('%s %s %s %s %s %s c'%(f(x+r-k),f(y+h),f(x),f(y+h-r+k),f(x),f(y+h-r)))
        p.append('%s %s l'%(f(x),f(y+r)))
        p.append('%s %s %s %s %s %s c'%(f(x),f(y+r-k),f(x+r-k),f(y),f(x+r),f(y)))
        p.append('h')
        return ' '.join(p)
    def circle_path(self,cx,cy,r):
        k=0.5523*r
        return (' '.join([
            '%s %s m'%(f(cx+r),f(cy)),
            '%s %s %s %s %s %s c'%(f(cx+r),f(cy+k),f(cx+k),f(cy+r),f(cx),f(cy+r)),
            '%s %s %s %s %s %s c'%(f(cx-k),f(cy+r),f(cx-r),f(cy+k),f(cx-r),f(cy)),
            '%s %s %s %s %s %s c'%(f(cx-r),f(cy-k),f(cx-k),f(cy-r),f(cx),f(cy-r)),
            '%s %s %s %s %s %s c'%(f(cx+k),f(cy-r),f(cx+r),f(cy-k),f(cx+r),f(cy)),'h']))

    # ----- fills -----
    def fill_solid(self,path,c):
        self._e('q %s rg %s f Q'%(' '.join(f(x) for x in c),path))
    def stroke(self,path,c,wd):
        self._e('q %s RG %s w %s S Q'%(' '.join(f(x) for x in c),f(wd),path))
    def fill_grad(self,path,shname):
        self._e('q %s W n /%s sh Q'%(path,shname))
    def line(self,x0,y0,x1,y1,c,wd):
        self._e('q %s RG %s w %s %s m %s %s l S Q'%(' '.join(f(x) for x in c),f(wd),f(x0),f(y0),f(x1),f(y1)))

    # ----- text -----
    def text(self,x,y,s,size,c=(1,1,1),bold=False,tc=0.0):
        fn='F1' if bold else 'F0'
        op='q %s rg BT /%s %s Tf'%(' '.join(f(v) for v in c),fn,f(size))
        if tc: op+=' %s Tc'%f(tc)
        op+=' %s %s Td (%s) Tj ET Q'%(f(x),f(y),esc(s))
        self._e(op)
    def ctext(self,cx,y,s,size,c=(1,1,1),bold=False,tc=0.0):
        w=textw(s,size,bold,tc)
        self.text(cx-w/2,y,s,size,c,bold,tc)

    # ----- sun/solar logo motif -----
    def sun(self,cx,cy,r):
        # radial gold body
        sh=self.radial(cx-r*0.3,cy+r*0.3,0, cx,cy,r, (1.0,0.88,0.45),(0.78,0.50,0.02))
        self.fill_grad(self.circle_path(cx,cy,r),sh)
        # grid lines clipped to circle
        self._e('q %s W n'%self.circle_path(cx,cy,r))
        for dy in (-r*0.5,0,r*0.5):
            self._e('%s %s %s %s %s w %s %s m %s %s l S'%(0.55,0.36,0.0,'',f(r*0.06),f(cx-r),f(cy+dy),f(cx+r),f(cy+dy)))
        for dx in (-r*0.5,0,r*0.5):
            self._e('%s %s %s RG %s w %s %s m %s %s l S'%(0.55,0.36,0.0,f(r*0.06),f(cx+dx),f(cy-r),f(cx+dx),f(cy+r)))
        self._e('Q')
        # rays
        for i in range(8):
            a=i*math.pi/4
            x0=cx+math.cos(a)*r*1.18; y0=cy+math.sin(a)*r*1.18
            x1=cx+math.cos(a)*r*1.45; y1=cy+math.sin(a)*r*1.45
            self.line(x0,y0,x1,y1,(0.96,0.72,0.06),r*0.12)

    def logo(self,cx,cy,scale):
        # "Bl <sun> <sun> m"  centered at cx
        size=46*scale; r=size*0.30
        gap=size*0.06
        wBl=textw('Bl',size,True)
        wm=textw('m',size,True)
        sund=2*r
        total=wBl+gap+sund+gap+sund+gap+wm
        x=cx-total/2
        base=cy-size*0.35
        self.text(x,base,'Bl',size,(1,1,1),True); x+=wBl+gap
        self.sun(x+r,cy,r); x+=sund+gap
        self.sun(x+r,cy,r); x+=sund+gap
        self.text(x,base,'m',size,(1,1,1),True)

    # ----- assemble content -----
    def build_content(self):
        parts=[]
        for nm in LAYER_NAMES:
            if not self.layers[nm]: continue
            parts.append('/OC /%s BDC'%('OC'+nm))
            parts.extend(self.layers[nm])
            parts.append('EMC')
        return '\n'.join(parts)

PAGE_REFS=[]

def make_page(cv):
    cnum=pdf.alloc()
    content=cv.build_content()
    shres=' '.join('/%s %d 0 R'%(k,v) for k,v in cv.shadings.items())
    props=' '.join('/OC%s %d 0 R'%(nm,ocg[nm]) for nm in LAYER_NAMES)
    res=('<</Font<</F0 %d 0 R/F1 %d 0 R>>/Shading<<%s>>/Properties<<%s>>>>'
         %(fontN,fontB,shres,props))
    pnum=pdf.add('<</Type/Page/Parent %d 0 R/MediaBox[0 0 %s %s]/Resources %s/Contents %d 0 R>>'
        %(PAGES,f(cv.w),f(cv.h),res,cnum))
    pdf.stream(cnum,'',content)
    PAGE_REFS.append(pnum)

# ============================================================
# PANEL DIMENSIONS  (phone-case box face 90mm x 175mm)
# ============================================================
W=90*MM; H=175*MM

# small icon helpers --------------------------------------------------
def icon_sun(cv,cx,cy,r,c=(0.96,0.72,0.06)):
    cv.fill_solid(cv.circle_path(cx,cy,r*0.55),c)
    for i in range(8):
        a=i*math.pi/4
        cv.line(cx+math.cos(a)*r*0.75,cy+math.sin(a)*r*0.75,
                cx+math.cos(a)*r*1.05,cy+math.sin(a)*r*1.05,c,r*0.16)
def icon_battery(cv,cx,cy,r,c=(0.96,0.72,0.06)):
    bw=r*1.7; bh=r*1.0
    cv.stroke(cv.rrect_path(cx-bw/2,cy-bh/2,bw,bh,r*0.12),c,r*0.16)
    cv.fill_solid(cv.rect(cx+bw/2,cy-bh*0.22,r*0.18,bh*0.44),c)
    cv.fill_solid(cv.rect(cx-bw/2+r*0.18,cy-bh/2+r*0.18,bw*0.55,bh-r*0.36),c)
def icon_leaf(cv,cx,cy,r,c=(0.24,0.75,0.42)):
    k=0.5523*r
    p=('%s %s m %s %s %s %s %s %s c %s %s %s %s %s %s c h'
       %(f(cx-r*0.7),f(cy-r*0.7), f(cx-r*0.7),f(cy+k), f(cx-k),f(cy+r*0.7), f(cx+r*0.7),f(cy+r*0.7),
         f(cx+r*0.7),f(cy-k), f(cx+k),f(cy-r*0.7), f(cx-r*0.7),f(cy-r*0.7)))
    cv.fill_solid(p,c)
    cv.line(cx-r*0.5,cy-r*0.5,cx+r*0.4,cy+r*0.4,(0.05,0.18,0.10),r*0.12)
def icon_shield(cv,cx,cy,r,c=(0.96,0.72,0.06)):
    p=('%s %s m %s %s l %s %s l %s %s %s %s %s %s c %s %s %s %s %s %s c h'
       %(f(cx),f(cy+r), f(cx+r*0.8),f(cy+r*0.45), f(cx+r*0.8),f(cy-r*0.1),
         f(cx+r*0.8),f(cy-r*0.7), f(cx+r*0.3),f(cy-r*0.95), f(cx),f(cy-r),
         f(cx-r*0.3),f(cy-r*0.95), f(cx-r*0.8),f(cy-r*0.7), f(cx-r*0.8),f(cy-r*0.1)))
    cv.stroke(p,c,r*0.16)
    cv.line(cx-r*0.28,cy-r*0.05,cx-r*0.05,cy-r*0.32,c,r*0.16)
    cv.line(cx-r*0.05,cy-r*0.32,cx+r*0.35,cy+r*0.28,c,r*0.16)

# ============================================================
# FRONT PANEL
# ============================================================
def front():
    cv=Canvas(W,H)
    # --- Background ---
    cv.layer('Background')
    sh=cv.axial(0,H,0,0,(0.09,0.09,0.12),(0.03,0.03,0.05))
    cv.fill_grad(cv.rect(0,0,W,H),sh)
    glow=cv.radial(W/2,H*0.46,0, W/2,H*0.46,H*0.55,(0.40,0.26,0.04),(0.04,0.04,0.06))
    cv.fill_grad(cv.rect(0,0,W,H),glow)
    cv.fill_solid(cv.rect(0,0,W,8),(0.96,0.72,0.06))  # bottom gold bar

    # --- Brand (logo top) ---
    cv.layer('Brand')
    cv.logo(W/2,H-46,0.92)

    # --- Product hero (phone case w/ solar back) ---
    cv.layer('Product')
    cw=86; ch=170; cx0=W/2-cw/2; cy0=H*0.46-ch/2
    body=cv.axial(cx0,cy0+ch,cx0+cw,cy0,(0.20,0.20,0.24),(0.07,0.07,0.09))
    cv.fill_grad(cv.rrect_path(cx0,cy0,cw,ch,14),body)
    cv.stroke(cv.rrect_path(cx0,cy0,cw,ch,14),(0.45,0.45,0.5),0.8)
    # solar panel inset
    ix=cx0+10; iy=cy0+34; iw=cw-20; ih=ch-72
    sol=cv.axial(ix,iy+ih,ix+iw,iy,(1.0,0.85,0.35),(0.72,0.45,0.0))
    cv.fill_grad(cv.rrect_path(ix,iy,iw,ih,6),sol)
    cols=3; rows=6
    for c in range(1,cols):
        cv.line(ix+iw*c/cols,iy+2,ix+iw*c/cols,iy+ih-2,(0.45,0.30,0.0),0.7)
    for r in range(1,rows):
        cv.line(ix+2,iy+ih*r/rows,ix+iw-2,iy+ih*r/rows,(0.45,0.30,0.0),0.7)
    # camera bump
    cbx=cx0+18; cby=cy0+ch-20
    cv.fill_solid(cv.rrect_path(cbx-9,cby-9,30,20,5),(0.05,0.05,0.07))
    cv.fill_solid(cv.circle_path(cbx,cby,4),(0.15,0.16,0.20))
    cv.fill_solid(cv.circle_path(cbx+12,cby,4),(0.15,0.16,0.20))

    # --- Content (taglines) ---
    cv.layer('Content')
    cv.ctext(W/2,H*0.46-ch/2-26,'SOLAR-POWERED PHONE CASE',9.5,(1,1,1),True,2.2)
    cv.ctext(W/2,H*0.46-ch/2-42,'Charge anywhere the sun shines.',8,(0.78,0.78,0.82),False,0.4)

    # --- Details ---
    cv.layer('Details')
    icon_sun(cv,22,H-92,7)
    cv.text(33,H-95,'100% SOLAR',7.5,(0.96,0.72,0.06),True,0.5)
    cv.line(16,H-104,W-16,H-104,(0.30,0.24,0.08),0.6)
    cv.ctext(W/2,22,'bloomcases.com',7,(0.7,0.7,0.74),False,1.0)
    make_page(cv)

# ============================================================
# BACK PANEL
# ============================================================
def back():
    cv=Canvas(W,H)
    cv.layer('Background')
    sh=cv.axial(0,H,0,0,(0.07,0.07,0.10),(0.03,0.03,0.05))
    cv.fill_grad(cv.rect(0,0,W,H),sh)
    glow=cv.radial(W/2,H,0,W/2,H,H*0.4,(0.28,0.19,0.03),(0.05,0.05,0.07))
    cv.fill_grad(cv.rect(0,0,W,H),glow)
    cv.fill_solid(cv.rect(0,0,W,8),(0.96,0.72,0.06))

    cv.layer('Brand')
    cv.logo(W/2,H-40,0.62)

    cv.layer('Content')
    y=H-78
    cv.text(20,y,'WHAT’S INSIDE',11,(0.96,0.72,0.06),True,0.6); y-=18
    for item in ['1x  Bloom Solar Phone Case','1x  USB-C Charging Cable','1x  Quick Start Guide']:
        cv.text(24,y,item,8.5,(0.88,0.88,0.9),False,0.2); y-=14
    y-=10
    cv.text(20,y,'FEATURES',11,(0.96,0.72,0.06),True,0.6); y-=22
    feats=[('sun','Solar charging  •  5W output'),
           ('bat','2000mAh backup battery'),
           ('leaf','Eco-friendly recycled shell'),
           ('shield','Military-grade drop protection')]
    for kind,label in feats:
        if kind=='sun': icon_sun(cv,28,y+3,7)
        elif kind=='bat': icon_battery(cv,28,y+3,7)
        elif kind=='leaf': icon_leaf(cv,28,y+3,7)
        else: icon_shield(cv,28,y+3,7)
        cv.text(42,y,label,8.5,(0.9,0.9,0.92),False,0.2); y-=23

    # tagline band filling mid-panel
    y-=4
    cv.line(20,y+8,W-20,y+8,(0.30,0.24,0.08),0.6)
    cv.ctext(W/2,y-12,'GROW YOUR POWER',13,(0.96,0.72,0.06),True,1.2)
    cv.ctext(W/2,y-28,'Clip on. Soak up the sun. Stay charged',8.5,(0.82,0.82,0.86),False,0.2)
    cv.ctext(W/2,y-40,'all day, naturally.',8.5,(0.82,0.82,0.86),False,0.2)
    cv.line(20,y-52,W-20,y-52,(0.30,0.24,0.08),0.6)

    cv.layer('Details')
    # specs box
    bx=18; bw=W-36; bh=70; by=58
    box=cv.axial(bx,by+bh,bx,by,(0.13,0.13,0.16),(0.08,0.08,0.10))
    cv.fill_grad(cv.rrect_path(bx,by,bw,bh,8),box)
    cv.stroke(cv.rrect_path(bx,by,bw,bh,8),(0.30,0.24,0.08),0.7)
    sy=by+bh-16
    cv.text(bx+12,sy,'SPECIFICATIONS',8,(0.96,0.72,0.06),True,0.8); sy-=14
    for line in ['Battery: 2000mAh Li-Po','Solar output: 5W  /  Port: USB-C','Compatible: iPhone 14 / 15 / 16']:
        cv.text(bx+12,sy,line,7.5,(0.82,0.82,0.85),False,0.1); sy-=11
    # barcode
    import random; random.seed(7)
    bxs=W-72; bw2=54; bh2=22; byb=30
    cv.fill_solid(cv.rect(bxs-5,byb-14,bw2+10,bh2+22),(1,1,1))
    xx=bxs
    while xx<bxs+bw2:
        wd=random.choice([0.7,1.1,1.6,0.9])
        cv.fill_solid(cv.rect(xx,byb,wd,bh2),(0,0,0))
        xx+=wd+random.choice([0.8,1.2,1.6])
    cv.ctext(bxs+bw2/2,byb-10,'8 12345 67890 4',6,(0,0,0),False,0.3)
    cv.text(20,30,'Made with sunlight ☀',7.5,(0.24,0.75,0.42),True,0.3)
    cv.text(20,20,'© 2026 Bloom  •  bloomcases.com',6.5,(0.6,0.6,0.64),False,0.2)
    make_page(cv)

# ============================================================
# SIDE / SPINE PANEL (20mm x 175mm)  -- extra side
# ============================================================
def spine():
    Ws=20*MM; Hs=175*MM
    cv=Canvas(Ws,Hs)
    cv.layer('Background')
    sh=cv.axial(0,Hs,Ws,0,(0.08,0.08,0.11),(0.03,0.03,0.05))
    cv.fill_grad(cv.rect(0,0,Ws,Hs),sh)
    cv.fill_solid(cv.rect(0,0,Ws,5),(0.96,0.72,0.06))
    cv.fill_solid(cv.rect(0,Hs-5,Ws,5),(0.96,0.72,0.06))
    cv.layer('Brand')
    cv.sun(Ws/2,Hs-24,7)
    cv.sun(Ws/2,24,7)
    cv.layer('Content')
    # vertical text via text matrix rotation 90 deg
    s='BLOOM  •  SOLAR PHONE CASE'
    size=12; tw=textw(s,size,True,1.5)
    x=Ws/2+size*0.35; y=Hs/2-tw/2
    cv.layers['Content'].append('q 1 1 1 rg BT /F1 %s Tf %s Tc 0 1 -1 0 %s %s Tm (%s) Tj ET Q'
        %(f(size),f(1.5),f(x),f(y),esc(s)))
    make_page(cv)

front(); back(); spine()

# finalize pages tree
kids=' '.join('%d 0 R'%r for r in PAGE_REFS)
pdf.put(PAGES,('<</Type/Pages/Count %d/Kids[%s]>>'%(len(PAGE_REFS),kids)).encode())

data=pdf.serialize()
open('/tmp/Bloom_Packaging.pdf','wb').write(data)
open('/tmp/Bloom_Packaging.ai','wb').write(data)
print('pages',len(PAGE_REFS),'objects',pdf.n,'bytes',len(data))
