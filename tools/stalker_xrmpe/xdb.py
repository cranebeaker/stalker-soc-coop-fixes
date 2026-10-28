import struct,sys,json
N=4096;F=60;TH=2;N_CHAR=256-TH+F;T=N_CHAR*2-1;R=T-1;MAX_FREQ=0x4000
d_code=[];d_len=[]
def _tables():
    # standard Okumura tables
    counts=[(0,1,3),(1,4,4),(5,8,5),(13,12,6),(25,24,7),(49,16,8)]
    # build via known layout
    dc=[0]*256; dl=[0]*256
    i=0
    spec=[(32,0x00,3),(16,0x01,4),(16,0x02,4),(16,0x03,4),]
    # generate exactly as in lzhuf.c
    code=[0x00]*32+[0x01]*16+[0x02]*16+[0x03]*16+[0x04]*8+[0x05]*8+[0x06]*8+[0x07]*8+[0x08]*8+[0x09]*8+[0x0A]*8+[0x0B]*8
    for v in range(0x0C,0x18): code+=[v]*4
    for v in range(0x18,0x30): code+=[v]*2
    for v in range(0x30,0x40): code+=[v]
    ln=[3]*32+[4]*48+[5]*64+[6]*48+[7]*48+[8]*16
    return code,ln
d_code,d_len=_tables()
assert len(d_code)==256 and len(d_len)==256
def lzhuf_decode(src,outsize):
    freq=[0]*(T+1);prnt=[0]*(T+N_CHAR);son=[0]*T
    for i in range(N_CHAR):
        freq[i]=1;son[i]=i+T;prnt[i+T]=i
    i=0;j=N_CHAR
    while j<=R:
        freq[j]=freq[i]+freq[i+1];son[j]=i;prnt[i]=prnt[i+1]=j;i+=2;j+=1
    freq[T]=0xffff;prnt[R]=0
    st={'pos':0,'buf':0,'len':0}
    def getbit():
        while st['len']<=8:
            b=src[st['pos']] if st['pos']<len(src) else 0;st['pos']+=1
            st['buf']|=b<<(8-st['len']);st['len']+=8
        v=st['buf'];st['buf']=(v<<1)&0xffff;st['len']-=1
        return (v>>15)&1
    def getbyte():
        while st['len']<=8:
            b=src[st['pos']] if st['pos']<len(src) else 0;st['pos']+=1
            st['buf']|=b<<(8-st['len']);st['len']+=8
        v=st['buf'];st['buf']=(v<<8)&0xffff;st['len']-=8
        return v>>8
    def reconst():
        j=0
        for i in range(T):
            if son[i]>=T:
                freq[j]=(freq[i]+1)//2;son[j]=son[i];j+=1
        i=0;j=N_CHAR
        while j<T:
            k=i+1;f=freq[j]=freq[i]+freq[k]
            k=j-1
            while f<freq[k]: k-=1
            k+=1
            freq[k+1:j+1]=freq[k:j];freq[k]=f
            son[k+1:j+1]=son[k:j];son[k]=i
            i+=2;j+=1
        for i in range(T):
            k=son[i]
            if k>=T: prnt[k]=i
            else: prnt[k]=prnt[k+1]=i
    def update(c):
        if freq[R]==MAX_FREQ: reconst()
        c=prnt[c+T]
        while True:
            freq[c]+=1;k=freq[c]
            l=c+1
            if k>freq[l]:
                while k>freq[l+1]: l+=1
                freq[c]=freq[l];freq[l]=k
                i=son[c];prnt[i]=l
                if i<T: prnt[i+1]=l
                j=son[l];son[l]=i
                prnt[j]=c
                if j<T: prnt[j+1]=c
                son[c]=j
                c=l
            c=prnt[c]
            if c==0: break
    def decode_char():
        c=son[R]
        while c<T:
            c+=getbit();c=son[c]
        c-=T;update(c);return c
    def decode_position():
        i=getbyte();c=d_code[i]<<6;j=d_len[i]-2
        while j: i=(i<<1)+getbit();j-=1
        return c|(i&0x3f)
    text=bytearray(b' '*(N+F-1));r=N-F;out=bytearray()
    while len(out)<outsize:
        c=decode_char()
        if c<256:
            out.append(c);text[r]=c;r=(r+1)&(N-1)
        else:
            i=(r-decode_position()-1)&(N-1);j=c-255+TH
            for k in range(j):
                c=text[(i+k)&(N-1)];out.append(c);text[r]=c;r=(r+1)&(N-1)
    return bytes(out[:outsize])

def lzo1x(src,outlen,*,max_output=None):
    # minimal lzo1x decompressor
    # Опциональный предел проверяется ДО роста output; старые callers без него
    # сохраняют прежнюю семантику (outlen исторически не ограничивал декодер).
    out=bytearray();ip=0;n=len(src)
    def check_output(extra):
        if max_output is not None and len(out)+extra>max_output:
            raise ValueError('LZO output exceeds max_output')
    def mlen(base,mask_bits):
        nonlocal ip
        t=base
        if t==0:
            while src[ip]==0: t+=255;ip+=1
            t+=mask_bits+src[ip];ip+=1
        return t
    t=src[ip]
    state=0
    if t>17:
        ip+=1;t-=17;check_output(t);out+=src[ip:ip+t];ip+=t;state=4 if t>=4 else t
    while True:
        t=src[ip];ip+=1
        if t>=64:
            dist=((t>>2)&7)+(src[ip]<<3)+1;ip+=1;ln=(t>>5)-1+2;st=t&3
        elif t>=32:
            ln=t&31
            if ln==0:
                while src[ip]==0: ln+=255;ip+=1
                ln+=31+src[ip];ip+=1
            ln+=2
            d=src[ip]|(src[ip+1]<<8);ip+=2
            dist=(d>>2)+1;st=d&3
        elif t>=16:
            ln=t&7
            if ln==0:
                while src[ip]==0: ln+=255;ip+=1
                ln+=7+src[ip];ip+=1
            ln+=2
            d=src[ip]|(src[ip+1]<<8);ip+=2
            dist=((t&8)<<11)+(d>>2)
            if dist==0: break
            dist+=0x4000;st=d&3
        else:
            if state==0:
                ln=t
                if ln==0:
                    while src[ip]==0: ln+=255;ip+=1
                    ln+=15+src[ip];ip+=1
                ln+=3
                check_output(ln)
                out+=src[ip:ip+ln];ip+=ln;state=4;continue
            elif state==4:
                dist=(t>>2)+(src[ip]<<2)+2049;ip+=1;ln=3;st=t&3
            else:
                dist=(t>>2)+(src[ip]<<2)+1;ip+=1;ln=2;st=t&3
        s=len(out)-dist
        check_output(ln+st)
        for k in range(ln): out.append(out[s+k])
        if st: out+=src[ip:ip+st];ip+=st
        state=st
    return bytes(out)

def tar_members(p):
    f=open(p,'rb');pos=0;m={}
    while True:
        f.seek(pos);h=f.read(512)
        if not h or h[0]==0: break
        name=h[:100].rstrip(b'\0').decode();size=int(h[124:136].strip(b'\0 ') or b'0',8)
        m[name]=(pos+512,size);pos+=512+((size+511)//512)*512
    return m

def index(f,off,size):
    pos=off
    while pos<off+size:
        f.seek(pos);cid,csz=struct.unpack('<II',f.read(8))
        if cid&0x7fffffff==1:
            raw=f.read(csz)
            if cid&0x80000000:
                real=struct.unpack('<I',raw[:4])[0];raw=lzhuf_decode(raw[4:],real)
            break
        pos+=8+csz
    ents=[];i=0
    while i<len(raw):
        bs,rs,cs,crc=struct.unpack_from('<HIII',raw,i)
        if bs<16: raise ValueError('bad entry at %d: %r'%(i,raw[i:i+40]))
        name=raw[i+14:i+bs-2].decode('cp1251');ptr=struct.unpack_from('<I',raw,i+bs-2)[0]
        ents.append((name,rs,cs,ptr));i+=bs+2
    return ents

if __name__=='__main__':
    import os; sys.stdout.reconfigure(encoding='utf-8')
    p=sys.argv[1];mode=sys.argv[2]
    for dbn in ('gamedata.db0','gamedata.db1'):
        dbp=os.path.join(p,dbn);f=open(dbp,'rb');off,size=0,os.path.getsize(dbp);ents=index(f,off,size)
        if mode=='list':
            print('==',dbn,len(ents),'entries')
            for e in ents:
                if len(sys.argv)<4 or sys.argv[3] in e[0]: print(e[0],e[1],e[2],sep='	')
        elif mode=='extract':
            import os; sys.stdout.reconfigure(encoding='utf-8')
            outdir=sys.argv[3];pat=sys.argv[4]
            for name,rs,cs,ptr in ents:
                if rs==0 or not name.endswith(pat): continue
                f.seek(off+ptr);data=f.read(cs)
                if rs!=cs: data=lzo1x(data,rs)
                dst=os.path.join(outdir,dbn,name.replace(chr(92),os.sep))
                os.makedirs(os.path.dirname(dst),exist_ok=True);open(dst,'wb').write(data)
