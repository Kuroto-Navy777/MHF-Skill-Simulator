"""Parse local Ferias HTML without executing scripts."""
import re
import json
from collections import Counter
from lxml import html

TYPES = dict(zip('katate souken taiken tachi hammer horn lance gunlance tonfa slaxe magspike right heavy yumi'.split(), 'SnS DB GS LS Hammer HH Lance GL Tonfas SA MS LBG HBG Bow'.split()))
GUNNER = {'LBG','HBG','Bow'}
ALIASES = {'Earplugs Up':'Hearing Protection Up','S. Assault Up':'Stylish Assault Up','C. Conversion Up':'Critical Conversion Up','Para Res Up':'Paralysis Res Up'}
SCHEMA = '''
CREATE TABLE ferias_weapons(weapon_type TEXT NOT NULL, upstream_id INTEGER NOT NULL, name_source TEXT NOT NULL, name_ja TEXT, category TEXT, slot_mode TEXT, pax_id INTEGER REFERENCES weapons(id), pax_match TEXT, conflict INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(weapon_type,upstream_id));
CREATE TABLE ferias_variants(weapon_type TEXT NOT NULL, upstream_id INTEGER NOT NULL, page TEXT NOT NULL, anchor TEXT NOT NULL, level INTEGER, name_source TEXT, rarity INTEGER, attack INTEGER, affinity INTEGER, slots_reported INTEGER, rank_text TEXT, category TEXT, slot_mode TEXT, intrinsic_raw TEXT, stats_json TEXT NOT NULL, PRIMARY KEY(weapon_type,page,anchor), FOREIGN KEY(weapon_type,upstream_id) REFERENCES ferias_weapons(weapon_type,upstream_id));
CREATE TABLE ferias_zenith(weapon_type TEXT NOT NULL,page TEXT NOT NULL,anchor TEXT NOT NULL,ordinal INTEGER NOT NULL,skill_id TEXT REFERENCES skills(id),points INTEGER,raw_text TEXT NOT NULL,PRIMARY KEY(weapon_type,page,anchor,ordinal),FOREIGN KEY(weapon_type,page,anchor) REFERENCES ferias_variants(weapon_type,page,anchor));
CREATE TABLE ferias_issues(page TEXT,anchor TEXT,reason TEXT,cells_json TEXT);
CREATE TABLE sigil_recipes(source_anchor TEXT PRIMARY KEY,cells_json TEXT NOT NULL);
CREATE TABLE sigil_reference_rows(table_index INTEGER,row_index INTEGER,cells_json TEXT NOT NULL,PRIMARY KEY(table_index,row_index));
CREATE INDEX ix_ferias_variants ON ferias_variants(weapon_type,upstream_id,level);
CREATE INDEX ix_ferias_zenith ON ferias_zenith(skill_id,points);
'''

def dump(v):
    return json.dumps(v,ensure_ascii=False,separators=(',',':'))

def txt(el):
    return ' '.join(' '.join(el.itertext()).split())

def first_int(s):
    m=re.match(r'^\s*([+-]?\d+)',s or '')
    return int(m[1]) if m else None

def load(z,path):
    matches=[n for n in z.namelist() if n.endswith('/'+path) or n==path]
    if len(matches)!=1: raise ValueError(f'Expected one member: {path}')
    return html.fromstring(z.read(matches[0]).decode('utf-8-sig'))

# Weapon family controls compatibility. Unverified families remain unknown.
def category_mode(page,tag,rank,zenith):
    if page=='t' or tag=='天廊武器': return 'tower','tower_special'
    if page=='s':
        if zenith: return 'zenith_evolution','shared'
        if rank.startswith(('GR','GSR')): return 'g_evolution','sigil'
        if rank.startswith('HR'): return 'hr_evolution','decoration'
        return 'evolution_unknown','unknown'
    if page=='g': return 'g_level','sigil'
    if tag=='辿異武器': return 'zenith','shared'
    if tag=='遷悠武器': return 'exotic','shared'
    if tag in {'準G級武器','準G級技巧武器'}: return 'quasi_g','unknown'
    if tag=='祈歌武器': return ('prayer_g','sigil') if rank.startswith(('GR','GSR')) else ('prayer_hr','unknown')
    if tag in {'始種武器','烈種武器','G級覇種','覇種武器','天嵐武器','剛種武器'}: return tag,'decoration'
    if page=='sp': return 'sp','decoration'
    if page=='n': return 'rng_cat','decoration'
    if tag in {'HC武器','親方印',''} and rank.startswith('HR'): return tag or 'normal_hr','decoration'
    return tag or 'unknown','unknown'

# Match translations to the actual MHSX2G skill level IDs.
def resolve_zenith(raw,lookup):
    val=re.sub(r'^(?:Zenith Skill|辿異スキル)\s*[:：]\s*','',raw).strip()
    m=re.fullmatch(r'(.+?)(?:\+(\d*))?',val)
    if not m: return None,None
    base=ALIASES.get(m[1],m[1]); digit=m[2]
    for key in ([base+'+'+digit] if digit else [base,base+'+1']):
        if key in lookup: return lookup[key]
    return None,None

# Decoration slots are occupied slot units, not necessarily jewel count.
def validate_slots(mode,reported,decoration_slots,sigils):
    if any(type(x) is not int or x<0 for x in (decoration_slots,sigils)): raise ValueError('nonnegative integers required')
    if mode in ('unknown','tower_special'):
        return {'valid':decoration_slots==sigils==0,'complete':False,'reason':mode}
    if mode not in ('shared','sigil','decoration') or reported is None or not 0<=reported<=3:
        return {'valid':False,'complete':False,'reason':'missing/invalid slot data'}
    valid=decoration_slots+sigils<=reported and (mode!='sigil' or decoration_slots==0) and (mode!='decoration' or sigils==0)
    return {'valid':valid,'complete':True,'reason':'ok' if valid else 'incompatible slot allocation'}

def import_ferias(db,z):
    db.executescript(SCHEMA)
    lookup={en:(sid,pt) for sid,pt,en in db.execute("SELECT skill_id,points,skill_levels.en FROM skill_levels JOIN skills ON skills.id=skill_levels.skill_id WHERE skills.kind='zenith'")}
    pax={i:(t,s,r) for i,t,s,r in db.execute('SELECT id,weapon_type,slots_reported,raw_display FROM weapons')}
    summary=Counter()
    for file,typ in TYPES.items():
        for suffix in ('','_sp','_n','_g','_s','_t'):
            page=suffix[1:] or 'main'; path=f'buki/{file}{suffix}.htm'; bases=set(); seen=set(); previous_base=None
            for row in load(z,path).xpath('//tr[td[1][@id]]'):
                c=row.xpath('./td'); anchor=c[0].get('id','')
                m=re.fullmatch(r'l([0-9A-Fa-f]{4})([0-9A-Fa-f]*)' if page=='n' else r'l([0-9A-Fa-f]{4})(\d*)',anchor)
                if not m: raise ValueError(f'{path}: bad anchor {anchor}')
                wid=int(m[1],16); ext=m[2]; base=not ext or (page=='n' and wid not in bases)
                if base:
                    bases.add(wid)
                    previous_base=wid
                if not base and (wid not in bases or (page in {'g','s','t'} and wid!=previous_base)):
                    db.execute('INSERT INTO ferias_issues VALUES(?,?,?,?)',(path,anchor,'anchor does not match containing weapon group',dump([txt(x) for x in c])))
                    if previous_base is not None:
                        db.execute('UPDATE ferias_weapons SET conflict=1 WHERE weapon_type=? AND upstream_id=?',(typ,previous_base))
                    summary['quarantined']+=1
                    continue
                if anchor in seen:
                    db.execute('INSERT INTO ferias_issues VALUES(?,?,?,?)',(path,anchor,'duplicate anchor',dump([txt(x) for x in c])))
                    db.execute('UPDATE ferias_weapons SET conflict=1 WHERE weapon_type=? AND upstream_id=?',(typ,wid))
                    summary['quarantined']+=1
                    continue
                seen.add(anchor)
                level=int(ext or ('0' if page=='t' else '1')) if page in {'g','s','t'} else None
                nm=(c[0].text or '').strip() or txt(c[0]); tag=' '.join(c[0].xpath('./p//text()')); qs=[txt(q) for q in row.xpath('.//q')]
                intrinsic=[txt(s) for s in c[-1].xpath('.//s') if re.search(r'(?:Origin|Burst) Weapon[:：]',txt(s))] if page!='t' else []
                if page=='t':
                    rarity=slots=None; atk=first_int(txt(c[2])); affinity=first_int(txt(c[4])); rank=''; cat,mode='tower','tower_special'; stats={'cells':[txt(x) for x in c[1:]]}
                else:
                    si=5 if typ in GUNNER else 4; rarity=first_int(c[1].text or txt(c[1])); a=txt(c[2]); atk=first_int(a); am=re.search(r'([+-]?\d+)\s*%',a); affinity=int(am[1]) if am else None
                    slots=first_int(txt(c[si])); rank=txt(c[si+1]); cat,mode=category_mode(page,tag,rank,qs)
                    stats={'attributes':a,'rank':rank,'price':txt(c[si+2]),'other_stats':[txt(x) for x in c[3:si]]}
                stats['sharpness']=[{'title':u.get('title'),'segments':[li.get('class') for li in u.xpath('./li')]} for u in row.xpath('.//ul[@title]')]
                if base:
                    old=db.execute('SELECT category FROM ferias_weapons WHERE weapon_type=? AND upstream_id=?',(typ,wid)).fetchone()
                    if old is None:
                        match=pax.get(wid) if typ not in GUNNER else None; pid=wid if match and match[0]==typ else None
                        state='not_applicable' if typ in GUNNER else 'missing' if not match else 'type_mismatch' if pid is None else 'linked'
                        if pid is not None and page=='main' and (slots!=match[1] or atk!=match[2]): state='linked_stats_differ'
                        db.execute('INSERT INTO ferias_weapons VALUES(?,?,?,?,?,?,?,?,?)',(typ,wid,nm,nm if page=='t' else None,cat,mode,pid,state,0));summary['base:'+typ]+=1;summary['pax:'+state]+=1
                    elif page=='t': db.execute('UPDATE ferias_weapons SET name_ja=? WHERE weapon_type=? AND upstream_id=?',(nm,typ,wid))
                    elif old[0]!=cat: db.execute('UPDATE ferias_weapons SET conflict=1 WHERE weapon_type=? AND upstream_id=?',(typ,wid))
                db.execute('INSERT INTO ferias_variants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(typ,wid,path,anchor,level,nm,rarity,atk,affinity,slots,rank,cat,mode,dump(intrinsic),dump(stats)));summary['variants']+=1
                for j,q in enumerate(qs):
                    sid,pt=resolve_zenith(q,lookup);db.execute('INSERT INTO ferias_zenith VALUES(?,?,?,?,?,?,?)',(typ,path,anchor,j,sid,pt,q));summary['zenith_mapped' if sid else 'zenith_unmapped']+=1
        print('Ferias',typ,summary['base:'+typ],flush=True)
    for r in load(z,'bougu/sigil.htm').xpath('//tr[td[1][@id]]'):
        c=r.xpath('./td');db.execute('INSERT INTO sigil_recipes VALUES(?,?)',(c[0].get('id'),dump([txt(x) for x in c])));summary['sigil_recipes']+=1
    for i,table in enumerate(load(z,'koneta/sigil_doc.htm').xpath('//table')):
        for j,r in enumerate(table.xpath('.//tr')):
            db.execute('INSERT INTO sigil_reference_rows VALUES(?,?,?)',(i,j,dump([txt(x) for x in r.xpath('./td|./th')])));summary['sigil_reference_rows']+=1
    return dict(summary)
