#!/usr/bin/env python3
"""Load LPOs from the PERUNTUKAN Excel sheet into the Lab Budget Tracker.
Runs on the hospital server. Python 3.8+ only, no extra packages. Nothing leaves the server.

  1. Dry run (writes nothing):   python load_peruntukan.py FILE.xlsx --user admin
  2. Check import_review.csv, fix the Excel sheet if needed, run again.
  3. Load for real:              python load_peruntukan.py FILE.xlsx --user admin --commit

Sheets named 27403 and 27499 are loaded into the Reagents and Consumables votes. Re-running is safe: the same LPO
is overwritten, not duplicated. The unit names in colours.json must already exist in the tracker (Setup tab)."""
import sys,re,csv,json,zipfile,argparse,getpass,datetime,urllib.request,http.cookiejar,hashlib
import xml.etree.ElementTree as ET
M='http://schemas.openxmlformats.org/spreadsheetml/2006/main';RN='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
Q=lambda t:'{%s}%s'%(M,t)
def colnum(ref):
    n=0
    for ch in re.match(r'[A-Z]+',ref).group():n=n*26+ord(ch)-64
    return n-1
class Book:
    def __init__(s,path):
        z=zipfile.ZipFile(path);s.z=z;s.ss=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall(Q('si')):s.ss.append(''.join(t.text or '' for t in si.iter(Q('t'))))
        st=ET.fromstring(z.read('xl/styles.xml'));fills=[]
        for f in st.find(Q('fills')).findall(Q('fill')):
            p=f.find(Q('patternFill'));k='none'
            if p is not None and p.get('patternType') not in(None,'none','gray125'):
                c=p.find(Q('fgColor'))
                if c is not None:
                    if c.get('rgb'):k=c.get('rgb')[-6:].upper()
                    elif c.get('theme') is not None:k='theme'+c.get('theme')
                    elif c.get('indexed') is not None:k='idx'+c.get('indexed')
            fills.append(k)
        s.xf=[]
        for x in st.find(Q('cellXfs')).findall(Q('xf')):
            i=int(x.get('fillId',0));s.xf.append(fills[i] if i<len(fills) else 'none')
        wb=ET.fromstring(z.read('xl/workbook.xml'));rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        tg={r.get('Id'):r.get('Target') for r in rel};s.sheets={}
        for sh in wb.find(Q('sheets')):
            t=tg[sh.get('{%s}id'%RN)];s.sheets[sh.get('name').strip()]=t[1:] if t.startswith('/') else 'xl/'+t
    def rows(s,name):
        for row in ET.fromstring(s.z.read(s.sheets[name])).iter(Q('row')):
            cells={}
            for c in row.findall(Q('c')):
                t=c.get('t');v=c.find(Q('v'));val=None
                if t=='s' and v is not None:val=s.ss[int(v.text)]
                elif t=='inlineStr':val=''.join(x.text or '' for x in c.iter(Q('t')))
                elif v is not None and v.text is not None:
                    try:val=v.text if t in('str','e','b') else float(v.text)
                    except ValueError:val=v.text
                si=int(c.get('s',0));cells[colnum(c.get('r'))]=(val,s.xf[si] if si<len(s.xf) else 'none')
            yield int(row.get('r')),cells
def todate(v):
    if isinstance(v,float) and 20000<v<60000:return datetime.date(1899,12,30)+datetime.timedelta(days=int(v))
    if isinstance(v,str):
        for f in('%d/%m/%Y','%Y-%m-%d','%d-%m-%Y','%d.%m.%Y'):
            try:return datetime.datetime.strptime(v.strip(),f).date()
            except ValueError:pass
    return None
def num(v):return float(v) if isinstance(v,float) else None
def txt(v):
    if v is None:return ''
    return str(int(v)) if isinstance(v,float) and v==int(v) else str(v).strip()
class Api:
    def __init__(s,url,user,pw):
        s.u=url.rstrip('/');s.o=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        s.call('/api/login',{'username':user,'password':pw})
    def call(s,path,body=None):
        r=urllib.request.Request(s.u+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        try:return json.loads(s.o.open(r).read() or b'{}')
        except urllib.error.HTTPError as e:
            raise SystemExit('Server said: '+json.loads(e.read() or b'{}').get('error',str(e.code)))
def main():
    ap=argparse.ArgumentParser();ap.add_argument('file');ap.add_argument('--url',default='http://localhost:8080');ap.add_argument('--user',default='admin')
    ap.add_argument('--year',type=int,default=2026);ap.add_argument('--colours',default='colours.json');ap.add_argument('--out',default='import_review.csv')
    ap.add_argument('--commit',action='store_true');ap.add_argument('--unassigned',default='',help='unit name for rows whose colour is not in colours.json');a=ap.parse_args()
    cmap=json.load(open(a.colours,encoding='utf-8'));cmap={k.upper():v for k,v in cmap.items() if not k.startswith('_')}
    api=Api(a.url,a.user,getpass.getpass('Tracker password for %s: '%a.user));book=Book(a.file);report=[];plan=[]
    for vote in('27403','27499'):
        if vote not in book.sheets:print('Sheet',vote,'not found, skipped.');continue
        units={u['n'] for u in api.call('/api/doc?path=config/main&vote='+vote)['data']['units']}
        need={v for v in cmap.values()}|({a.unassigned} if a.unassigned else set())
        if need-units:raise SystemExit('Vote %s: these units are not in the tracker yet (add them in Setup first): %s'%(vote,', '.join(sorted(need-units))))
        hdr=None;seen={}
        for rn,cells in book.rows(vote):
            g=lambda i:cells.get(i,(None,'none'))[0]
            if hdr is None:
                if txt(g(0)).lower()=='tarikh' and txt(g(1)).lower()=='perihal':
                    h=[txt(cells[i][0]).lower() if i in cells else '' for i in range(max(cells)+1)]
                    f=lambda *k:next((i for i,x in enumerate(h) if any(w in x for w in k) and 'dummy' not in x),None)
                    hdr=dict(d=0,s=1,lo=f('lo'),t=f('tanggungan'),b=f('sebenar'))
                    if None in hdr.values():raise SystemExit('Sheet %s: could not find the columns Tarikh, Perihal, No LO, Tanggungan, Sebenar.'%vote)
                continue
            sup=txt(g(hdr['s']));t=num(g(hdr['t']));b=num(g(hdr['b']))
            if not sup or (t is None and b is None):continue
            fills=[cells[i][1] for i in range(0,9) if i in cells];fills+=['none']*(9-len(fills))
            fk=max(set(fills),key=fills.count);rem=' '.join(txt(cells[i][0]) for i in sorted(cells) if i>hdr['b']+1 and cells[i][0] not in(None,'')).strip()
            lo=txt(g(hdr['lo']));d=todate(g(0));unit=cmap.get(fk) or a.unassigned
            row=dict(vote=vote,row=rn,lo=lo,sup=sup,date=str(d or txt(g(0))),amt=(t or 0)+(b or 0),unit=unit or '('+fk+')',rem=rem,st='',why='')
            low=rem.lower()
            if 'batal' in low or 'redundant' in low:row.update(st='skipped',why='marked cancelled or redundant in remarks')
            elif not lo:row.update(st='skipped',why='no LO number')
            elif not unit:row.update(st='skipped',why='colour %s is not in colours.json'%fk)
            elif d is None:row.update(st='skipped',why='date missing or not a date')
            elif d.year!=a.year:row.update(st='skipped',why='date is not in %d'%a.year)
            else:
                key=(lo,t,b)
                if key in seen:row.update(st='skipped',why='same LO number and amounts as row %d (double entry?)'%seen[key])
                else:
                    seen[key]=rn;n=sum(1 for p in plan if p['vote']==vote and p['lo']==lo)
                    did='i%s_%s%s'%(vote[-2:],re.sub(r'[^A-Za-z0-9]','',lo),'' if n==0 else '_%d'%(n+1))
                    doc=dict(no=lo,date=d.isoformat(),unit=unit,sup=sup,item=rem,lpo=(t if t is not None else b),inv=(b if b is not None else None),ack=True,by='import',src='budget',st='Active')
                    plan.append(dict(vote=vote,lo=lo,id=did,doc=doc));row.update(st='to load' if not a.commit else 'loaded',why='repeated LO number with a different amount' if n else '')
            report.append(row)
    with open(a.out,'w',newline='',encoding='utf-8-sig') as fh:
        w=csv.writer(fh);w.writerow(['vote','excel row','LO number','supplier','date as read','amount RM','section','remarks','result','reason']);[w.writerow([r[k] for k in('vote','row','lo','sup','date','amt','unit','rem','st','why')]) for r in report]
    for vote in('27403','27499'):
        R=[r for r in report if r['vote']==vote]
        if R:print('\nVote %s: %d rows read, %d to load (RM %s), %d need attention'%(vote,len(R),sum(1 for r in R if r['st']!='skipped'),format(sum(r['amt'] for r in R if r['st']!='skipped'),',.2f'),sum(1 for r in R if r['st']=='skipped')))
    if a.commit:
        for p in plan:api.call('/api/doc?vote='+p['vote'],{'op':'set','path':'lpos/'+p['id'],'data':p['doc']})
        print('\nLoaded %d LPOs.'%len(plan))
    else:print('\nDRY RUN: nothing was written. Review %s, then add --commit to load.'%a.out)
    print('Review file:',a.out)
if __name__=='__main__':main()
