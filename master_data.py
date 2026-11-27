"""Versioned local master extension; the original imported tables and IDs stay intact."""
import json
from functools import lru_cache
from pathlib import Path
from contextlib import closing
import sqlite3

VERSION = 1


def has_master(db):
    # A completed migration writes the marker last in the same transaction.
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_manifest'").fetchone():
        return False
    row = db.execute("SELECT value FROM master_manifest WHERE key='version'").fetchone()
    if not row or json.loads(row[0]) != VERSION:
        raise ValueError('Unsupported or incomplete master database')
    return True


def manifest(db):
    return {k:json.loads(v) for k,v in db.execute('SELECT key,value FROM master_manifest')} if has_master(db) else None


def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(',',':'))


@lru_cache(maxsize=2)
def weapon_mapping(path, size, mtime):
    # Cache a small source-name map, not the much larger variant table.
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        return {k:(en,ja) for k,en,ja in db.execute('SELECT source_key,en,ja FROM master_weapon_names')}


def read_weapon_mapping(db):
    path = Path(db.execute('PRAGMA database_list').fetchone()[2])
    if path.is_file():
        st=path.stat()
        return weapon_mapping(str(path),st.st_size,st.st_mtime_ns)
    return {k:(en,ja) for k,en,ja in db.execute('SELECT source_key,en,ja FROM master_weapon_names')}


def skill_reference(db, directory):
    if has_master(db):
        return [json.loads(r[0]) for r in db.execute('SELECT data FROM master_skill_reference ORDER BY ordinal')]
    from skill_catalog import catalog, descriptions, matched_description
    from materials import archive_path
    from skill_descriptions_ja import DETAILS
    from localization import skill_summary
    rows=catalog(db)
    for row in rows:
        row['description_ja']=DETAILS.get(row['ja'])
    try:
        source=archive_path(db, directory, 'ferias')
        details=descriptions(source,source.stat().st_mtime_ns)
    except (ValueError,OSError,KeyError,IndexError):
        return rows
    for row in rows:
        row['description_en']=matched_description(row,details)
        if not row['description_ja']:
            row['description_ja']=skill_summary(row,row['description_en'])
    return rows


def material_lookup(db, directory, name):
    if has_master(db):
        row=db.execute('SELECT data FROM master_material_sources WHERE name=?',(name,)).fetchone()
        return {'sources':json.loads(row[0]) if row else [], 'baseline':'ZZ'}
    from materials import archive_path
    from material_sources import lookup
    try:
        path=archive_path(db,directory,'ferias')
        return {'sources':lookup(path,name),'baseline':'ZZ'}
    except (ValueError,OSError):
        return {'sources':[],'baseline':'ZZ','unavailable':True}


# Store only fields used by the recipe planner, not entire XML or HTML archives.
def equipment_recipe(node):
    def costs(parent):
        return [{'type':c.get('Type'), 'items':[[i.text,i.get('Num')] for i in c.findall('Item')]} for c in parent.findall('Cost')]
    src=node.find('Source')
    return {'name':node.get('Name'),'type':node.get('Type'),'class':node.get('Class'),
            'source':[src.text,src.get('Level')] if src is not None else None,
            'sources':[[s.text,s.get('Type')] for s in node.findall('./Sources/Source')],
            'levels':[[l.tag,costs(l)] for l in node.findall('./Level/*')], 'costs':costs(node)}


def recipe_node(data):
    # Adapter for the existing planner's XML interface; only normalized fields are reconstructed.
    from xml.etree import ElementTree as ET
    def node(parent,tag,attrs,text=None):
        n=ET.SubElement(parent,tag,{k:v for k,v in attrs.items() if v is not None});n.text=text;return n
    def costs(parent,records):
        for c in records:
            n=node(parent,'Cost',{'Type':c['type']})
            for name,qty in c['items']:node(n,'Item',{'Num':qty},name)
    root=ET.Element('Data',{k:v for k,v in {'Name':data['name'],'Type':data['type'],'Class':data['class']}.items() if v is not None})
    if data['source'] is not None:node(root,'Source',{'Level':data['source'][1]},data['source'][0])
    srcs=node(root,'Sources',{})
    for name,typ in data['sources']:node(srcs,'Source',{'Type':typ},name)
    levels=node(root,'Level',{})
    for level,rows in data['levels']:costs(node(levels,level,{}),rows)
    costs(root,data['costs'])
    return root


class RecipeRecords:
    def __init__(self,db):self.db=db
    def __getitem__(self,eid):
        row=self.db.execute('SELECT data FROM master_equipment_recipes WHERE equipment_id=?',(eid,)).fetchone()
        if not row:raise KeyError(eid)
        return recipe_node(json.loads(row[0]))


class RecipeNames:
    def __init__(self,db,kind):self.db=db;self.kind=kind
    def get(self,name,default):
        rows=[r[0] for r in self.db.execute('SELECT equipment_id FROM master_equipment_recipes WHERE kind=? AND name=?',(self.kind,name))]
        return rows or default
