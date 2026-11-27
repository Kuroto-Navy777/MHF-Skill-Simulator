"""Generate exact local catalogue factors and conservative bounds. Never distribute this DB."""
import argparse,collections,hashlib,itertools,json,math,mmap,os,sqlite3,struct,time
from pathlib import Path
from contextlib import closing
from calculation_identity import SCHEMA_VERSION,calculation_identity,source_identity
from ferias_import import validate_slots
from skill_engine import Engine,PARTS
from weapon_effects import intrinsic_levels

SCHEMA='''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS skill(id INTEGER PRIMARY KEY,source_id TEXT UNIQUE,kind TEXT,metadata TEXT);
CREATE TABLE IF NOT EXISTS tier(skill_id INTEGER,points INTEGER,name TEXT,rules TEXT,PRIMARY KEY(skill_id,points));
CREATE TABLE IF NOT EXISTS entity(id INTEGER PRIMARY KEY,source_id TEXT UNIQUE,kind TEXT,slots INTEGER,job TEXT,sex TEXT,supported INTEGER,flags TEXT);
CREATE TABLE IF NOT EXISTS vector(entity_id INTEGER,skill_id INTEGER,kind TEXT,points INTEGER,PRIMARY KEY(entity_id,skill_id,kind));
CREATE INDEX IF NOT EXISTS vector_skill ON vector(skill_id,kind,points,entity_id);
CREATE TABLE IF NOT EXISTS armor_level(entity_id INTEGER,level TEXT,slots INTEGER,defense INTEGER,PRIMARY KEY(entity_id,level));
CREATE TABLE IF NOT EXISTS weapon(id INTEGER PRIMARY KEY,weapon_type TEXT,page TEXT,anchor TEXT,source_weapon_id INTEGER,level INTEGER,slot_class TEXT,category TEXT,supported INTEGER,reason TEXT,UNIQUE(weapon_type,page,anchor));
CREATE INDEX IF NOT EXISTS weapon_type ON weapon(weapon_type,supported);
CREATE TABLE IF NOT EXISTS weapon_pattern(slot_class TEXT,decoration_used INTEGER,sigils INTEGER,PRIMARY KEY(slot_class,decoration_used,sigils));
CREATE TABLE IF NOT EXISTS cuff_member(entity_id INTEGER PRIMARY KEY,class_id TEXT);
CREATE TABLE IF NOT EXISTS cuff_pair(class_a TEXT,class_b TEXT,slots INTEGER,secret_count INTEGER,needs_g INTEGER,needs_p INTEGER,PRIMARY KEY(class_a,class_b));
CREATE TABLE IF NOT EXISTS bound(skill_id INTEGER,provider TEXT,low INTEGER,high INTEGER,automatic_low INTEGER,automatic_high INTEGER,PRIMARY KEY(skill_id,provider));
CREATE TABLE IF NOT EXISTS audit(category TEXT,source_id TEXT,reason TEXT);
CREATE INDEX IF NOT EXISTS audit_category ON audit(category);
'''
ALLOWED_ABILITIES={'Ｇ級効果','スキル強化','スキル枠拡張','スキル枠消費なし','スキル発動'}

def meta(db,key,value=None):
 if value is not None:db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,json.dumps(value,ensure_ascii=False)))
 else:
  row=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else None

def generate(source,destination,cancel=None):
 source=Path(source).resolve();destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
 start=time.perf_counter();identity=source_identity(source);abi=calculation_identity()
 # Staging file is atomically installed only after all factors and mmap data finish.
 staging=destination.with_suffix('.building.sqlite');csr_tmp=destination.with_suffix('.building.csr')
 if staging.exists():staging.unlink()
 def checkpoint():
  if cancel and cancel.is_set():raise InterruptedError('index generation cancelled')
  if source_identity(source)!=identity:raise InterruptedError('source DB changed while building index')
 with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as raw,closing(sqlite3.connect(staging)) as out:
  raw.row_factory=sqlite3.Row;raw.execute('BEGIN');e=Engine(raw);out.executescript(SCHEMA)
  out.execute('PRAGMA journal_mode=DELETE');out.execute('PRAGMA synchronous=FULL')
  skills={sid:i for i,sid in enumerate(e.skills,1)}
  out.executemany('INSERT INTO skill VALUES(?,?,?,?)',[(n,sid,e.skills[sid]['kind'],e.skills[sid]['metadata']) for sid,n in skills.items()])
  out.executemany('INSERT INTO tier VALUES(?,?,?,?)',[(skills[sid],t['points'],t['ja'],t['rules_json']) for sid,ts in e.levels.items() for t in ts])
  abilities=collections.defaultdict(list)
  for row in raw.execute('SELECT equipment_id,type_ja,value_ja FROM abilities'):abilities[row[0]].append((row[1],row[2]))
  entities={};records=[];extra_vectors=[];cuff_classes={}
  for i,row in enumerate(raw.execute('SELECT * FROM equipment'),1):
   eid=row['id'];entities[eid]=i;ab=abilities[eid];reasons=[]
   for typ,value in ab:
    if typ not in ALLOWED_ABILITIES:reasons.append('unsupported ability: '+typ)
    if typ in ('スキル強化','スキル枠拡張','スキル発動'):
     matches=e.level_names[('normal' if typ=='スキル発動' else 'zenith',value)]
     if len(matches)==1:
      tier=matches[0];extra_vectors.append((i,skills[tier['skill_id']],'automatic' if typ=='スキル発動' else 'zenith',tier['points']))
     else:reasons.append('unmapped ability: '+str(value))
   flags={'class':row['class_code'],'group':row['group_name'],'abilities':ab}
   supported=not reasons and row['class_code'] not in ('(未)','(不)') and row['group_name']!='SP'
   records.append((i,eid,row['kind'],row['slots'],row['job'],row['sex'],int(supported),json.dumps(flags,ensure_ascii=False)))
   out.executemany('INSERT INTO audit VALUES(?,?,?)',[('equipment',eid,r) for r in reasons])
   if row['kind']=='cuff' and row['slots'] in (0,1,2) and supported:
    secret=int(any(t=='スキル枠消費なし' for t,v in ab));g=int(secret or 'Ｇ' in (row['class_code'] or '') or '辿' in (row['class_code'] or ''));p=int(row['group_name']=='P')
    cls=json.dumps((row['slots'],secret,g,p),separators=(',',':'));cuff_classes[cls]=(row['slots'],secret,g,p)
    out.execute('INSERT INTO cuff_member VALUES(?,?)',(i,cls))
   if i%4096==0:checkpoint();time.sleep(.001)
  out.executemany('INSERT INTO entity VALUES(?,?,?,?,?,?,?,?)',records)
  counts=collections.Counter()
  for row in raw.execute('SELECT equipment_id,skill_id,points FROM equipment_skills'):
   eid,sid,pt=row
   if eid not in entities or sid not in skills:
    out.execute('INSERT INTO audit VALUES(?,?,?)',('point',str(eid),'unmapped equipment or skill'));continue
   out.execute('INSERT INTO vector VALUES(?,?,?,?)',(entities[eid],skills[sid],'normal',pt));counts['normal_points']+=1
  # More than one declared ability can add the same Zenith family.
  for eid,sid,kind,pt in extra_vectors:
   out.execute('INSERT INTO vector VALUES(?,?,?,?) ON CONFLICT(entity_id,skill_id,kind) DO UPDATE SET points=CASE WHEN excluded.kind="automatic" THEN MAX(points,excluded.points) ELSE points+excluded.points END',(eid,sid,kind,pt))
  out.executemany('INSERT INTO armor_level VALUES(?,?,?,?)',[(entities[row[0]],row[1],row[2],row[3]) for row in raw.execute('SELECT equipment_id,level,slots,defense FROM levels') if row[0] in entities])
  # A class pair represents every member pair exactly; source IDs remain distinct.
  out.execute("INSERT INTO cuff_pair VALUES('','',0,0,0,0)")
  for cls,c in cuff_classes.items():out.execute('INSERT INTO cuff_pair VALUES(?,?,?,?,?,?)',('',cls,c[0],c[1],c[2],c[3]))
  pair_count=1+len(cuff_classes)
  for a,b in itertools.combinations_with_replacement(sorted(cuff_classes),2):
   ca,cb=cuff_classes[a],cuff_classes[b]
   if ca[0]+cb[0]<=2 and ca[1]+cb[1]<=1:
    out.execute('INSERT INTO cuff_pair VALUES(?,?,?,?,?,?)',(a,b,ca[0]+cb[0],ca[1]+cb[1],int(ca[2] or cb[2]),int(ca[3] or cb[3])));pair_count+=1
  zen=collections.defaultdict(list)
  for r in raw.execute('SELECT weapon_type,page,anchor,skill_id,points FROM ferias_zenith'):zen[tuple(r[:3])].append((r[3],r[4]))
  weapon_count=0;patterns=set();last_id=len(entities)
  for row in raw.execute('SELECT v.*,w.conflict FROM ferias_variants v JOIN ferias_weapons w USING(weapon_type,upstream_id)'):
   weapon_count+=1;eid=last_id+weapon_count;key=(row['weapon_type'],row['page'],row['anchor']);mode,slots=row['slot_mode'],row['slots_reported']
   declared,unmapped=intrinsic_levels(e,row);reasons=[]
   if row['conflict']:reasons.append('conflicted source weapon ID')
   if unmapped:reasons.append('unmapped intrinsic effect')
   if mode not in ('decoration','shared','sigil') or slots not in range(4):reasons.append('unsupported slot mode or capacity')
   if any(sid not in skills or pt is None for sid,pt in zen[key]):reasons.append('unmapped Zenith effect')
   cls=str(mode)+':'+str(slots);supported=not reasons
   out.execute('INSERT INTO weapon VALUES(?,?,?,?,?,?,?,?,?,?)',(eid,*key,row['upstream_id'],row['level'],cls,row['category'],int(supported),'; '.join(reasons)))
   out.execute('INSERT INTO entity VALUES(?,?,?,?,?,?,?,?)',(eid,'weapon:'+':'.join(map(str,key)),'weapon',slots,None,None,int(supported),'{}'))
   for sid,pt in zen[key]:
    if sid in skills and pt is not None:out.execute('INSERT INTO vector VALUES(?,?,?,?) ON CONFLICT(entity_id,skill_id,kind) DO UPDATE SET points=points+excluded.points',(eid,skills[sid],'zenith',pt))
   if row['category']=='exotic':declared=declared+[e.level_names[('normal','早食い')][0]]
   for t in declared:out.execute('INSERT OR REPLACE INTO vector VALUES(?,?,?,?)',(eid,skills[t['skill_id']],'automatic',t['points']))
   if supported and cls not in patterns:
    patterns.add(cls)
    for used in range(4):
     for sigils in range(4):
      if validate_slots(mode,slots,used,sigils)['valid']:out.execute('INSERT INTO weapon_pattern VALUES(?,?,?)',(cls,used,sigils))
   out.executemany('INSERT INTO audit VALUES(?,?,?)',[('weapon',str(key),reason) for reason in reasons])
   if weapon_count%8192==0:checkpoint();time.sleep(.002)
  # Safe independent extrema: missing entities contribute zero. Correlations are
  # deliberately relaxed, so these bounds cannot exclude a feasible composition.
  out.execute('CREATE INDEX IF NOT EXISTS entity_kind ON entity(kind,id)')
  for sid in skills.values():
   checkpoint()
   for kind in (*PARTS,'jewel','cuff','weapon'):
    row=out.execute('SELECT MIN(v.points),MAX(v.points) FROM vector v JOIN entity e ON e.id=v.entity_id WHERE v.skill_id=? AND (e.kind=? OR (?="weapon" AND e.kind="weapon_template")) AND v.kind!=?',(sid,kind,kind,'automatic')).fetchone()
    auto=out.execute('SELECT MIN(v.points),MAX(v.points) FROM vector v JOIN entity e ON e.id=v.entity_id WHERE v.skill_id=? AND (e.kind=? OR (?="weapon" AND e.kind="weapon_template")) AND v.kind=?',(sid,kind,kind,'automatic')).fetchone()
    out.execute('INSERT INTO bound VALUES(?,?,?,?,?,?)',(sid,kind,min(0,row[0] or 0),max(0,row[1] or 0),min(0,auto[0] or 0),max(0,auto[1] or 0)))
  # CSR-style mmap: offsets plus (skill ordinal, kind, signed points) triples.
  all_rows=out.execute('SELECT entity_id,skill_id,kind,points FROM vector ORDER BY entity_id,skill_id,kind')
  offsets=[0]*(last_id+weapon_count+2);payload=bytearray();current=0;type_ids={'normal':1,'zenith':2,'automatic':3}
  for eid,sid,kind,pt in all_rows:
   while current<=eid:offsets[current]=len(payload)//12;current+=1
   payload+=struct.pack('<iii',sid,type_ids[kind],pt)
  while current<len(offsets):offsets[current]=len(payload)//12;current+=1
  header=struct.pack('<8sIII',b'MHFCSR14',SCHEMA_VERSION,len(offsets),len(payload)//12)
  csr_tmp.write_bytes(header+struct.pack('<'+str(len(offsets))+'I',*offsets)+payload)
  checkpoint();csr=destination.with_suffix('.csr');os.replace(csr_tmp,csr)
  stats={'source_equipment':len(entities),'weapon_variants':weapon_count,'skill_families':len(skills),'vectors':out.execute('SELECT count(*) FROM vector').fetchone()[0],'armor_levels':out.execute('SELECT count(*) FROM armor_level').fetchone()[0],'cuff_classes':len(cuff_classes),'cuff_class_pairs':pair_count,'weapon_pattern_rows':out.execute('SELECT count(*) FROM weapon_pattern').fetchone()[0],'audit':dict(out.execute('SELECT category,count(*) FROM audit GROUP BY category')),'csr_bytes':csr.stat().st_size}
  meta(out,'schema',SCHEMA_VERSION);meta(out,'source_identity',identity);meta(out,'calculation_identity',abi);meta(out,'csr_sha256',hashlib.sha256(csr.read_bytes()).hexdigest());meta(out,'statistics',stats);meta(out,'ready',True)
  out.commit();out.execute('ANALYZE');out.commit()
 out.close();raw.close()
 os.replace(staging,destination);stats.update(generation_seconds=round(time.perf_counter()-start,6),sqlite_bytes=destination.stat().st_size)
 return stats

class MappedVectors:
 def __init__(self,path):
  self.file=Path(path).open('rb');self.map=mmap.mmap(self.file.fileno(),0,access=mmap.ACCESS_READ)
  magic,version,self.offset_count,self.row_count=struct.unpack_from('<8sIII',self.map)
  if magic!=b'MHFCSR14' or version!=SCHEMA_VERSION or len(self.map)!=20+4*self.offset_count+12*self.row_count:raise ValueError('invalid sparse map')
 def get(self,eid):
  if not 0<=eid<self.offset_count-1:raise KeyError(eid)
  a,b=struct.unpack_from('<II',self.map,20+eid*4);start=20+4*self.offset_count
  return [struct.unpack_from('<iii',self.map,start+i*12) for i in range(a,b)]
 def close(self):self.map.close();self.file.close()

def load_solver_vectors(source_db,items,skills):
    path=os.environ.get('MHF_PRECOMPUTED_FACTS');expected=os.environ.get('MHF_PRECOMPUTED_SHA');csr_expected=os.environ.get('MHF_PRECOMPUTED_CSR_SHA')
    if not path or not expected or not csr_expected:return None
    from data_packages import file_hash
    path=Path(path);csr=path.with_suffix('.csr');name=source_db.execute('PRAGMA database_list').fetchone()[2]
    if not name:return None
    try:
        if file_hash(path)!=expected or file_hash(csr)!=csr_expected:return None
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            if meta(db,'source_identity')!=source_identity(name) or meta(db,'calculation_identity')!=calculation_identity() or not meta(db,'ready'):return None
            ids={r[0]:items[r[1]]['id'] for r in db.execute("SELECT id,source_id FROM entity WHERE kind!='weapon'") if r[1] in items}
            sid={r[0]:skills[r[1]]['id'] for r in db.execute('SELECT id,source_id FROM skill') if r[1] in skills}
            maps=[collections.defaultdict(dict) for _ in range(3)];mapped=MappedVectors(csr)
            try:
                for ordinal,eid in ids.items():
                    for skill,kind,points in mapped.get(ordinal):maps[kind-1][eid][sid[skill]]=points
            finally:mapped.close()
            return tuple(maps)
    except (OSError,ValueError,KeyError,sqlite3.Error,struct.error):return None

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(json.dumps(generate(a.db,a.out),ensure_ascii=False,indent=2))
