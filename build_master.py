"""Build a self-contained local master database from the user's imported DB and verified ZIPs."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
from contextlib import closing
from master_data import VERSION, pack, equipment_recipe, skill_reference
from materials import archive_path, item_names, equipment_data, weapon_rows, weapon_record, PARTS
from weapon_names import local_names, register, JA, JOIN
from material_sources import source_index, lookup

SCHEMA='''
CREATE TABLE master_manifest(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE master_weapon_names(source_key TEXT PRIMARY KEY,en TEXT NOT NULL,ja TEXT NOT NULL);
CREATE TABLE master_item_names(ja TEXT NOT NULL,en TEXT NOT NULL,PRIMARY KEY(ja,en));
CREATE TABLE master_equipment_recipes(equipment_id TEXT PRIMARY KEY REFERENCES equipment(id),kind TEXT NOT NULL,name TEXT NOT NULL,data TEXT NOT NULL);
CREATE INDEX master_recipe_name ON master_equipment_recipes(kind,name);
CREATE TABLE master_weapon_recipes(page TEXT NOT NULL,anchor TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(page,anchor));
CREATE TABLE master_skill_reference(ordinal INTEGER PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE master_material_sources(name TEXT PRIMARY KEY,data TEXT NOT NULL);
CREATE TABLE master_rule_reference(key TEXT PRIMARY KEY,data TEXT NOT NULL);
'''


def migrate(source, output, archives=None):
    source,output=Path(source).resolve(),Path(output).resolve()
    directory=Path(archives).resolve() if archives else source.parent
    if output.exists() or source==output:raise ValueError('Output already exists; choose a new path. Original database is not overwritten.')
    if not source.is_file():raise ValueError('Input database not found')
    output.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.mhf-master-',suffix='.sqlite',dir=output.parent);os.close(fd)
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as base, closing(sqlite3.connect(tmp)) as db:
            base.row_factory=db.row_factory=sqlite3.Row
            # Verify each archive we actually parse before creating new tables.
            ja,en,ferias=[archive_path(base,directory,k) for k in ('ja','en','ferias')]
            sources=[dict(r) for r in base.execute('SELECT * FROM sources ORDER BY id')]
            if base.execute("SELECT 1 FROM sqlite_master WHERE name='master_manifest'").fetchone():raise ValueError('Input is already a master database')
            core=('equipment','skills','skill_levels','equipment_skills','levels','abilities','weapons','ferias_weapons','ferias_variants','ferias_zenith','sigil_reference_rows')
            counts={t:base.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in core}
            base.backup(db)
            db.execute('PRAGMA foreign_keys=ON')
            # Read descriptions before adding the master marker table.
            skills=skill_reference(base,directory)
            db.executescript(SCHEMA)
            with db:
                print('Weapon names / skill descriptions...',flush=True)
                mapping=local_names(ferias,ferias.stat().st_mtime_ns)
                if not mapping or len(skills)!=counts['skill_levels']:raise ValueError('Reference data incomplete')
                db.executemany('INSERT INTO master_weapon_names VALUES(?,?,?)',((k,*v) for k,v in mapping.items()))
                db.executemany('INSERT INTO master_skill_reference VALUES(?,?)',((i,pack(r)) for i,r in enumerate(skills)))
                print('Equipment recipes / item names...',flush=True)
                jnames,_=item_names(ja,en)
                db.executemany('INSERT INTO master_item_names VALUES(?,?)',((j,e) for j,es in jnames.items() for e in sorted(es)))
                for kind in (*PARTS,'jewel','cuff'):
                    nodes,_=equipment_data(ja,kind)
                    existing={r[0]:r[1] for r in db.execute('SELECT id,ja FROM equipment WHERE kind=?',(kind,))}
                    if existing!={k:x.get('Name') for k,x in nodes.items()}:raise ValueError(f'Equipment ID mismatch: {kind}')
                    db.executemany('INSERT INTO master_equipment_recipes VALUES(?,?,?,?)',((k,kind,x.get('Name'),pack(equipment_recipe(x))) for k,x in nodes.items()))
                print('Weapon recipes...',flush=True)
                pages=db.execute('SELECT DISTINCT page,weapon_type FROM ferias_variants ORDER BY page').fetchall()
                unsupported=0
                for page,wt in pages:
                    if not re.fullmatch(r'buki/[a-z]+(?:_g|_sp|_n)?\.htm',page):continue
                    ci=8 if wt in ('LBG','HBG','Bow') else 7
                    records=[]
                    for anchor,cells in weapon_rows(ferias,page).items():
                        record=weapon_record(cells,ci)
                        if record is None:unsupported+=1;continue
                        records.append((page,anchor,pack(record)))
                    db.executemany('INSERT INTO master_weapon_recipes VALUES(?,?,?)',records)
                print('Material acquisition references...',flush=True)
                names,_,quests=source_index(ferias,ferias.stat().st_mtime_ns)
                db.executemany('INSERT INTO master_material_sources VALUES(?,?)',((n,pack(rows)) for n in sorted(names) if (rows:=lookup(ferias,n))))
                from external import MEALS,ROAD_COSTS,ROAD_SINGLE,ROAD_ALL,ROAD_DEF,ROAD_ATK,ADVANCE
                from bounty import GROUPS,SOURCE,public_rules
                refs={'meals':MEALS,'road_costs':ROAD_COSTS,'road_single':ROAD_SINGLE,'road_all':ROAD_ALL,'road_defense':ROAD_DEF,'road_attack':ROAD_ATK,'road_advance':ADVANCE,'bounty_source':SOURCE,'bounties':{f'{g}:{n}:{mode}':public_rules({'group':g,'number':n,'mode':mode}) for g,ns in GROUPS.items() for n in ns for mode in ('solo','multi')}}
                db.executemany('INSERT INTO master_rule_reference VALUES(?,?)',((k,pack(v)) for k,v in refs.items()))
                extra={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('master_weapon_names','master_item_names','master_equipment_recipes','master_weapon_recipes','master_skill_reference','master_material_sources','master_rule_reference')}
                data={'version':VERSION,'baseline':'ZZ','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources':sources,'counts':{**counts,**extra},'coverage':{'skill_descriptions_ja':sum(bool(r.get('description_ja')) for r in skills),'skill_descriptions_en':sum(bool(r.get('description_en')) for r in skills),'unsupported_weapon_rows':unsupported,'quest_names_in_source':len(quests.get('Name',{}))},'rain_verified':False,'notes':['Source hashes checked for ja/en/ferias; Pax retained from original import.','Recipes and sources retain legacy parser coverage; special weapon recipes and ambiguous matches are not inferred.','External/bounty rules are reference snapshots; runtime logic remains in application code.']}
                db.executemany('INSERT INTO master_manifest VALUES(?,?)',((k,pack(v)) for k,v in data.items()))
                # Register from the just-created master map directly, avoiding a second connection before commit.
                from weapon_names import japanese_name,matched_local_name
                db.create_function('weapon_ja',5,japanese_name,deterministic=True)
                db.create_function('weapon_ja_local',4,lambda wt,wid,v,b:matched_local_name(mapping,wt,wid,v,b),deterministic=True)
                data['coverage']['japanese_weapon_variants']=db.execute(f'SELECT count(*) FROM {JOIN} WHERE {JA} IS NOT NULL').fetchone()[0]
                db.execute('UPDATE master_manifest SET value=? WHERE key=?',(pack(data['coverage']),'coverage'))
                if any(db.execute(f'SELECT count(*) FROM {t}').fetchone()[0]!=n for t,n in counts.items()):raise ValueError('Core counts changed')
                if db.execute('PRAGMA foreign_key_check').fetchone():raise ValueError('Foreign key validation failed')
                if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('SQLite integrity validation failed')
            print(json.dumps(data,ensure_ascii=False,indent=2),flush=True)
        if output.exists():raise FileExistsError(output)
        # Publish only after all checks; never replace an existing destination.
        if os.name=='nt':os.rename(tmp,output)
        else:os.link(tmp,output)
        return data
    finally:
        Path(tmp).unlink(missing_ok=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',type=Path,default=Path('mhf.sqlite'))
    p.add_argument('--out',type=Path,default=Path('mhf_master.sqlite'))
    p.add_argument('--archives',type=Path,help='Optional folder containing original ZIPs')
    a=p.parse_args();migrate(a.db,a.out,a.archives)
