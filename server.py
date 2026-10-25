#!/usr/bin/env python3
"""Lab Budget Tracker: intranet server. Python 3.8+ only, no extra packages.
Run:  python server.py        (then open http://THIS-PC:7000 )"""
import re,os,json,sqlite3,secrets,hashlib,time,threading,uuid,tempfile
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,quote
HERE=os.path.dirname(os.path.abspath(__file__))
import sys;sys.path.insert(0,HERE)
try:
    from pdftext import pages as pdf_pages
except Exception:
    pdf_pages=lambda d:[]
DB=os.environ.get('BUDGET_DB',os.path.join(HERE,'budget.db'));PORT=int(os.environ.get('PORT','7000'))
VOTES=('27403','27499','DOC');CUR='27403'
MAXF=200*1024*1024
MIMES={'pdf':'application/pdf','doc':'application/msword','docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','xls':'application/vnd.ms-excel','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','ppt':'application/vnd.ms-powerpoint','pptx':'application/vnd.openxmlformats-officedocument.presentationml.presentation','png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','txt':'text/plain','csv':'text/csv','mp4':'video/mp4','webm':'video/webm'}
COOKIE=f'sid{PORT}'
LK=threading.RLock();con=sqlite3.connect(DB,check_same_thread=False);con.row_factory=sqlite3.Row
con.executescript('''CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE,name TEXT,role TEXT,salt TEXT,pw TEXT,active INTEGER DEFAULT 1,fails INTEGER DEFAULT 0,locked REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,uid TEXT,exp REAL);
CREATE TABLE IF NOT EXISTS docs(path TEXT PRIMARY KEY,data TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v INTEGER);
CREATE TABLE IF NOT EXISTS filetext(fid TEXT,page INTEGER,text TEXT);
CREATE INDEX IF NOT EXISTS ft_fid ON filetext(fid);
CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY,name TEXT,mime TEXT,size INTEGER,data BLOB,ts REAL,uid TEXT);
INSERT OR IGNORE INTO meta VALUES('ver',1);''')
def hpw(pw,salt):return hashlib.pbkdf2_hmac('sha256',pw.encode(),bytes.fromhex(salt),200000).hex()
def add_user(un,name,role,pw):
    salt=secrets.token_hex(16);uid=uuid.uuid4().hex
    con.execute('INSERT INTO users(id,username,name,role,salt,pw) VALUES(?,?,?,?,?,?)',(uid,un.strip().lower(),name.strip(),role,salt,hpw(pw,salt)));con.commit();return uid
def bump():con.execute("UPDATE meta SET v=v+1 WHERE k='ver'");con.commit()
def getdoc(p):
    r=con.execute('SELECT data FROM docs WHERE path=?',(CUR+':'+p,)).fetchone();return json.loads(r[0]) if r else None
def allcol(c):
    out=[]
    pre=CUR+':'+c+'/'
    for r in con.execute('SELECT path,data FROM docs WHERE path LIKE ?',(pre+'%',)):
        rest=r[0][len(pre):]
        if '/' not in rest:out.append((rest,json.loads(r[1])))
    return out
def units_of(uid):return (getdoc('members/'+uid) or {}).get('units',[])
def vis(u,col,pid,d):
    if u['role']=='admin':return True
    if u['role']=='staff' and col not in('isodocs','isoacks','handbook','site'):return False
    if col in('handbook','site'):return True
    if col=='isodocs':return d.get('status')=='Approved'
    if col=='isoacks':return pid.startswith(u['id']+'_')
    m=units_of(u['id'])
    if col in('lpos','reqs','warrants','items'):return d.get('unit') in m
    if col=='moves':
        it=getdoc('items/'+str(d.get('item')));return bool(it) and it.get('unit') in m
    if col=='counts':return any(i.get('test')==d.get('test') and i.get('unit') in m for _,i in allcol('items'))
    if col=='config':return True
    if col in('joins','members'):return pid==u['id']
    return False
def may(u,path,op,d,old):
    col,_,pid=path.partition('/')
    if u['role']=='admin':return True
    if col=='joins':return pid==u['id']
    if col=='isoacks':return op=='set' and pid.startswith(u['id']+'_') and d.get('uid')==u['id']
    if op=='delete':return False
    m=units_of(u['id']);mg={**(old or {}),**d}
    if col in('lpos','reqs'):
        if mg.get('unit') not in m or d.get('ack') is True:return False
        if op=='update' and 'st' in d:return False
        if op!='update' and d.get('st') not in(None,'Active','Held','Pending'):return False
        return True
    if col=='moves':
        it=getdoc('items/'+str(mg.get('item')));return bool(it) and it.get('unit') in m
    if col=='counts':return any(i.get('test')==mg.get('test') and i.get('unit') in m for _,i in allcol('items'))
    return False
SAMPLE={'budget':500000,'year':time.localtime().tm_year,'units':[{'n':n,'last':l,'top':0} for n,l in [('Biokimia',120000),('Hematologi',150000),('Mikrobiologi',90000),('Histositologi',60000),('POCT',50000),('General',30000)]]}
with LK:
    if not con.execute('SELECT 1 FROM users').fetchone():
        pw=secrets.token_urlsafe(9);add_user('admin','Administrator','admin',pw)
        print('\n'+'='*60+f'\nFIRST RUN. Sign in with username: admin   password: {pw}\nChange it after signing in (top right).\n'+'='*60+'\n')
    con.execute("UPDATE docs SET path='27403:'||path WHERE path NOT LIKE '%:%'");con.commit()
    for v,b in(('27403',500000),('27499',550000)):
        if con.execute('SELECT 1 FROM docs WHERE path=?',(v+':config/main',)).fetchone() is None:
            con.execute('INSERT INTO docs VALUES(?,?)',(v+':config/main',json.dumps({**SAMPLE,'budget':b})));con.commit()
def newyear(d):
    cfg=getdoc('config/main');old=[u['n'] for u in cfg['units']]
    y=int(d['year']);b=float(d['budget']);U=d['units']
    if y<2000 or b<=0 or [u['n'] for u in U]!=old:raise ValueError('year, budget or unit names are not valid')
    if sum(float(u['last']) for u in U)<=0:raise ValueError('the share basis must be above zero')
    snap={r[0][len(CUR)+1:]:json.loads(r[1]) for r in con.execute('SELECT path,data FROM docs WHERE path LIKE ?',(CUR+':%',))}
    con.execute('CREATE TABLE IF NOT EXISTS archive(id INTEGER PRIMARY KEY AUTOINCREMENT,year INTEGER,ts REAL,data TEXT)')
    con.execute('INSERT INTO archive(year,ts,data) VALUES(?,?,?)',(cfg['year'],time.time(),json.dumps({'vote':CUR,'docs':snap})))
    lp=[v for k,v in snap.items() if k.startswith('lpos/')]
    val=lambda l:float(l['inv']) if l.get('inv') not in(None,'') else float(l.get('lpo') or 0)
    for k,w in [(k,v) for k,v in snap.items() if k.startswith('warrants/')]:
        used=sum(val(l) for l in lp if l.get('src')==k.split('/')[1] and l.get('st')=='Active');left=float(w['amt'])-used
        if left>0.005:w['amt']=round(left,2);con.execute('INSERT OR REPLACE INTO docs VALUES(?,?)',(CUR+':'+k,json.dumps(w)))
        else:con.execute('DELETE FROM docs WHERE path=?',(CUR+':'+k,))
    mv=[(k,v) for k,v in snap.items() if k.startswith('moves/')]
    for c in('lpos','reqs','recon','counts','moves'):con.execute('DELETE FROM docs WHERE path LIKE ?',(CUR+':'+c+'/%',))
    start=f'{y}-01-01';n=0;ts=int(time.time()*1000)
    for k,it in [(k,v) for k,v in snap.items() if k.startswith('items/')]:
        iid=k.split('/')[1];bal=float(it.get('open') or 0);lots={}
        for _,m in sorted([x for x in mv if x[1].get('item')==iid],key=lambda x:x[1].get('ts',0)):
            t=m.get('type');q=float(m.get('qty') or 0)
            if t=='in':
                bal+=q
                if m.get('lk'):
                    o=lots.setdefault(m['lk'],{'lot':m.get('lot'),'exp':m.get('exp'),'rem':0,'val':0,'q':0});o['rem']+=q;o['q']+=q;o['val']+=q*float(m.get('price') or 0)
            elif t in('out','waste'):
                bal-=q
                if m.get('lk') in lots:lots[m['lk']]['rem']-=q
            elif t=='count':bal=q
        keep=[(lk,o) for lk,o in lots.items() if o['rem']>1e-9]
        it['open']=round(max(0,bal-sum(o['rem'] for _,o in keep)),4);con.execute('INSERT OR REPLACE INTO docs VALUES(?,?)',(CUR+':'+k,json.dumps(it)))
        for lk,o in keep:
            n+=1;con.execute('INSERT INTO docs VALUES(?,?)',(CUR+':moves/'+uuid.uuid4().hex[:20],json.dumps({'item':iid,'type':'in','qty':round(o['rem'],4),'price':o['val']/o['q'] if o['q'] else 0,'lpo':'','lot':o['lot'],'exp':o['exp'],'lk':lk,'date':start,'ts':ts+n,'by':'system'})))
    new={**cfg,'year':y,'budget':b,'units':[{'n':u['n'],'last':float(u['last']),'top':0,'res':bool(u.get('res'))} for u in U],'log':[{'d':time.strftime('%Y-%m-%d'),'t':f"New year {y} started. {cfg['year']} records archived."}]}
    con.execute('INSERT OR REPLACE INTO docs VALUES(?,?)',(CUR+':config/main',json.dumps(new)))
class H(BaseHTTPRequestHandler):
    def log_message(self,*a):pass
    def send(self,obj,code=200,ctype='application/json',extra=None):
        b=obj if isinstance(obj,bytes) else json.dumps(obj).encode()
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(b)
    def send_file(self,name,mime,data):
        inl=mime in('application/pdf','image/png','image/jpeg','video/mp4','video/webm');n=len(data);code=200
        hd={'Accept-Ranges':'bytes','Content-Disposition':('inline' if inl else 'attachment')+"; filename*=UTF-8''"+quote(name),'X-Content-Type-Options':'nosniff'}
        m=re.match(r'bytes=(\d*)-(\d*)',self.headers.get('Range') or '')
        if m and (m.group(1) or m.group(2)):
            a=int(m.group(1)) if m.group(1) else max(0,n-int(m.group(2)));b=min(int(m.group(2)),n-1) if (m.group(1) and m.group(2)) else n-1
            if a<=b:data=data[a:b+1];code=206;hd['Content-Range']='bytes %d-%d/%d'%(a,b,n)
        self.send(bytes(data),code=code,ctype=mime,extra=hd)
    def hsearch(self,qs,items):
        terms=[w for w in re.split(r'\s+',qs.lower().strip()) if len(w)>=2][:6];res=[]
        if not terms:return res
        for fid,page,text in con.execute('SELECT fid,page,text FROM filetext'):
            it=items.get(fid)
            if not it:continue
            low=text.lower()
            if all(t in low for t in terms):
                k=low.find(terms[0]);st=max(0,k-70);res.append({**it,'page':page,'snippet':text[st:k+110],'hits':sum(low.count(t) for t in terms)})
        res.sort(key=lambda r:-r['hits']);return res[:60]
    def user(self):
        c=dict(x.strip().split('=',1) for x in self.headers.get('Cookie','').split(';') if '=' in x);t=c.get(COOKIE)
        if not t:return None
        r=con.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.uid WHERE s.token=? AND s.exp>? AND u.active=1',(t,time.time())).fetchone();return dict(r) if r else None
    def body(self):
        n=int(self.headers.get('Content-Length') or 0);return json.loads(self.rfile.read(n) or b'{}') if n<5_000_000 else {}
    def do_GET(self):
        with LK:self.route('GET')
    def do_POST(self):
        with LK:self.route('POST')
    def route(self,m):
        global CUR
        try:
            u=urlparse(self.path);p=u.path;q=parse_qs(u.query);CUR=q.get('vote',['27403'])[0];CUR=CUR if CUR in VOTES else '27403'
            if m=='GET' and p in('/','/index.html'):return self.send(open(os.path.join(HERE,'index.html'),'rb').read(),ctype='text/html; charset=utf-8')
            if m=='GET' and p in('/handbook','/panduan'):return self.send(open(os.path.join(HERE,'handbook.html'),'rb').read(),ctype='text/html; charset=utf-8')
            if m=='GET' and p=='/docs':return self.send(open(os.path.join(HERE,'docs.html'),'rb').read(),ctype='text/html; charset=utf-8')
            if m=='GET' and p=='/xlsx.full.min.js':
                f=os.path.join(HERE,'xlsx.full.min.js')
                return self.send(open(f,'rb').read(),ctype='application/javascript') if os.path.exists(f) else self.send({'error':'none'},404)
            if p=='/api/login' and m=='POST':
                d=self.body();r=con.execute('SELECT * FROM users WHERE username=?',(str(d.get('username','')).strip().lower(),)).fetchone()
                if r and r['locked']>time.time():return self.send({'error':'Too many attempts. Wait 5 minutes.'},429)
                if not r or not r['active'] or hpw(str(d.get('password','')),r['salt'])!=r['pw']:
                    if r:con.execute('UPDATE users SET fails=fails+1,locked=CASE WHEN fails>=4 THEN ? ELSE 0 END WHERE id=?',(time.time()+300,r['id']));con.commit()
                    return self.send({'error':'Wrong username or password.'},401)
                con.execute('UPDATE users SET fails=0,locked=0 WHERE id=?',(r['id'],));t=secrets.token_hex(32)
                con.execute('INSERT INTO sessions VALUES(?,?,?)',(t,r['id'],time.time()+12*3600));con.execute('DELETE FROM sessions WHERE exp<?',(time.time(),));con.commit()
                return self.send({'ok':1},extra={'Set-Cookie':f'{COOKIE}={t}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200'})
            us=self.user()
            if p in('/api/pub','/api/pubfile','/api/pubsearch') and m=='GET':
                CUR='DOC';site=getdoc('site/main') or {}
                if us is None and site.get('public') is False:return self.send({'error':'Sign in required.'},401)
                hosp={i:d for i,d in allcol('handbook') if d.get('aud')=='hospital' and d.get('file')}
                if p=='/api/pub':return self.send({'site':{k:site.get(k) for k in('hospital','contact','public')},'items':[{'id':i,**d} for i,d in hosp.items()]})
                if p=='/api/pubfile':
                    fid=q.get('id',[''])[0];r=con.execute('SELECT name,mime,data FROM files WHERE id=?',(fid,)).fetchone()
                    if not r or not any(d['file']['id']==fid for d in hosp.values()):return self.send({'error':'Not found'},404)
                    return self.send_file(r['name'],r['mime'],r['data'])
                return self.send({'results':self.hsearch(q.get('q',[''])[0],{d['file']['id']:dict(id=i,title=d.get('title'),label=d.get('kind'),kind=d.get('kind'),fid=d['file']['id']) for i,d in hosp.items()})})
            if not us:return self.send({'error':'Sign in required.'},401)
            if p=='/api/hsearch' and m=='GET':
                CUR='DOC';items={}
                if q.get('scope',['handbook'])[0]=='iso':
                    for i,d in allcol('isodocs'):
                        if d.get('file') and (us['role']=='admin' or d.get('status')=='Approved'):items[d['file']['id']]=dict(id=i,title=d.get('title'),label=d.get('no'),kind='ISO',fid=d['file']['id'])
                else:
                    for i,d in allcol('handbook'):
                        if d.get('file'):items[d['file']['id']]=dict(id=i,title=d.get('title'),label=d.get('kind'),kind=d.get('kind'),fid=d['file']['id'])
                return self.send({'results':self.hsearch(q.get('q',[''])[0],items)})
            if p=='/api/upload' and m=='POST':
                if us['role']!='admin':return self.send({'error':'Admin only.'},403)
                n=int(self.headers.get('Content-Length') or 0);nm=q.get('name',['file'])[0][:200];ext=nm.rsplit('.',1)[-1].lower() if '.' in nm else ''
                if ext not in MIMES:return self.send({'error':'File type not allowed. Use PDF, Word, Excel, PowerPoint, image, txt or csv.'},400)
                if n<=0 or n>MAXF:return self.send({'error':'The file is empty or larger than 25 MB.'},400)
                fid=uuid.uuid4().hex;raw=self.rfile.read(n);con.execute('INSERT INTO files VALUES(?,?,?,?,?,?,?)',(fid,nm,MIMES[ext],n,raw,time.time(),us['id']))
                pg=pdf_pages(raw) if ext=='pdf' else []
                for i,t in enumerate(pg,1):
                    if t:con.execute('INSERT INTO filetext VALUES(?,?,?)',(fid,i,t))
                con.commit();return self.send({'id':fid,'name':nm,'size':n,'pages':len(pg),'chars':sum(len(t) for t in pg)})
            if p=='/api/file' and m=='GET':
                r=con.execute('SELECT name,mime,data FROM files WHERE id=?',(q.get('id',[''])[0],)).fetchone()
                if not r:return self.send({'error':'Not found'},404)
                if us['role']!='admin':
                    CUR='DOC'
                    fid=q['id'][0]
                    if not (any(d.get('file',{}).get('id')==fid and d.get('status')=='Approved' for _,d in allcol('isodocs')) or any(d.get('file',{}).get('id')==fid for _,d in allcol('handbook'))):return self.send({'error':'Not allowed.'},403)
                return self.send_file(r['name'],r['mime'],r['data'])
            if p=='/api/logout':
                con.execute('DELETE FROM sessions WHERE uid=?',(us['id'],));con.commit();return self.send({'ok':1},extra={'Set-Cookie':f'{COOKIE}=; Max-Age=0; Path=/'})
            if p=='/api/me':return self.send({'id':us['id'],'name':us['name'],'canEdit':us['role']=='admin','role':us['role'],'username':us['username']})
            if p=='/api/ver':return self.send({'v':con.execute("SELECT v FROM meta WHERE k='ver'").fetchone()[0]})
            if p=='/api/names':
                ids=[i for i in q.get('ids',[''])[0].split(',') if i]
                return self.send({r['id']:{'name':r['name']} for i in ids for r in con.execute('SELECT id,name FROM users WHERE id=?',(i,))})
            if p=='/api/doc' and m=='GET':
                path=q['path'][0];col,_,pid=path.partition('/');d=getdoc(path)
                return self.send({'data':d if d is not None and vis(us,col,pid,d) else None})
            if p=='/api/col' and m=='GET':
                c=q['name'][0]
                if c in('recon','members') and us['role']!='admin':return self.send({'docs':[]})
                return self.send({'docs':[{'id':i,'data':d} for i,d in allcol(c) if vis(us,c,i,d)]})
            if p=='/api/doc' and m=='POST':
                b=self.body();op,path,d=b.get('op'),b.get('path',''),b.get('data') or {}
                if op not in('set','update','add','delete') or not isinstance(d,dict):return self.send({'error':'Bad request'},400)
                if op=='add':path=path+'/'+uuid.uuid4().hex[:20]
                if path.count('/')!=1:return self.send({'error':'Bad path'},400)
                old=getdoc(path)
                if not may(us,path,op,d,old):return self.send({'error':'You are not allowed to do that.'},403)
                if op=='delete':
                    con.execute('DELETE FROM docs WHERE path=?',(CUR+':'+path,))
                    if path.split('/')[0] in('isodocs','handbook') and old and old.get('file'):
                        con.execute('DELETE FROM files WHERE id=?',(old['file']['id'],));con.execute('DELETE FROM filetext WHERE fid=?',(old['file']['id'],))
                else:
                    new=({**(old or {}),**d} if op=='update' else d);con.execute('INSERT OR REPLACE INTO docs VALUES(?,?)',(CUR+':'+path,json.dumps(new)))
                con.commit();bump();return self.send({'id':path.split('/')[1]})
            if p=='/api/password' and m=='POST':
                d=self.body();r=con.execute('SELECT * FROM users WHERE id=?',(us['id'],)).fetchone()
                if hpw(str(d.get('old','')),r['salt'])!=r['pw'] or len(str(d.get('new','')))<8:return self.send({'error':'Wrong current password, or new one is under 8 characters.'},400)
                s=secrets.token_hex(16);con.execute('UPDATE users SET salt=?,pw=? WHERE id=?',(s,hpw(d['new'],s),us['id']));con.commit();return self.send({'ok':1})
            if us['role']!='admin':
                if p=='/api/search':return self.send([])
                return self.send({'error':'Admin only.'},403)
            if p=='/api/search':
                s='%'+q.get('q',[''])[0].lower()+'%'
                return self.send([{'id':r['id'],'name':r['name']} for r in con.execute('SELECT id,name FROM users WHERE active=1 AND (lower(name) LIKE ? OR username LIKE ?) LIMIT 8',(s,s))])
            if p=='/api/users' and m=='GET':
                return self.send({'users':[dict(r) for r in con.execute('SELECT id,username,name,role,active FROM users ORDER BY name')]})
            if p=='/api/users' and m=='POST':
                d=self.body();a=d.get('action')
                if a=='create':
                    if len(str(d.get('password','')))<8 or not str(d.get('username','')).strip() or not str(d.get('name','')).strip():return self.send({'error':'Username, name and a password of 8+ characters are required.'},400)
                    try:add_user(d['username'],d['name'],d.get('role') if d.get('role') in('admin','staff') else 'user',d['password'])
                    except sqlite3.IntegrityError:return self.send({'error':'That username already exists.'},400)
                elif a=='reset':
                    if len(str(d.get('password','')))<8:return self.send({'error':'Password must be 8+ characters.'},400)
                    s=secrets.token_hex(16);con.execute('UPDATE users SET salt=?,pw=?,fails=0,locked=0 WHERE id=?',(s,hpw(d['password'],s),d['id']));con.execute('DELETE FROM sessions WHERE uid=?',(d['id'],))
                elif a=='active':
                    if d['id']==us['id']:return self.send({'error':'You cannot deactivate yourself.'},400)
                    con.execute('UPDATE users SET active=? WHERE id=?',(1 if d.get('active') else 0,d['id']))
                con.commit();return self.send({'ok':1})
            if p=='/api/newyear' and m=='POST':
                try:newyear(self.body());con.commit();bump();return self.send({'ok':1})
                except (ValueError,KeyError,TypeError) as e:con.rollback();return self.send({'error':'Could not start the new year: '+str(e)},400)
            if p=='/api/export':
                docs={r[0][len(CUR)+1:]:json.loads(r[1]) for r in con.execute("SELECT path,data FROM docs WHERE path LIKE ? AND path NOT LIKE ? AND path NOT LIKE ?",(CUR+':%',CUR+':members/%',CUR+':joins/%'))}
                return self.send(json.dumps({'format':'budget-export-1','vote':CUR,'exported':time.strftime('%Y-%m-%d %H:%M'),'docs':docs}).encode(),extra={'Content-Disposition':'attachment; filename=budget-export-'+time.strftime('%Y%m%d')+'.json'})
            if p=='/api/backup':
                f=tempfile.mktemp();b=sqlite3.connect(f);con.backup(b);b.close();data=open(f,'rb').read();os.remove(f)
                return self.send(data,ctype='application/octet-stream',extra={'Content-Disposition':'attachment; filename=budget-backup-'+time.strftime('%Y%m%d')+'.db'})
            self.send({'error':'Not found'},404)
        except Exception as e:con.rollback();self.send({'error':'Server error: '+str(e)},500)
if __name__=='__main__':
    print(f"Lab Budget Tracker (reagents 27403 and consumables 27499) running on port {PORT}. Database: {DB}");ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
