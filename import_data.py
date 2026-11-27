"""Local-only MHF data import. No upstream assets are bundled."""
import argparse
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET

FILES = {'head':'EquipHead.xml','body':'EquipBody.xml','arm':'EquipArm.xml','waist':'EquipWst.xml','leg':'EquipLeg.xml','jewel':'Jewel.xml','cuff':'SkillCuff.xml','weapon_template':'Weapon.xml'}
SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE sources(id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, verification TEXT NOT NULL);
CREATE TABLE skills(id TEXT PRIMARY KEY, kind TEXT NOT NULL, ja TEXT NOT NULL, en TEXT NOT NULL, priority INTEGER, metadata TEXT NOT NULL);
CREATE TABLE skill_levels(skill_id TEXT REFERENCES skills(id), points INTEGER, ja TEXT NOT NULL, en TEXT NOT NULL, rules_json TEXT NOT NULL, PRIMARY KEY(skill_id,points));
CREATE TABLE equipment(id TEXT PRIMARY KEY, kind TEXT NOT NULL, group_name TEXT NOT NULL, ja TEXT NOT NULL, en TEXT NOT NULL, rarity INTEGER, job TEXT, sex TEXT, class_code TEXT, type_name TEXT, slots INTEGER, source_ja TEXT, source_en TEXT, metadata TEXT NOT NULL);
CREATE TABLE equipment_skills(equipment_id TEXT REFERENCES equipment(id), skill_id TEXT REFERENCES skills(id), points INTEGER NOT NULL, PRIMARY KEY(equipment_id,skill_id));
CREATE TABLE levels(equipment_id TEXT REFERENCES equipment(id), level TEXT, defense INTEGER, slots INTEGER, metadata TEXT NOT NULL, PRIMARY KEY(equipment_id,level));
CREATE TABLE abilities(equipment_id TEXT REFERENCES equipment(id), ordinal INTEGER, type_ja TEXT, value_ja TEXT, type_en TEXT, value_en TEXT, PRIMARY KEY(equipment_id,ordinal));
CREATE TABLE weapons(id INTEGER PRIMARY KEY, name TEXT, weapon_type TEXT, rarity INTEGER, raw_true INTEGER, raw_display INTEGER, slots_reported INTEGER, affinity INTEGER, defense INTEGER, excluded_hint INTEGER, stats_json TEXT, upgrades_json TEXT);
CREATE TABLE rain_overrides(entity_kind TEXT, entity_id TEXT, field TEXT, value_json TEXT, evidence TEXT NOT NULL, PRIMARY KEY(entity_kind,entity_id,field));
CREATE INDEX ix_equip_kind ON equipment(kind);
CREATE INDEX ix_equip_name ON equipment(ja,en);
CREATE INDEX ix_skill_points ON equipment_skills(skill_id,points);
'''

def dump(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True)

# Only accept the exact archive member by basename; never unpack or run executables.
def member(z, name):
    matches = [n for n in z.namelist() if n.rsplit('/',1)[-1] == name]
    if len(matches) != 1:
        matches = [n for n in matches if '/dat/' in n.lower() or n == name]
    if len(matches) != 1:
        raise ValueError(f'ambiguous/missing member: {name}: {matches}')
    return z.read(matches[0])

def root(z, name):
    return ET.fromstring(member(z,name))

def num(v):
    return int(v) if v not in (None,'') else None

def tree(el):
    return {'tag':el.tag,'attributes':el.attrib,'text':(el.text or '').strip(),'children':[tree(c) for c in el]}

def import_skills(db, ja, en):
    maps = [{},{}]
    for kind, file, tag, level_tag in [('normal','SkillBase.xml','Data','Option'),('zenith','TeniSkillBase.xml','SkillTree','Skill')]:
        a,b = [{x.attrib['ID']:x for x in root(z,file).iter(tag)} for z in (ja,en)]
        if a.keys()!=b.keys(): raise ValueError(f'{file}: skill IDs differ')
        for key,x in a.items():
            y=b[key]; sid=f'{kind}:{key}'
            for m,t in zip(maps,(x,y)):
                if kind=='normal':
                    name=t.attrib['Name']
                    if name in m: raise ValueError(f'duplicate normal skill {name}')
                    m[name]=sid
            db.execute('INSERT INTO skills VALUES(?,?,?,?,?,?)',(sid,kind,x.attrib['Name'],y.attrib['Name'],num(x.get('No')),dump({'ja':x.attrib,'en':y.attrib})))
            ax,bx=[{int(l.attrib['Point']):l for l in t.findall(level_tag)} for t in (x,y)]
            if ax.keys()!=bx.keys(): raise ValueError(f'{sid}: thresholds differ')
            for pt,l in ax.items():
                m=bx[pt]
                db.execute('INSERT INTO skill_levels VALUES(?,?,?,?,?)',(sid,pt,l.get('Name',l.text),m.get('Name',m.text),dump({'ja':tree(l),'en':tree(m)})))
    return maps

def points(node, mapping):
    result=Counter()
    for s in node.findall('./Skills/Skill'):
        result[mapping[s.text.strip()]]+=int(s.attrib['Point'])
    return dict(result)

def import_equipment(db, ja, en, maps):
    for kind,file in FILES.items():
        a,b=[list(root(z,file)) for z in (ja,en)]
        if len(a)!=len(b): raise ValueError(f'{file}: group count differs')
        for g,(ag,bg) in enumerate(zip(a,b)):
            ax,bx=ag.findall('Data'),bg.findall('Data')
            if len(ax)!=len(bx): raise ValueError(f'{file}: group count differs')
            for i,(x,y) in enumerate(zip(ax,bx)):
                eid=f'{kind}:{g}:{i}'
                p,q=points(x,maps[0]),points(y,maps[1])
                if p!=q: raise ValueError(f'{eid}: point mismatch')
                for attr in ('Rare','Job','Sex','Slot','Class'):
                    if x.get(attr)!=y.get(attr): raise ValueError(f'{eid}: {attr} mismatch')
                # Keep level-specific data and abilities instead of guessing slot rules.
                xl,yl=x.findall('./Level/*'),y.findall('./Level/*')
                if [(l.tag,l.get('Def'),l.get('Slot')) for l in xl]!=[(l.tag,l.get('Def'),l.get('Slot')) for l in yl]: raise ValueError(f'{eid}: level mismatch')
                aa,ba=x.findall('./Abilities/Ability'),y.findall('./Abilities/Ability')
                if len(aa)!=len(ba): raise ValueError(f'{eid}: ability count mismatch')
                db.execute('INSERT INTO equipment VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(eid,kind,ag.tag,x.get('Name'),y.get('Name'),num(x.get('Rare')),x.get('Job'),x.get('Sex'),x.get('Class'),x.get('Type'),num(x.get('Slot')),x.findtext('Source'),y.findtext('Source'),dump({'ja':x.attrib,'en':y.attrib,'elemental':x.find('Elemental').attrib if x.find('Elemental') is not None else {}})))
                db.executemany('INSERT INTO equipment_skills VALUES(?,?,?)',[(eid,s,v) for s,v in p.items()])
                db.executemany('INSERT INTO levels VALUES(?,?,?,?,?)',[(eid,l.tag,num(l.get('Def')),num(l.get('Slot')),dump({'ja':l.attrib,'en':m.attrib})) for l,m in zip(xl,yl)])
                db.executemany('INSERT INTO abilities VALUES(?,?,?,?,?,?)',[(eid,j,l.get('Type'),l.text,m.get('Type'),m.text) for j,(l,m) in enumerate(zip(aa,ba))])

def import_weapons(db,z):
    # Array index is the upstream weapon ID. Raw slots are not classified as decoration/sigil slots.
    for i,w in enumerate(json.loads(member(z,'melee.json'))):
        s=w['stats']; n=w['name']; raw=s['raw']
        flagged=int(i==0 or any(k in n.casefold() for k in ('dummy','delete','ダミー','削除')))
        db.execute('INSERT INTO weapons VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(i,n,s['weapon_type'],s['rarity'],raw['true_value'],raw['bloated_value'],s['slots'],s['affinity'],s['defense'],flagged,dump(s),dump(w['upgrades'])))

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for a in ('ja','en','pax','out'): p.add_argument('--'+a,required=True,type=Path)
    p.add_argument('--ferias',type=Path)
    args=p.parse_args()
    if args.out.exists(): p.error('output already exists; choose a new path')
    try:
        with sqlite3.connect(args.out) as db, zipfile.ZipFile(args.ja) as ja, zipfile.ZipFile(args.en) as en, zipfile.ZipFile(args.pax) as pax:
            db.executescript(SCHEMA)
            for k,f in [('ja',args.ja),('en',args.en),('pax',args.pax)]:
                db.execute('INSERT INTO sources VALUES(?,?,?,?)',(k,f.name,hashlib.file_digest(f.open('rb'),'sha256').hexdigest(),'upstream; Rain not verified'))
            maps=import_skills(db,ja,en)
            import_equipment(db,ja,en,maps)
            import_weapons(db,pax)
            if args.ferias:
                from ferias_import import import_ferias
                with args.ferias.open('rb') as f:
                    sha=hashlib.file_digest(f,'sha256').hexdigest()
                db.execute('INSERT INTO sources VALUES(?,?,?,?)',('ferias',args.ferias.name,sha,'upstream; Rain not verified'))
                with zipfile.ZipFile(args.ferias) as ferias:
                    print('ferias:',import_ferias(db,ferias),flush=True)
            if db.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('foreign key check failed')
            print('equipment:',db.execute('SELECT kind,count(*) FROM equipment GROUP BY kind').fetchall())
            for t in ('skills','skill_levels','equipment_skills','levels','abilities','weapons'):
                print(t,db.execute(f'SELECT count(*) FROM {t}').fetchone()[0])
            print('integrity:',db.execute('PRAGMA integrity_check').fetchone()[0])
    except BaseException:
        args.out.unlink(missing_ok=True)
        raise

if __name__=='__main__': main()
