"""Text per page from a PDF. Uses pypdf if it is installed, otherwise a built-in reader (works for normal text PDFs;
scanned pages that are only pictures have no text to read)."""
import re,zlib,io,base64
def pages(data):
    try:
        from pypdf import PdfReader
        r=[re.sub(r'\s+',' ',(p.extract_text() or '')).strip() for p in PdfReader(io.BytesIO(data)).pages]
        if any(r):return r
    except Exception:pass
    try:return _own(data)
    except Exception:return []
def _inflate(s):
    try:return zlib.decompressobj().decompress(s)
    except Exception:return b''
def _stream(d,s):
    m=re.search(rb'/Filter\s*(\[[^\]]*\]|/\w+)',d)
    for f in (re.findall(rb'/(\w+)',m.group(1)) if m else []):
        if f in(b'FlateDecode',b'Fl'):s=_inflate(s)
        elif f in(b'ASCII85Decode',b'A85'):
            t=s.strip()
            t=(t[2:] if t.startswith(b'<~') else t).split(b'~>')[0]
            try:s=base64.a85decode(t)
            except Exception:s=b''
        elif f in(b'ASCIIHexDecode',b'AHx'):
            try:s=bytes.fromhex(re.sub(rb'[^0-9A-Fa-f]',b'',s.split(b'>')[0]).decode())
            except Exception:s=b''
    return s
def _objects(b):
    o={}
    for m in re.finditer(rb'(\d+)\s+\d+\s+obj\b(.*?)endobj',b,re.S):
        body=m.group(2);sm=re.search(rb'stream\r?\n',body)
        if sm:
            d=body[:sm.start()];s=body[sm.end():];e=s.rfind(b'endstream');s=s[:e] if e>=0 else s
            o[int(m.group(1))]=(d,_stream(d,s))
        else:o[int(m.group(1))]=(body,None)
    for n,(d,s) in list(o.items()):
        if s is not None and b'/ObjStm' in d:
            N=int(re.search(rb'/N\s+(\d+)',d).group(1));F=int(re.search(rb'/First\s+(\d+)',d).group(1));h=s[:F].split()
            for i in range(N):
                a=int(h[2*i+1]);z=int(h[2*i+3]) if i+1<N else len(s)-F
                o.setdefault(int(h[2*i]),(s[F+a:F+z],None))
    return o
def _pagelist(o):
    root=next((n for n,(d,s) in o.items() if re.search(rb'/Type\s*/Catalog',d)),None);out=[]
    def walk(n,depth=0):
        d=o[n][0] if n in o else b''
        if re.search(rb'/Type\s*/Pages\b',d) and depth<20:
            k=re.search(rb'/Kids\s*\[(.*?)\]',d,re.S)
            for x in re.findall(rb'(\d+)\s+0\s+R',k.group(1) if k else b''):walk(int(x),depth+1)
        elif n in o:out.append(n)
    if root:
        m=re.search(rb'/Pages\s+(\d+)\s+0\s+R',o[root][0])
        if m:walk(int(m.group(1)))
    return out or sorted(n for n,(d,s) in o.items() if re.search(rb'/Type\s*/Page\b',d))
def _res(o,n):
    for _ in range(8):
        d=o[n][0];m=re.search(rb'/Resources\s*(\d+)\s+0\s+R',d)
        if m:return o[int(m.group(1))][0] if int(m.group(1)) in o else b''
        if b'/Resources' in d:return d
        p=re.search(rb'/Parent\s+(\d+)\s+0\s+R',d)
        if not p or int(p.group(1)) not in o:break
        n=int(p.group(1))
    return b''
def _hex(x):
    x=x.decode();x+='0' if len(x)%2 else '';return bytes.fromhex(x).decode('utf-16-be','ignore')
def _cmap(s):
    if not s:return None
    m={};w=2
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar',s,re.S):
        for a,b in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>',blk):w=len(a)//2;m[int(a,16)]=_hex(b)
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange',s,re.S):
        for lo,hi,rest in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(\[[^\]]*\]|<[0-9A-Fa-f]+>)',blk):
            w=len(lo)//2;l=int(lo,16);h=int(hi,16)
            if rest[:1]==b'[':
                for i,x in enumerate(re.findall(rb'<([0-9A-Fa-f]+)>',rest)):m[l+i]=_hex(x)
            else:
                base=_hex(rest[1:-1])
                for c in range(l,min(h,l+65535)+1):m[c]=(base[:-1]+chr(ord(base[-1])+c-l)) if base else ''
    return (m,w)
def _fonts(o,res):
    m=re.search(rb'/Font\s*(\d+)\s+0\s+R',res)
    fd=o[int(m.group(1))][0] if m and int(m.group(1)) in o else (res[res.find(b'/Font'):] if b'/Font' in res else b'');out={}
    for name,num in re.findall(rb'/([^\s/<>\[\]()]+)\s+(\d+)\s+0\s+R',fd):
        f=o.get(int(num))
        if f is None:continue
        tu=re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R',f[0]);out[name]=_cmap(o[int(tu.group(1))][1]) if tu and int(tu.group(1)) in o else None
    return out
def _dec(b,f):
    if f is None:return b.decode('cp1252','ignore')
    m,w=f;return ''.join(m.get(int.from_bytes(b[i:i+w],'big'),'') for i in range(0,len(b),w))
_TOK=re.compile(rb'\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>%]+|[-+]?\d*\.?\d+|[A-Za-z\'"*]+',re.S)
_NUM=re.compile(rb'[-+]?\d*\.?\d+')
def _lit(t):
    s=t[1:-1];out=bytearray();i=0
    while i<len(s):
        c=s[i]
        if c==92 and i+1<len(s):
            n=s[i+1];i+=2
            if 48<=n<=55:
                v=n-48
                for _ in range(2):
                    if i<len(s) and 48<=s[i]<=55:v=v*8+s[i]-48;i+=1
                out.append(v&255)
            else:out.append({110:10,114:13,116:9,98:8,102:12}.get(n,n))
        else:out.append(c);i+=1
    return bytes(out)
def _content(c,fonts):
    out=[];cur=None;st=[];arr=None
    for m in _TOK.finditer(c):
        t=m.group()
        if t==b'[':arr=[];continue
        if t==b']':
            if arr is not None:st.append(arr)
            arr=None;continue
        if t[:1] in(b'(',b'<'):
            h=re.sub(rb'\s',b'',t[1:-1]) if t[:1]==b'<' else b''
            v=_lit(t) if t[:1]==b'(' else bytes.fromhex(h.decode()+('0' if len(h)%2 else ''))
            (arr if arr is not None else st).append(v);continue
        if arr is not None:
            if _NUM.fullmatch(t):arr.append(float(t))
            continue
        if t[:1]==b'/':st.append(t[1:]);continue
        if _NUM.fullmatch(t):st.append(float(t));continue
        if t==b'Tf' and len(st)>=2:cur=fonts.get(st[-2])
        elif t==b'Tj' and st and isinstance(st[-1],bytes):out.append(_dec(st[-1],cur))
        elif t==b'TJ' and st and isinstance(st[-1],list):
            for x in st[-1]:
                if isinstance(x,bytes):out.append(_dec(x,cur))
                elif x<-200:out.append(' ')
        elif t in(b"'",b'"') and st and isinstance(st[-1],bytes):out.append(' '+_dec(st[-1],cur))
        elif t in(b'Td',b'TD',b'T*',b'Tm',b'ET'):out.append(' ')
        st=[]
    return ''.join(out)
def _own(data):
    o=_objects(data);res=[]
    for n in _pagelist(o):
        d=o[n][0];cs=[];m=re.search(rb'/Contents\s*(\[[^\]]*\]|\d+\s+0\s+R)',d)
        if m:
            for x in re.findall(rb'(\d+)\s+0\s+R',m.group(1)):
                if int(x) in o and o[int(x)][1] is not None:cs.append(o[int(x)][1])
        res.append(re.sub(r'\s+',' ',_content(b'\n'.join(cs),_fonts(o,_res(o,n)))).strip())
    return res
