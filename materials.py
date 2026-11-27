"""Read local upstream recipe data on demand; no third-party data is distributed."""
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
import hashlib
import math
import json
import re
import zipfile
from import_data import FILES, root
from ferias_import import load, txt
from sharing import canonical_build

PARTS = ('head','body','arm','waist','leg')

# Verify the local archives against the database before using positional equipment IDs.
def archive_path(db, directory, key):
    r = db.execute('SELECT filename,sha256 FROM sources WHERE id=?',(key,)).fetchone()
    if not r: raise ValueError(f'Missing database source: {key}')
    p = directory / Path(r['filename']).name
    if not p.is_file(): raise ValueError(f'Missing source ZIP: {p.name} / 元ZIPをDBと同じフォルダに配置してください')
    st=p.stat()
    verify(p,st.st_size,st.st_mtime_ns,r['sha256'])
    return p

@lru_cache(maxsize=12)
def verify(p,size,mtime,expected):
    with p.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=expected: raise ValueError(f'Source ZIP differs from imported database: {p.name}')

# Keep exact source IDs, including duplicate names; translate only unambiguous matches.
@lru_cache(maxsize=2)
def item_names(ja,en):
    with zipfile.ZipFile(ja) as a,zipfile.ZipFile(en) as b:
        jp={e.get('No'):e.text for e in root(a,'Item.xml')}; ep={e.get('No'):e.text for e in root(b,'Item.xml')}
    j,e=defaultdict(set),defaultdict(set)
    for i,n in jp.items():
        if n and ep.get(i): j[n].add(ep[i]); e[ep[i]].add(n)
    return j,e

@lru_cache(maxsize=7)
def equipment_data(path,kind):
    with zipfile.ZipFile(path) as z: r=root(z,FILES[kind])
    by_id={}; by_name=defaultdict(list)
    for g,group in enumerate(r):
        for i,x in enumerate(group.findall('Data')):
            eid=f'{kind}:{g}:{i}'; by_id[eid]=x; by_name[x.get('Name')].append(eid)
    return by_id,by_name

# Parse a weapon material cell only when its complete text consists of named quantities.
def weapon_cell(cell):
    from lxml import html
    raw=html.tostring(cell,encoding='unicode')
    raw=re.sub(r'<br\s*/?>','\n',raw,flags=re.I)
    node=html.fromstring(raw); lines=[x.strip() for x in node.text_content().splitlines() if x.strip()]
    if not lines or lines==['なし']: return []
    groups=[[]]
    for line in lines:
        if line.lower()=='or' or line=='または': groups.append([]); continue
        m=re.fullmatch(r'(.+?)\s*[x×]\s*(\d+)',line)
        if not m: return None
        groups[-1].append((m[1].strip(),int(m[2])))
    return groups if all(groups) else None

@lru_cache(maxsize=12)
def weapon_rows(path,page):
    with zipfile.ZipFile(path) as z: h=load(z,page)
    rows=defaultdict(list)
    for r in h.xpath('//tr[td[1][@id]]'):
        cells=r.xpath('./td'); rows[cells[0].get('id')].append(cells)
    return rows

def weapon_record(cells,ci):
    # Preserve the legacy parser's exact ambiguity and layout checks.
    if len(cells)!=1 or len(cells[0])!=ci+3:return None
    c=cells[0]
    return {'name':(c[0].text or '').strip(),'creates':weapon_cell(c[ci]),'upgrades':weapon_cell(c[ci+1]),
            'links':[a.get('href','')[1:] for a in c[0].xpath('./div/a') if '←' in txt(a) and a.get('href','').startswith('#')]}

class Planner:
    def __init__(self,db,directory):
        self.db=db; self.dir=Path(directory); self.steps=[];self.warnings=[];self.serial=0
        from master_data import has_master
        self.master=has_master(db)
        if self.master:
            self.jnames,self.enames=defaultdict(set),defaultdict(set)
            for ja,en in db.execute('SELECT ja,en FROM master_item_names'):
                self.jnames[ja].add(en);self.enames[en].add(ja)
        else:
            self.ja=archive_path(db,self.dir,'ja'); self.en=archive_path(db,self.dir,'en')
            self.jnames,self.enames=item_names(self.ja,self.en)

    def equipment(self,kind):
        if self.master:
            from master_data import RecipeRecords,RecipeNames
            return RecipeRecords(self.db),RecipeNames(self.db,kind)
        return equipment_data(self.ja,kind)

    def warn(self,ja,en):
        self.warnings.append({'ja':ja,'en':en})

    def material(self,n,qty,english=False):
        if english:
            matches=self.enames.get(n,set())
            if len(matches)==1: ja=next(iter(matches)); en=n; key='ja:'+ja
            else: ja=n;en=n;key='en:'+n
        else:
            ja=n; names=self.jnames.get(n,set());en=next(iter(names)) if len(names)==1 else n;key='ja:'+n
        return {'key':key,'ja':ja,'en':en,'qty':qty}

    def add(self,group,ja,en,level,options,count=1):
        self.serial+=1
        self.steps.append({'id':str(self.serial),'group':group,'ja':ja,'en':en,'level':level,'count':count,'options':options})

    def xml_options(self,costs):
        options=[]
        for c in costs:
            items=c.findall('Item')
            if not items or any(not i.text or not (i.get('Num') or '').isdigit() or int(i.get('Num'))<=0 for i in items): continue
            options.append({'type':c.get('Type','unknown'),'materials':[self.material(i.text,int(i.get('Num'))) for i in items]})
        return options

    def armor(self,part,eid,level,seen=()):
        by_id,by_name=self.equipment(part)
        x=by_id[eid]; name=x.get('Name'); en=self.db.execute('SELECT en FROM equipment WHERE id=?',(eid,)).fetchone()[0]
        if eid in seen or len(seen)>40:
            self.warn(f'{name}: 強化経路が循環しています',f'{en}: cyclic upgrade chain');return
        levels=x.findall('./Level/*'); names=[l.tag for l in levels]
        if level not in names: raise ValueError(f'{name}: invalid level {level}')
        # Prefer direct creation when available; do not combine its alternative upgrade route.
        for l in levels[:names.index(level)+1]:
            costs=l.findall('Cost')
            if l.tag==names[0]:
                direct=[c for c in costs if c.get('Type')=='create']
                if direct: costs=direct
                else:
                    src=x.find('Source')
                    matches=by_name.get(src.text,[]) if src is not None else []
                    if len(matches)==1 and (src.get('Level') or '').isdigit(): self.armor(part,matches[0],'L'+src.get('Level'),seen+(eid,))
                    else: self.warn(f'{name}: 強化元が未確定',f'{en}: predecessor unavailable or ambiguous')
            opts=self.xml_options(costs)
            if not opts: self.warn(f'{name} {l.tag}: 素材不明',f'{en} {l.tag}: missing recipe')
            self.add(part,name,en,l.tag,opts)

    def accessory(self,kind,eid,count):
        x=self.equipment(kind)[0][eid]; n=x.get('Name'); en=self.db.execute('SELECT en FROM equipment WHERE id=?',(eid,)).fetchone()[0]
        opts=self.xml_options(x.findall('Cost'))
        sources=[s.text for s in x.findall('./Sources/Source') if s.text]
        if not opts and kind=='jewel':
            # A single, complete Lv7 armor route is a safe alternative to direct production.
            # Multiple candidate sources are evaluated independently, never added together.
            from itertools import product
            part_map={'Head':'head','Body':'body','Arm':'arm','Waist':'waist','Leg':'leg'}
            for src in x.findall('./Sources/Source'):
                part=part_map.get(src.get('Type'))
                if not part or not src.text: continue
                by_id,by_name=self.equipment(part)
                matches=by_name.get(src.text,[])
                if len(matches)!=1:continue
                armor=by_id[matches[0]]
                if armor.get('Type')!='Ｇ級防具' or armor.find('./Level/L7') is None:continue
                # Ravi and standard G/GF/GX refine at Lv7; skip unclear special classes.
                if armor.get('Class') not in ('(Ｇ)','(G)','(GF)','(GX)'):continue
                old_steps,old_warnings,old_serial=self.steps,self.warnings,self.serial
                self.steps,self.warnings,self.serial=[],[],0
                try:
                    self.armor(part,matches[0],'L7')
                    steps=self.steps
                    if self.warnings or not steps or any(not st['options'] for st in steps):continue
                    if math.prod(len(st['options']) for st in steps)>64:continue
                    for route in product(*(st['options'] for st in steps)):
                        combined={}
                        for opt in route:
                            for m in opt['materials']:
                                if m['key'] in combined:combined[m['key']]['qty']+=m['qty']
                                else:combined[m['key']]=dict(m)
                        opts.append({'type':'refine','source':src.text,'materials':list(combined.values())})
                finally:
                    self.steps,self.warnings,self.serial=old_steps,old_warnings,old_serial
        if not opts:
            suffix=' / '.join(sources)
            self.warn(f'{n}: 生産・精錬素材未確定。精錬元等: {suffix or "不明"}',f'{en}: no complete recipe; refinement source: {suffix or "unknown"}')
        self.add(kind,n,en,'',opts,count)

    def weapon(self,w,wt):
        v=self.db.execute('SELECT * FROM ferias_variants WHERE weapon_type=? AND page=? AND anchor=?',(wt,w['page'],w['anchor'])).fetchone()
        if not v: raise ValueError('Unknown weapon variant')
        # Only standard creation/upgrade and G-level 100% material routes have a defined layout.
        if v['category'] in ('tower','g_evolution','hr_evolution','zenith_evolution','evolution_unknown') or not re.fullmatch(r'buki/[a-z]+(?:_g|_sp|_n)?\.htm',w['page']):
            self.warn(f'{v["name_source"]}: 特殊武器の強化素材は未対応',f'{v["name_source"]}: special upgrade system not supported');return
        gun=wt in ('LBG','HBG','Bow'); ci=8 if gun else 7
        if not self.master:
            path=archive_path(self.db,self.dir,'ferias')
            rows=weapon_rows(path,w['page'])
        g=w['page'].endswith('_g.htm'); seen=set()
        def visit(anchor,level=None):
            if anchor in seen or len(seen)>100: self.warn('武器の強化経路が不明','Weapon upgrade chain ambiguous');return
            seen.add(anchor)
            if self.master:
                row=self.db.execute('SELECT data FROM master_weapon_recipes WHERE page=? AND anchor=?',(w['page'],anchor)).fetchone()
                record=json.loads(row[0]) if row else None
            else:record=weapon_record(rows.get(anchor,[]),ci)
            if record is None: self.warn(f'{anchor}: 武器素材の形式未対応',f'{anchor}: unsupported weapon recipe layout');return
            nm=record['name'];creates=record['creates'];upgrades=record['upgrades'];opts=[]
            if g and level and level>1:
                prior=self.db.execute('SELECT anchor FROM ferias_variants WHERE weapon_type=? AND page=? AND upstream_id=? AND level=?',(wt,w['page'],v['upstream_id'],level-1)).fetchall()
                if len(prior)==1: visit(prior[0][0],level-1)
                else: self.warn(f'{nm}: 前段階不明',f'{nm}: previous level unknown')
                chosen=creates; typ='100%'
            elif creates: chosen=creates;typ='create'
            else:
                chosen=upgrades;typ='upgrade'
                links=record['links']
                if len(links)==1:visit(links[0])
                else:self.warn(f'{nm}: 武器の強化元不明',f'{nm}: weapon predecessor unknown')
            if chosen: opts=[{'type':typ,'materials':[self.material(n,q,True) for n,q in route]} for route in chosen]
            else: self.warn(f'{nm} {anchor}: 素材未取得',f'{nm} {anchor}: recipe not parsed')
            self.add('weapon',nm,nm,str(level or anchor),opts)
        visit(w['anchor'],v['level'])

    def plan(self,raw):
        b=canonical_build(self.db,raw)
        for p in PARTS:
            if p in b['armor']:
                a=b['armor'][p]; self.armor(p,a['item'],a['level'])
        for eid,n in sorted(Counter(j for a in [*b['armor'].values(),b.get('weapon',{})] for j in a.get('jewels',[])).items()): self.accessory('jewel',eid,n)
        for eid,n in sorted(Counter(b['cuffs']).items()): self.accessory('cuff',eid,n)
        if b.get('weapon'): self.weapon(b['weapon'],b['weapon_type'])
        plan_id=hashlib.sha256(json.dumps(self.steps,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
        return {'plan_id':plan_id,'steps':self.steps,'warnings':self.warnings,'baseline':'ZZ','complete':not self.warnings}
