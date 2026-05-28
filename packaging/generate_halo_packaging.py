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
    s=s.replace(''',"'").replace(''',"'").replace('"','"').replace('"','"')
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

    # ----- ellipse + halo-ring logo motif -----
    def ellipse_path(self,cx,cy,rx,ry):
        kx=0.5523*rx; ky=0.5523*ry
        return ' '.join([
            '%s %s m'%(f(cx+rx),f(cy)),
            '%s %s %s %s %s %s c'%(f(cx+rx),f(cy+ky),f(cx+kx),f(cy+ry),f(cx),f(cy+ry)),
            '%s %s %s %s %s %s c'%(f(cx-kx),f(cy+ry),f(cx-rx),f(cy+ky),f(cx-rx),f(cy)),
            '%s %s %s %s %s %s c'%(f(cx-rx),f(cy-ky),f(cx-kx),f(cy-ry),f(cx),f(cy-ry)),
            '%s %s %s %s %s %s c'%(f(cx+kx),f(cy-ry),f(cx+rx),f(cy-ky),f(cx+rx),f(cy)),'h'])

    def ring(self,cx,cy,rx,ry):
        amber=(0.96,0.62,0.10)
        dark=(0.10,0.09,0.08)
        # outer amber halo ellipse w/ radial sheen
        sh=self.radial(cx-rx*0.2,cy+ry*0.3,0, cx,cy,rx, (1.0,0.78,0.30),(0.85,0.48,0.04))
        self.fill_grad(self.ellipse_path(cx,cy,rx,ry),sh)
        # dark inner lens
        self.fill_solid(self.ellipse_path(cx,cy,rx*0.80,ry*0.50),dark)
        # central amber bar splits lens into two dark "eyes"
        self.fill_solid(self.ellipse_path(cx,cy,rx*0.16,ry*0.50),amber)

    def logo(self,cx,cy,scale):
        # "HAL" bold amber + halo-ring "O"
        size=46*scale
        amber=(0.96,0.62,0.10)
        dark=(0.10,0.09,0.08)
        s='HAL'
        wHAL=textw(s,size,True)
        rx=size*0.40; ry=size*0.30
        gap=size*0.04
        total=wHAL+gap+2*rx
        x=cx-total/2
        base=cy-size*0.35
        # dark drop shadow for 3D gaming look
        self.text(x+size*0.05,base-size*0.05,s,size,dark,True)
        self.text(x,base,s,size,amber,True)
        x+=wHAL+gap
        self.ring(x+rx,cy,rx,ry)


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

# small icon helpers (gaming) ---------------------------------------
AMBER=(0.96,0.62,0.10)
def icon_battery(cv,cx,cy,r,c=AMBER):
    bw=r*1.7; bh=r*1.0
    cv.stroke(cv.rrect_path(cx-bw/2,cy-bh/2,bw,bh,r*0.12),c,r*0.16)
    cv.fill_solid(cv.rect(cx+bw/2,cy-bh*0.22,r*0.18,bh*0.44),c)
    cv.fill_solid(cv.rect(cx-bw/2+r*0.18,cy-bh/2+r*0.18,bw*0.55,bh-r*0.36),c)
def icon_pad(cv,cx,cy,r,c=AMBER):
    # gamepad outline with d-pad + 2 buttons
    bw=r*2.0; bh=r*1.1
    cv.stroke(cv.rrect_path(cx-bw/2,cy-bh/2,bw,bh,r*0.5),c,r*0.16)
    # d-pad (left)
    dx=cx-r*0.55
    cv.fill_solid(cv.rect(dx-r*0.32,cy-r*0.10,r*0.64,r*0.20),c)
    cv.fill_solid(cv.rect(dx-r*0.10,cy-r*0.32,r*0.20,r*0.64),c)
    # buttons (right)
    bxr=cx+r*0.55
    cv.fill_solid(cv.circle_path(bxr+r*0.22,cy,r*0.14),c)
    cv.fill_solid(cv.circle_path(bxr-r*0.22,cy,r*0.14),c)
    cv.fill_solid(cv.circle_path(bxr,cy+r*0.22,r*0.14),c)
    cv.fill_solid(cv.circle_path(bxr,cy-r*0.22,r*0.14),c)
def icon_bolt(cv,cx,cy,r,c=AMBER):
    p=('%s %s m %s %s l %s %s l %s %s l %s %s l %s %s l h'
       %(f(cx+r*0.15),f(cy+r), f(cx-r*0.5),f(cy-r*0.1), f(cx-r*0.05),f(cy-r*0.1),
         f(cx-r*0.2),f(cy-r), f(cx+r*0.5),f(cy+r*0.15), f(cx+r*0.05),f(cy+r*0.15)))
    cv.fill_solid(p,c)
def icon_fan(cv,cx,cy,r,c=AMBER):
    cv.stroke(cv.circle_path(cx,cy,r*0.95),c,r*0.14)
    for i in range(4):
        a=i*math.pi/2+0.5
        x1=cx+math.cos(a)*r*0.15; y1=cy+math.sin(a)*r*0.15
        x2=cx+math.cos(a+0.9)*r*0.75; y2=cy+math.sin(a+0.9)*r*0.75
        x3=cx+math.cos(a)*r*0.75; y3=cy+math.sin(a)*r*0.75
        cv.fill_solid('%s %s m %s %s l %s %s l h'%(f(x1),f(y1),f(x2),f(y2),f(x3),f(y3)),c)
    cv.fill_solid(cv.circle_path(cx,cy,r*0.14),c)
def icon_shield(cv,cx,cy,r,c=AMBER):
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
    sh=cv.axial(0,H,0,0,(0.09,0.08,0.07),(0.03,0.03,0.04))
    cv.fill_grad(cv.rect(0,0,W,H),sh)
    glow=cv.radial(W/2,H*0.46,0, W/2,H*0.46,H*0.55,(0.42,0.28,0.06),(0.04,0.04,0.05))
    cv.fill_grad(cv.rect(0,0,W,H),glow)
    cv.fill_solid(cv.rect(0,0,W,8),AMBER)  # bottom amber bar

    # --- Brand (logo top) ---
    cv.layer('Brand')
    cv.logo(W/2,H-46,0.92)

    # --- Product hero (gaming handheld: phone + controller grips) ---
    cv.layer('Product')
    midy=H*0.45
    # central phone screen
    pw=44; ph=120; px=W/2-pw/2; py=midy-ph/2
    # grip wings (left + right)
    gw=26; gh=78
    for sgn in (-1,1):
        gx=W/2+sgn*(pw/2)-(0 if sgn<0 else gw)
        gx=(px-gw+4) if sgn<0 else (px+pw-4)
        grip=cv.axial(gx,py+gh,gx+gw,py,(0.22,0.22,0.26),(0.09,0.09,0.11))
        cv.fill_grad(cv.rrect_path(gx,midy-gh/2,gw,gh,12),grip)
        cv.stroke(cv.rrect_path(gx,midy-gh/2,gw,gh,12),(0.40,0.40,0.46),1.0)
    # phone body
    body=cv.axial(px,py+ph,px+pw,py,(0.16,0.16,0.19),(0.06,0.06,0.08))
    cv.fill_grad(cv.rrect_path(px,py,pw,ph,8),body)
    cv.stroke(cv.rrect_path(px,py,pw,ph,8),(0.45,0.45,0.5),1.2)
    # screen with game-glow
    sx=px+4; sy=py+8; sw=pw-8; sh2=ph-16
    scr=cv.axial(sx,sy+sh2,sx+sw,sy,(0.10,0.30,0.55),(0.55,0.20,0.45))
    cv.fill_grad(cv.rrect_path(sx,sy,sw,sh2,4),scr)
    # HUD bits on screen
    cv.fill_solid(cv.rect(sx+4,sy+sh2-8,sw*0.4,3),(1,1,1))
    cv.fill_solid(cv.rect(sx+4,sy+sh2-14,sw*0.25,3),AMBER)
    cv.fill_solid(cv.circle_path(sx+sw*0.5,sy+sh2*0.45,7),(1,1,1))
    # LEFT controls: d-pad + analog stick
    lcx=px-gw/2+2
    cv.fill_solid(cv.rect(lcx-5,midy+14,10,4),(0.55,0.55,0.6))
    cv.fill_solid(cv.rect(lcx-2,midy+11,4,10),(0.55,0.55,0.6))
    cv.fill_solid(cv.circle_path(lcx,midy-12,6),(0.30,0.30,0.35))
    cv.fill_solid(cv.circle_path(lcx,midy-12,3.5),AMBER)
    # RIGHT controls: 4 face buttons + analog stick
    rcx=px+pw+gw/2-2
    cv.fill_solid(cv.circle_path(rcx+5,midy+16,3),AMBER)
    cv.fill_solid(cv.circle_path(rcx-5,midy+16,3),AMBER)
    cv.fill_solid(cv.circle_path(rcx,midy+21,3),AMBER)
    cv.fill_solid(cv.circle_path(rcx,midy+11,3),AMBER)
    cv.fill_solid(cv.circle_path(rcx,midy-12,6),(0.30,0.30,0.35))
    cv.fill_solid(cv.circle_path(rcx,midy-12,3.5),AMBER)
    # shoulder triggers
    cv.fill_solid(cv.rrect_path(px-gw+2,midy+gh/2-4,gw-2,7,3),(0.30,0.30,0.35))
    cv.fill_solid(cv.rrect_path(px+pw,midy+gh/2-4,gw-2,7,3),(0.30,0.30,0.35))

    # --- Content (taglines) ---
    cv.layer('Content')
    cv.ctext(W/2,midy-ph/2-26,'GAMING PHONE CASE',9.5,(1,1,1),True,2.2)
    cv.ctext(W/2,midy-ph/2-42,'Turn your phone into a console.',8,(0.80,0.78,0.74),False,0.4)

    # --- Details ---
    cv.layer('Details')
    icon_pad(cv,24,H-92,7)
    cv.text(38,H-95,'PLUG & PLAY',7.5,AMBER,True,0.5)
    cv.line(16,H-104,W-16,H-104,(0.30,0.24,0.08),0.6)
    make_page(cv)

# ============================================================
# BACK PANEL
# ============================================================
def back():
    cv=Canvas(W,H)
    cv.layer('Background')
    sh=cv.axial(0,H,0,0,(0.07,0.06,0.06),(0.03,0.03,0.04))
    cv.fill_grad(cv.rect(0,0,W,H),sh)
    glow=cv.radial(W/2,H,0,W/2,H,H*0.4,(0.30,0.20,0.04),(0.05,0.05,0.06))
    cv.fill_grad(cv.rect(0,0,W,H),glow)
    cv.fill_solid(cv.rect(0,0,W,8),AMBER)

    cv.layer('Brand')
    cv.logo(W/2,H-40,0.62)

    cv.layer('Content')
    # top section: what's inside
    y=H-78
    cv.text(20,y,"WHAT'S INSIDE",11,AMBER,True,0.6); y-=18
    for item in ['1x  HALO Gaming Case','1x  USB-C Cable','1x  Quick Start Guide']:
        cv.text(24,y,item,8.5,(0.88,0.88,0.9),False,0.2); y-=14
    y-=12
    # features
    cv.text(20,y,'FEATURES',11,AMBER,True,0.6); y-=20
    feats=[('pad','Console-grade controls'),
           ('bolt','Ultra-low-latency triggers'),
           ('fan','Active cooling fan'),
           ('shield','Drop-proof grip shell')]
    for kind,label in feats:
        if kind=='pad': icon_pad(cv,28,y+3,7)
        elif kind=='bolt': icon_bolt(cv,28,y+3,7)
        elif kind=='fan': icon_fan(cv,28,y+3,7)
        else: icon_shield(cv,28,y+3,7)
        cv.text(42,y,label,8.5,(0.9,0.9,0.92),False,0.2); y-=20

    # tagline immediately below features
    y-=2
    cv.line(20,y,W-20,y,(0.30,0.24,0.08),0.6); y-=18
    cv.ctext(W/2,y,'GAME ANYWHERE',13,AMBER,True,1.2); y-=16
    cv.ctext(W/2,y,'Snap on the grips and play. Built',8.5,(0.84,0.82,0.78),False,0.2); y-=13
    cv.ctext(W/2,y,'for serious mobile gamers.',8.5,(0.84,0.82,0.78),False,0.2); y-=14
    cv.line(20,y,W-20,y,(0.30,0.24,0.08),0.6)

    cv.layer('Details')
    # specs box immediately below tagline
    bx=18; bw=W-36; bh=72; by=y-bh-10
    box=cv.axial(bx,by+bh,bx,by,(0.13,0.12,0.11),(0.08,0.08,0.08))
    cv.fill_grad(cv.rrect_path(bx,by,bw,bh,8),box)
    cv.stroke(cv.rrect_path(bx,by,bw,bh,8),(0.30,0.24,0.08),0.7)
    sy=by+bh-14
    cv.text(bx+12,sy,'SPECIFICATIONS',8,AMBER,True,0.8); sy-=14
    for line in ['Connection: USB-C plug-in','Buttons: D-pad, 4x ABXY, dual sticks','Triggers: L/R analog shoulder','Compatible: iPhone 17 Pro Max']:
        cv.text(bx+12,sy,line,7.5,(0.82,0.82,0.85),False,0.1); sy-=12
    cv.text(bx+12,by-14,'Level up your phone',7.5,AMBER,True,0.3)
    make_page(cv)

front(); back()

# finalize pages tree
kids=' '.join('%d 0 R'%r for r in PAGE_REFS)
pdf.put(PAGES,('<</Type/Pages/Count %d/Kids[%s]>>'%(len(PAGE_REFS),kids)).encode())

data=pdf.serialize()
open('/tmp/HALO_Packaging.pdf','wb').write(data)
open('/tmp/HALO_Packaging.ai','wb').write(data)
print('pages',len(PAGE_REFS),'objects',pdf.n,'bytes',len(data))
