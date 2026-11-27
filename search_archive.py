"""Local authenticated persistent witnesses, bitset indexes and scoped proof records.

This cache has its own per-user integrity key. It never uses or changes the
Ed25519 release signing key. Cached data is private derived data, not a release asset.
"""
import collections,copy,hashlib,hmac,json,os,sqlite3,threading,time,zlib
from pathlib import Path
from activation import attained,scoped_attained
from candidate_pool import condition_key as raw_condition_key
from candidate_groups import armor_key
from calculation_identity import SCHEMA_VERSION,calculation_identity,source_identity

def canonical(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def condition_key(req):
 # Normalize only semantics that are already guaranteed by the shared request
 # contract. Empty owned/candidate/cuff restrictions are deliberately retained.
 from external import normalize
 value=copy.deepcopy(req);external=normalize(value.get('external'))
 if external['meal']=='none':external['quality']=0
 if not any(external['road'].values()):external['road_floor']=1
 value['external']=external
 if value.get('search_mode')=='automatic':
  value['armor']={};value.pop('cuffs',None);value['weapon']={'sigils':value.get('weapon',{}).get('sigils',0)}
  value['auto_weapon']=True;value['integrated_weapon']=True;value.setdefault('g_poogie',True);value.setdefault('premium_poogie_clothes',True);value.setdefault('g_armor_only',False)
 for key in ('exclude','exclude_classes','armor_candidates','jewel_limits','cuff_limits','min_stats'):
  if key in value and not value[key]:value.pop(key)
 for key in ('exclude','exclude_classes'):
  if key in value:value[key]=sorted(set(value[key]))
 if 'zenith_sources' in value:value['zenith_sources']={k:sorted(set(v)) for k,v in value['zenith_sources'].items()}
 return raw_condition_key(value)

def build_identity(build):
 b=copy.deepcopy(build)
 for a in list(b.get('armor',{}).values())+[b.get('weapon',{})]:
  if 'jewels' in a:a['jewels']=sorted(a['jewels'])
 b['cuffs']=sorted(b.get('cuffs',[]));return hashlib.sha256(canonical(b).encode()).hexdigest()

def requirements_dominate(required,core):
 return all(sid in required and ((required[sid]<=pt if pt<0 else required[sid]>=pt) and (required[sid]<0)==(pt<0)) for sid,pt in core.items())

SCHEMA='''
CREATE TABLE IF NOT EXISTS archive_meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS pattern(id INTEGER PRIMARY KEY,signature TEXT UNIQUE,attained TEXT,tag TEXT);
CREATE TABLE IF NOT EXISTS witness(id INTEGER PRIMARY KEY,identity TEXT UNIQUE,pattern_id INTEGER,armor_key TEXT,features TEXT,payload BLOB,payload_hash TEXT,tag TEXT);
CREATE INDEX IF NOT EXISTS witness_pattern ON witness(pattern_id,armor_key);
CREATE TABLE IF NOT EXISTS scope(id TEXT PRIMARY KEY,request TEXT,exportable INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS membership(scope_id TEXT,witness_id INTEGER,tag TEXT,PRIMARY KEY(scope_id,witness_id));
CREATE INDEX IF NOT EXISTS membership_witness ON membership(witness_id,scope_id);
CREATE TABLE IF NOT EXISTS posting(pattern_id INTEGER,skill TEXT,points INTEGER,PRIMARY KEY(pattern_id,skill));
CREATE INDEX IF NOT EXISTS posting_skill ON posting(skill,points,pattern_id);
CREATE TABLE IF NOT EXISTS proof(id INTEGER PRIMARY KEY,scope_id TEXT,core TEXT,certificate TEXT,tag TEXT,UNIQUE(scope_id,core));
CREATE INDEX IF NOT EXISTS proof_scope ON proof(scope_id);
CREATE TABLE IF NOT EXISTS attempt(scope_id TEXT,required TEXT,status TEXT,updated REAL,tag TEXT,PRIMARY KEY(scope_id,required));
CREATE TABLE IF NOT EXISTS work(id TEXT PRIMARY KEY,scope_id TEXT,context TEXT,request TEXT,state TEXT,attempts INTEGER DEFAULT 0,next_after REAL DEFAULT 0,last_status TEXT,updated REAL);
CREATE INDEX IF NOT EXISTS work_pending ON work(scope_id,state,next_after);
'''

class ArchiveIndex:
 def __init__(self,rows,patterns):
  self.rows=rows;self.postings=collections.defaultdict(dict);self.groups=collections.defaultdict(list);self.orders={}
  buffers={};size=(len(rows)+7)//8
  for i,r in enumerate(rows):
   self.groups[r['armor_key']].append(i)
   for sid,pt in patterns[r.get('index_pattern',r['pattern_id'])].items():
    key=(sid,pt)
    if key not in buffers:buffers[key]=bytearray(size)
    buffers[key][i>>3]|=1<<(i&7)
  for (sid,pt),buffer in buffers.items():self.postings[sid][pt]=int.from_bytes(buffer,'little')
  self.all=(1<<len(rows))-1
 def skill_mask(self,sid,pt):
  mask=0
  for value,bits in self.postings.get(sid,{}).items():
   if value<=pt if pt<0 else value>=pt:mask|=bits
  return mask
 def mask(self,required):
  mask=self.all
  for sid,pt in required.items():mask&=self.skill_mask(sid,pt)
  return mask
 def positions(self,mask):
  for block,value in enumerate(mask.to_bytes((len(self.rows)+7)//8,'little')):
   while value:
    low=value&-value;yield block*8+low.bit_length()-1;value^=low
 def group_count(self,mask,key):return sum(bool(mask&(1<<i)) for i in self.groups.get(key,()))


class SearchArchive:
 @property
 def db(self):
  if getattr(self,'_closed',False):raise sqlite3.InterfaceError('calculation archive is closed')
  if self._db is None:
   self._db=sqlite3.connect(self.path,timeout=15,check_same_thread=False);self._db.row_factory=sqlite3.Row;self._db.execute('PRAGMA synchronous=NORMAL');self._db.execute('PRAGMA mmap_size=268435456')
  return self._db
 @db.setter
 def db(self,value):self._db=value
 def park(self):
  # No open cache handle is needed while the app is waiting for user input.
  # Keep the authenticated in-memory index, but release SQLite file locks.
  with self.lock:
   if self._db is not None:self._db.close();self._db=None
 def invalidate_scope(self,req):
  with self.lock:
   self.db.execute('DELETE FROM membership WHERE scope_id=?',(condition_key(req),));self.touch();self.db.commit()
 def contains_build(self,req,build):
  try:identity=build_identity(build)
  except (ValueError,KeyError,TypeError,AttributeError):return False
  return any(r['identity']==identity for r in self._index(req).rows)
 def __init__(self,source,path):
  self.source=Path(source);self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  self.identity=source_identity(self.source);self.calculation=calculation_identity();self.lock=threading.RLock();self.indices=collections.OrderedDict();self.fact_state='unprepared';self.fact_stats=None
  key_path=self.path.with_suffix('.integrity-key')
  try:
   fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
   with os.fdopen(fd,'wb') as f:f.write(os.urandom(32))
  except FileExistsError:pass
  self.key=key_path.read_bytes()
  if len(self.key)!=32:raise ValueError('invalid local calculation-cache integrity key')
  self.db=sqlite3.connect(self.path,timeout=15,check_same_thread=False);self.db.row_factory=sqlite3.Row
  self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=NORMAL');self.db.execute('PRAGMA mmap_size=268435456');self.db.executescript(SCHEMA)
  if 'context' not in {r[1] for r in self.db.execute('PRAGMA table_info(work)')}:self.db.execute('ALTER TABLE work ADD COLUMN context TEXT')
  if 'exportable' not in {r[1] for r in self.db.execute('PRAGMA table_info(scope)')}:self.db.execute('ALTER TABLE scope ADD COLUMN exportable INTEGER DEFAULT 0')
  old=self.db.execute("SELECT value FROM archive_meta WHERE key='identity'").fetchone();generation=canonical([SCHEMA_VERSION,self.identity,self.calculation])
  if old and old[0]!=generation:
   for table in ('pattern','witness','scope','membership','posting','proof','work','attempt'):self.db.execute('DELETE FROM '+table)
  self.db.execute("UPDATE work SET state='unknown' WHERE state='running'")
  self.db.execute("INSERT OR REPLACE INTO archive_meta VALUES('identity',?)",(generation,));self.db.execute("INSERT OR IGNORE INTO archive_meta VALUES('revision','0')");self.db.commit()
  self.facts_path=self.path.with_suffix('.facts.sqlite');self.fact_manifest=self.path.with_suffix('.facts-auth.json');self.fact_connection=None;self.fact_stamp=None;self.bounds_cache=None;self.maxslots=None;self.coverage_cache={}
 def tag(self,value):return hmac.new(self.key,(self.identity+'|'+self.calculation+'|'+canonical(value)).encode(),hashlib.sha256).hexdigest()
 def valid(self,value,tag):return hmac.compare_digest(self.tag(value),tag or '')
 def revision(self):return int(self.db.execute("SELECT value FROM archive_meta WHERE key='revision'").fetchone()[0])
 def touch(self):self.db.execute("UPDATE archive_meta SET value=CAST(value AS INTEGER)+1 WHERE key='revision'");self.indices.clear()
 def _scope(self,req):
  key=condition_key(req);self.db.execute('INSERT OR IGNORE INTO scope(id,request) VALUES(?,?)',(key,canonical({k:v for k,v in req.items() if not k.startswith('_')})));return key
 def ingest(self,req,hits,exportable=False):
  with self.lock:
   scope=self._scope(req);changed=False
   if exportable:
    if any(k in req for k in ('inventory','owned_weapons')):raise ValueError('cannot mark personal scope exportable')
    self.db.execute('UPDATE scope SET exportable=1,request=? WHERE id=?',(canonical({k:v for k,v in req.items() if not k.startswith('_')}),scope))
   for hit in hits:
    if not hit.get('evaluation',{}).get('valid'):continue
    # Calls originate only after independent validation; restored untrusted files
    # must go through CandidateService's validator before reaching this method.
    clean={k:copy.deepcopy(hit[k]) for k in ('build','evaluation','new_jewels') if k in hit};clean.setdefault('new_jewels',0)
    values=attained(clean['evaluation']);a=canonical(values);signature=hashlib.sha256(a.encode()).hexdigest()
    cursor=self.db.execute('INSERT INTO pattern(signature,attained,tag) VALUES(?,?,?) ON CONFLICT(signature) DO UPDATE SET attained=excluded.attained,tag=excluded.tag WHERE attained!=excluded.attained OR tag!=excluded.tag',(signature,a,self.tag(['pattern',signature,a])))
    changed|=bool(cursor.rowcount)
    pid=self.db.execute('SELECT id FROM pattern WHERE signature=?',(signature,)).fetchone()[0]
    self.db.executemany('INSERT OR IGNORE INTO posting VALUES(?,?,?)',[(pid,sid,pt) for sid,pt in values.items()])
    identity=build_identity(clean['build']);armor=canonical(armor_key(clean['build']));r=clean['evaluation']
    total=sum(len(x.get('jewels',[])) for x in list(clean['build']['armor'].values())+[clean['build'].get('weapon',{})])
    features=canonical({'total_jewels':total,'active':sum(s['status'] in ('active','overlap') for s in r['skills']),
     'defense':r.get('defense_stats',{}).get('adjusted',{}).get('defense') or 0,
     'optional':values,'zenith_supply':{z['id']:{p:__import__('activation').supplied_points(r,z['id'],[p]) for p in ('weapon','armor','jewel','cuff')} for z in r.get('zenith',[])}})
    clean['new_jewels']=total
    payload=zlib.compress(canonical(clean).encode(),6);digest=hashlib.sha256(payload).hexdigest();tag=self.tag(['witness',identity,signature,armor,features,digest])
    cursor=self.db.execute('INSERT INTO witness(identity,pattern_id,armor_key,features,payload,payload_hash,tag) VALUES(?,?,?,?,?,?,?) ON CONFLICT(identity) DO UPDATE SET pattern_id=excluded.pattern_id,armor_key=excluded.armor_key,features=excluded.features,payload=excluded.payload,payload_hash=excluded.payload_hash,tag=excluded.tag WHERE payload!=excluded.payload OR payload_hash!=excluded.payload_hash OR tag!=excluded.tag',(identity,pid,armor,features,payload,digest,tag))
    changed|=bool(cursor.rowcount)
    wid=self.db.execute('SELECT id FROM witness WHERE identity=?',(identity,)).fetchone()[0]
    cursor=self.db.execute('INSERT INTO membership VALUES(?,?,?) ON CONFLICT(scope_id,witness_id) DO UPDATE SET tag=excluded.tag WHERE tag!=excluded.tag',(scope,wid,self.tag(['membership',scope,identity])))
    changed|=bool(cursor.rowcount)
   if changed:self.touch()
   self.db.commit();return changed
 def _index(self,req):
  key=condition_key(req);revision=self.revision();cached=self.indices.get(key)
  if cached and cached[0]==revision:self.indices.move_to_end(key);return cached[1]
  patterns={};rows=[]
  for r in self.db.execute('SELECT w.id,w.identity,w.pattern_id,w.armor_key,w.features,w.payload_hash,w.tag,w.payload,p.signature,p.attained,p.tag AS ptag,m.tag AS mtag FROM membership m JOIN witness w ON w.id=m.witness_id JOIN pattern p ON p.id=w.pattern_id WHERE m.scope_id=? ORDER BY w.id',(key,)):
   if hashlib.sha256(r['payload']).hexdigest()!=r['payload_hash']:continue
   if not self.valid(['membership',key,r['identity']],r['mtag']):continue
   if not self.valid(['pattern',r['signature'],r['attained']],r['ptag']):continue
   if not self.valid(['witness',r['identity'],r['signature'],r['armor_key'],r['features'],r['payload_hash']],r['tag']):continue
   row=dict(r);row.pop('payload')
   effective=json.loads(r['attained'])
   if req.get('zenith_sources'):
    supply=json.loads(r['features']).get('zenith_supply',{})
    for sid,providers in req['zenith_sources'].items():
     if sid in effective:effective[sid]=min(effective[sid],sum(supply.get(sid,{}).get(p,0) for p in providers))
   signature=canonical(effective);row['index_pattern']=signature;patterns[signature]=effective;row['features_data']=json.loads(row['features']);row['features_data']['optional']=effective;rows.append(row)
  index=ArchiveIndex(rows,patterns);self.indices[key]=(revision,index)
  while len(self.indices)>4:self.indices.popitem(last=False)
  return index
 def _hit(self,row):
  r=self.db.execute('SELECT payload,payload_hash FROM witness WHERE id=?',(row['id'],)).fetchone()
  if not r or len(r['payload'])>2*1024*1024 or hashlib.sha256(r['payload']).hexdigest()!=r['payload_hash']:return None
  dec=zlib.decompressobj();raw=dec.decompress(r['payload'],4*1024*1024)
  if dec.unconsumed_tail or not dec.eof:return None
  hit=json.loads(raw)
  if build_identity(hit['build'])!=row['identity'] or canonical(attained(hit['evaluation']))!=row['attained']:return None
  return hit
 def query(self,req,required,targets=(),limit=64):
  start=time.perf_counter()
  with self.lock:
   index=self._index(req);mask=index.mask(required)
   per_skill={f'{sid}|{pt}':(mask&index.skill_mask(sid,pt)).bit_count() for sid,pt in targets}
   positions=list(index.positions(mask))
   optional=req.get('optional',[])
   def order(i):
    f=index.rows[i]['features_data'];values=f['optional'];score=0
    for t in optional:
     value=values.get(t['skill'],0);pt=t['points']
     if value<=pt if pt<0 else value>=pt:score+=t.get('weight',1)
    mode=req.get('objective','minimal_jewels')
    return {'minimal_jewels':(-score,f['total_jewels'],-f['active']), 'optional':(-score,f['total_jewels'],-f['active']),
     'max_skills':(-f['active'],-score,f['total_jewels']), 'defense':(-f['defense'],-score,f['total_jewels'])}.get(mode,(-score,f['total_jewels'],-f['active']))+(index.rows[i]['identity'],)
   order_key=canonical([req.get('objective','minimal_jewels'),optional])
   if order_key not in index.orders:index.orders[order_key]=sorted(range(len(index.rows)),key=order)
   ranked=index.orders[order_key];selected=[];seen=set()
   for i in ranked:
    if not mask&(1<<i):continue
    row=index.rows[i]
    if req.get('diverse_armor',True) and row['armor_key'] in seen:continue
    hit=self._hit(row)
    if hit is None:continue
    hit['new_jewels']=sum(len(a.get('jewels',[])) for a in list(hit['build']['armor'].values())+[hit['build'].get('weapon',{})])-sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})]);hit['archive_variant_count']=index.group_count(mask,row['armor_key']);selected.append(hit);seen.add(row['armor_key'])
    if len(selected)>=limit:break
   distinct=len({index.rows[i]['armor_key'] for i in positions})
   return {'status':'confirmed' if selected else 'unexplored','results':selected,'confirmed_builds':mask.bit_count(),
    'distinct_armor':distinct,'decoration_variants':max(0,mask.bit_count()-distinct),'candidate_counts':per_skill,
    'reservoir_counts':{'confirmed_builds':len(index.rows),'distinct_armor':len(index.groups),'decoration_variants':len(index.rows)-len(index.groups)},
    'archive_filter_seconds':round(time.perf_counter()-start,6),'archive_revision':self.revision(),'scope':condition_key(req)}
 def has_scope(self,req):
  with self.lock:return bool(self._index(req).rows)
 def variants(self,req,required,armor,exclude=None,limit=8):
  with self.lock:
   index=self._index(req);key=canonical(tuple((p,armor.get(p)) for p in ('head','body','arm','waist','leg')))
   mask=index.mask(required);positions=index.groups.get(key,[]);hits=[];skip=build_identity(exclude) if exclude else None
   for i in positions:
    r=index.rows[i]
    if mask&(1<<i) and r['identity']!=skip:
     hit=self._hit(r)
     if hit:
      hit['new_jewels']=sum(len(a.get('jewels',[])) for a in list(hit['build']['armor'].values())+[hit['build'].get('weapon',{})])-sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})]);hits.append(hit)
     if len(hits)>=limit:break
   return {'results':hits,'variant_count':index.group_count(mask,key)-(1 if skip and any(index.rows[i]['identity']==skip and mask&(1<<i) for i in positions) else 0),'complete_game_search':False}
 def cross_scope(self,req,limit=96):
  # This is a migration/adoption path, never a claim that another scope is valid.
  # The caller must independently check every current restriction before ingest.
  with self.lock:
   key=condition_key(req);result=[]
   for scope, in self.db.execute('SELECT id FROM scope WHERE id!=? ORDER BY rowid DESC LIMIT 4',(key,)):
    row=self.db.execute('SELECT request FROM scope WHERE id=?',(scope,)).fetchone()
    old=json.loads(row[0]);index=self._index(old)
    for r in index.rows[-limit:]:
     hit=self._hit(r)
     if hit:result.append(hit)
     if len(result)>=limit:return result
   return result
 def put_attempt(self,req,required,status):
  with self.lock:
   scope=self._scope(req);body=canonical(required);updated=time.time()
   self.db.execute('INSERT OR REPLACE INTO attempt VALUES(?,?,?,?,?)',(scope,body,status,updated,self.tag(['attempt',scope,body,status,updated])));self.db.commit()
 def attempt(self,req,required):
  scope=condition_key(req);body=canonical(required)
  with self.lock:
   r=self.db.execute('SELECT * FROM attempt WHERE scope_id=? AND required=?',(scope,body)).fetchone()
   if r and self.valid(['attempt',scope,body,r['status'],r['updated']],r['tag']):return {'status':r['status'],'updated':r['updated'],'retry_after':max(0,60-(time.time()-r['updated']))}
  return None
 def put_proof(self,req,core,certificate):
  if certificate.get('kind') not in ('safe_interval','full_model_infeasible','semantic_rule'):raise ValueError('untrusted proof type')
  with self.lock:
   scope=self._scope(req);body=canonical(certificate);keys=canonical(core)
   self.db.execute('INSERT OR REPLACE INTO proof(scope_id,core,certificate,tag) VALUES(?,?,?,?)',(scope,keys,body,self.tag(['proof',scope,keys,body])));self.db.commit()
 def proofs(self,req):
  with self.lock:
   scope=condition_key(req);result=[]
   for r in self.db.execute('SELECT core,certificate,tag FROM proof WHERE scope_id=?',(scope,)):
    if self.valid(['proof',scope,r['core'],r['certificate']],r['tag']):result.append((json.loads(r['core']),json.loads(r['certificate'])))
   return result
 def assess(self,req,required,targets,counts):
  proofs=self.proofs(req);states={}
  for sid,pt in targets:
   key=f'{sid}|{pt}';n=counts.get(key,0)
   if n:states[key]={'state':'confirmed','count':n};continue
   extended=dict(required)
   if sid in extended and (extended[sid]<0)!=(pt<0):states[key]={'state':'input_conflict','count':0};continue
   extended[sid]=(min(extended.get(sid,pt),pt) if pt<0 else max(extended.get(sid,pt),pt))
   certificate=next((c for core,c in proofs if requirements_dominate(extended,core)),None)
   states[key]={'state':'proven_infeasible' if certificate and certificate.get('coverage_complete') else 'unresolved_data' if certificate else 'unknown','count':0,'proof_scope':'supported_search_model' if certificate else None}
  return states
 def prepare_facts(self,cancel=None):
  from search_precompute import generate
  self.fact_state='building'
  try:
   stats=generate(self.source,self.facts_path,cancel)
   from contextlib import closing
   from search_precompute import meta
   with closing(sqlite3.connect(self.facts_path)) as generated:
    if meta(generated,'calculation_identity')!=self.calculation:raise InterruptedError('calculation code changed during index generation')
   evidence={'source':self.identity,'calculation':self.calculation,'sqlite_sha256':hashlib.sha256(self.facts_path.read_bytes()).hexdigest(),'csr_sha256':hashlib.sha256(self.facts_path.with_suffix('.csr').read_bytes()).hexdigest()}
   self.fact_manifest.write_text(canonical({'evidence':evidence,'tag':self.tag(['facts',evidence])}),encoding='utf-8')
   self.fact_stats=stats;self.fact_state='ready';return stats
  except BaseException:
   self.fact_state='unprepared';raise
 def adopt_signed_facts(self,sqlite_path,csr_path,source_sha256):
  from data_packages import file_hash
  from search_precompute import meta
  import shutil
  if file_hash(self.source)!=source_sha256:raise ValueError('source changed before data installation')
  staging=self.facts_path.with_suffix('.importing.sqlite');csr_staging=self.facts_path.with_suffix('.importing.csr')
  shutil.copy2(sqlite_path,staging);shutil.copy2(csr_path,csr_staging)
  from contextlib import closing
  with closing(sqlite3.connect(staging)) as db:
   if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or meta(db,'schema')!=SCHEMA_VERSION or meta(db,'calculation_identity')!=self.calculation:raise ValueError('invalid or incompatible common data')
   if file_hash(csr_staging)!=meta(db,'csr_sha256'):raise ValueError('sparse matrix digest differs')
   meta(db,'source_identity',self.identity);db.commit();stats=meta(db,'statistics')
  if self.fact_connection:self.fact_connection.close();self.fact_connection=None
  os.replace(staging,self.facts_path);os.replace(csr_staging,self.facts_path.with_suffix('.csr'))
  evidence={'source':self.identity,'calculation':self.calculation,'sqlite_sha256':file_hash(self.facts_path),'csr_sha256':file_hash(self.facts_path.with_suffix('.csr'))}
  self.fact_manifest.write_text(canonical({'evidence':evidence,'tag':self.tag(['facts',evidence])}),encoding='utf-8')
  self.bounds_cache=None;self.coverage_cache.clear();self.fact_stats=stats;self.fact_state='ready'

 def open_facts(self):
  if self.fact_connection is not None:
   stamp=self.facts_path.stat()
   if self.fact_stamp==(stamp.st_size,stamp.st_mtime_ns,stamp.st_ctime_ns):return self.fact_connection
   self.fact_connection.close();self.fact_connection=None;self.fact_state='unprepared';return None
  try:
   data=json.loads(self.fact_manifest.read_text(encoding='utf-8'));ev=data['evidence']
   if not self.valid(['facts',ev],data['tag']) or ev['source']!=self.identity or ev['calculation']!=self.calculation:return None
   if hashlib.sha256(self.facts_path.read_bytes()).hexdigest()!=ev['sqlite_sha256']:return None
   if hashlib.sha256(self.facts_path.with_suffix('.csr').read_bytes()).hexdigest()!=ev['csr_sha256']:return None
   self.fact_connection=sqlite3.connect(self.facts_path.resolve().as_uri()+'?mode=ro',uri=True,check_same_thread=False)
   self.fact_connection.row_factory=sqlite3.Row;self.fact_connection.execute('PRAGMA mmap_size=268435456');stamp=self.facts_path.stat();self.fact_stamp=(stamp.st_size,stamp.st_mtime_ns,stamp.st_ctime_ns);self.fact_state='ready'
   from search_precompute import meta
   if meta(self.fact_connection,'calculation_identity')!=self.calculation or meta(self.fact_connection,'source_identity')!=self.identity or meta(self.fact_connection,'schema')!=SCHEMA_VERSION:
    self.fact_connection.close();self.fact_connection=None;return None
   self.fact_stats=meta(self.fact_connection,'statistics');self.bounds_cache=None;return self.fact_connection
  except (OSError,ValueError,KeyError,sqlite3.Error):return None
 def safe_interval(self,sid,pt,allowed=None):
  facts=self.open_facts()
  if facts is None:return None
  if self.bounds_cache is None:
   self.bounds_cache=collections.defaultdict(list)
   for r in facts.execute('SELECT b.*,s.kind,s.source_id FROM bound b JOIN skill s ON s.id=b.skill_id'):self.bounds_cache[r['source_id']].append(dict(r))
   cap=facts.execute('SELECT MAX(slots) FROM armor_level').fetchone()[0] or 3;self.maxslots=5*max(3,cap)+3
  rows=self.bounds_cache.get(sid,[])
  if not rows:return None
  # Weapon <=3 and five armor <=3 is current supported layout. Use all
  # imported level maxima when larger; each jewel occupies at least one unit.
  maxslots=self.maxslots
  lo=hi=0;automatic_low=automatic_high=0
  for row in rows:
   provider='armor' if row['provider'] in ('head','body','arm','waist','leg') else row['provider']
   if allowed and provider not in allowed:continue
   factor=maxslots if provider=='jewel' else 2 if provider=='cuff' else 1
   lo+=row['low']*factor;hi+=row['high']*factor
   automatic_low=min(automatic_low,row['automatic_low']);automatic_high=max(automatic_high,row['automatic_high'])
  if pt<0 and lo>pt and automatic_low>pt or pt>0 and hi<pt and automatic_high<pt:
   return {'kind':'safe_interval','skill':sid,'threshold':pt,'low':lo,'high':hi,'automatic_low':automatic_low,'automatic_high':automatic_high,'scope':'supported_search_model','source':self.identity,'calculation':self.calculation}
  return None
 def worker_environment(self):
  if self.open_facts() is None:return {}
  evidence=json.loads(self.fact_manifest.read_text(encoding='utf-8'))['evidence']
  return {'MHF_PRECOMPUTED_FACTS':str(self.facts_path.resolve()),'MHF_PRECOMPUTED_SHA':evidence['sqlite_sha256'],'MHF_PRECOMPUTED_CSR_SHA':evidence['csr_sha256']}

 def coverage(self,req):
  key=condition_key(req)
  if key in self.coverage_cache:return self.coverage_cache[key]
  facts=self.open_facts()
  if facts is None:return {'complete':False,'reason':'index_not_ready'}
  bad=[];job='ガンナー' if req.get('weapon_type') in ('HBG','LBG','Bow') else '剣士';sex=req.get('sex','男')
  excluded=set(req.get('exclude',[]));classes=set(req.get('exclude_classes',[]))
  for r in facts.execute("SELECT DISTINCT e.* FROM audit a JOIN entity e ON e.source_id=a.source_id WHERE a.category='equipment'"):
   flags=json.loads(r['flags']);kind=r['kind'];eid=r['source_id'];code=flags.get('class');group=flags.get('group');ab=flags.get('abilities',[])
   if eid in excluded or code in classes or code in ('(未)','(不)') or r['job'] not in (None,'共',job) or r['sex'] not in (None,'共',sex):continue
   if kind in ('head','body','arm','waist','leg'):
    fixed=req.get('armor',{}).get(kind);allowed=req.get('armor_candidates',{}).get(kind)
    if fixed and fixed.get('item')!=eid:continue
    if allowed is not None and eid not in allowed:continue
    if not fixed and allowed is None and req.get('g_armor_only',True) and not any(a[0]=='Ｇ級効果' for a in ab):continue
   elif kind=='jewel':
    if group=='SP':continue # SP armors are already an explicit unresolved armor case.
    if req.get('jewel_candidates') is not None and eid not in req['jewel_candidates']:continue
   elif kind=='cuff':
    if 'cuffs' in req and eid not in req['cuffs']:continue
    if req.get('cuff_candidates') is not None and eid not in req['cuff_candidates']:continue
    secret=any(a[0]=='スキル枠消費なし' for a in ab)
    if group=='P' and not req.get('premium_poogie_clothes'):continue
    if (secret or 'Ｇ' in (code or '') or '辿' in (code or '')) and not req.get('g_poogie'):continue
   elif kind=='weapon_template':
    if req.get('weapon',{}).get('template')!=eid:continue
   else:continue
   bad.append({'provider':kind,'id':eid})
   if len(bad)>=20:break
  w=req.get('weapon',{});auto=req.get('auto_weapon');categories=req.get('weapon_filters',{}).get('categories');selectors=req.get('weapon_candidates')
  if auto or w.get('page'):
   for r in facts.execute('SELECT * FROM weapon WHERE weapon_type=? AND supported=0',(req['weapon_type'],)):
    if not auto and (r['page'],r['anchor'])!=(w.get('page'),w.get('anchor')):continue
    if categories is not None and r['category'] not in categories:continue
    if selectors is not None and not any(x['page']==r['page'] and x['anchor']==r['anchor'] for x in selectors):continue
    if f"{r['page']}#{r['anchor']}" in excluded or str(r['source_weapon_id']) in excluded:continue
    bad.append({'provider':'weapon','id':f"{r['page']}#{r['anchor']}",'reason':r['reason']})
    if len(bad)>=20:break
  result={'complete':not bad,'reason':'declared_eligible_data_complete' if not bad else 'unhandled_eligible_data','examples':bad}
  self.coverage_cache[key]=result;return result

 def supply_coverage(self,providers):
  facts=self.open_facts()
  if facts is None:return False
  for provider in providers:
   if provider=='weapon':
    if facts.execute('SELECT 1 FROM weapon WHERE supported=0 LIMIT 1').fetchone():return False
   elif provider=='armor':
    if facts.execute("SELECT 1 FROM audit a JOIN entity e ON e.source_id=a.source_id WHERE a.category='equipment' AND e.kind IN ('head','body','arm','waist','leg') LIMIT 1").fetchone():return False
   elif facts.execute("SELECT 1 FROM audit a JOIN entity e ON e.source_id=a.source_id WHERE a.category='equipment' AND e.kind=? LIMIT 1",(provider,)).fetchone():return False
  return True

 def enqueue(self,req,targets):
  with self.lock:
   scope=self._scope(req);context=canonical(sorted((x['skill'],x.get('points')) for x in req.get('required',[])))
   for target in targets:
    task={**copy.deepcopy(req),'required':req.get('required',[])+([target] if target else [])};task.pop('probe',None)
    key=hashlib.sha256((scope+canonical(task['required'])).encode()).hexdigest()
    self.db.execute("INSERT OR IGNORE INTO work(id,scope_id,context,request,state,updated) VALUES(?,?,?,?,'pending',?)",(key,scope,context,canonical(task),time.time()))
   self.db.commit()
 def next_work(self,req):
  with self.lock:
   row=self.db.execute("SELECT * FROM work WHERE scope_id=? AND context=? AND state IN ('pending','unknown') AND next_after<=? ORDER BY attempts,updated,id LIMIT 1",(condition_key(req),canonical(sorted((x['skill'],x.get('points')) for x in req.get('required',[]))),time.time())).fetchone()
   if not row:return None
   self.db.execute("UPDATE work SET state='running',updated=? WHERE id=?",(time.time(),row['id']));self.db.commit();return {'id':row['id'],'request':json.loads(row['request'])}
 def finish_work(self,key,status):
  with self.lock:
   row=self.db.execute('SELECT attempts FROM work WHERE id=?',(key,)).fetchone()
   if not row:return
   attempts=row[0]+1;state='done' if status in ('confirmed','proven_infeasible','data_incomplete') else 'unknown'
   self.db.execute('UPDATE work SET state=?,attempts=?,last_status=?,next_after=?,updated=? WHERE id=?',(state,attempts,status,time.time()+min(86400,30*2**min(10,attempts)),time.time(),key));self.db.commit()
 def status(self):
  with self.lock:
   return {'state':self.fact_state,'statistics':self.fact_stats,'witnesses':self.db.execute('SELECT count(*) FROM witness').fetchone()[0],
    'patterns':self.db.execute('SELECT count(*) FROM pattern').fetchone()[0],'proofs':self.db.execute('SELECT count(*) FROM proof').fetchone()[0],
    'tasks':dict(self.db.execute('SELECT state,count(*) FROM work GROUP BY state')),'schema_version':SCHEMA_VERSION,'calculation_identity':self.calculation,'source_identity':self.identity}
 def close(self):
  with self.lock:
   if self.fact_connection is not None:self.fact_connection.close();self.fact_connection=None
   if self._db is not None:self._db.close();self._db=None
   self._closed=True
