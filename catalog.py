"""Paged catalog on the existing read-only Phase 5A database."""
import json
import re
import unicodedata
from weapon_names import JA, JOIN, register

ARMOR = {'head','body','arm','waist','leg'}
RANKS = {'G','GF','GX','GP','GS','Z','ZF','ZY','ZX','ZP','other'}

# Rank is derived from the source name and type, not guessed from rarity.
def armor_rank(ja, en, type_name):
    if not type_name or not ('Ｇ級' in type_name or '辿異' in type_name):
        return 'other'
    group = ('ZF','ZY','ZX','ZP','Z') if '辿異' in type_name else ('GF','GX','GP','GS','G')
    for text in (ja,en):
        normalized = unicodedata.normalize('NFKC',text or '')
        for rank in group:
            if re.search(r'(?<![A-Za-z])'+rank+r'(?![A-Za-z])',normalized):
                return rank
    return 'other'

# Normalize full/half-width characters for literal Japanese and English name matching.
def normalized(value):
    return unicodedata.normalize('NFKC',value or '').casefold()

# Return the highest recorded reinforcement level, with no fabricated values.
def latest_level(db, item_id, mode='max'):
    order='ASC' if mode=='first' else 'DESC'
    row = db.execute(f'SELECT level,defense,slots FROM levels WHERE equipment_id=? AND slots IS NOT NULL ORDER BY CAST(substr(level,2) AS INTEGER) {order}, level {order} LIMIT 1',(item_id,)).fetchone()
    return dict(row) if row else {}

# Preserve ordinary and zenith skills separately, alongside source-defined abilities.
def decorate_item(db,row,level_mode='max'):
    r=dict(row); meta=json.loads(r.pop('metadata'))
    r['rank']=armor_rank(r['ja'],r['en'],r['type_name']) if r['kind'] in ARMOR else None
    r['resistances']=meta.get('elemental',{})
    r['latest']=latest_level(db,r['id'])
    r['first']=latest_level(db,r['id'],'first')
    selected=r['first'] if level_mode=='first' else r['latest']
    if selected.get('slots') is not None: r['slots']=selected['slots']
    r['skills']=[dict(x) for x in db.execute('SELECT s.ja,s.en,s.kind,p.points FROM equipment_skills p JOIN skills s ON s.id=p.skill_id WHERE p.equipment_id=? ORDER BY s.kind,s.priority,s.id',(r['id'],))]
    r['abilities']=[dict(x) for x in db.execute('SELECT type_ja,value_ja,type_en,value_en FROM abilities WHERE equipment_id=? ORDER BY ordinal',(r['id'],))]
    return r

# Count and page the same filtered query; only enrich rows in the requested page.
def catalog(db, *, kind,q,weapon_type,page,page_size,rank,job,sex,hide_unavailable,hide_paid,hide_festival,sort,lang,level_mode='max'):
    db.create_function('norm',1,normalized,deterministic=True)
    db.create_function('armor_rank',3,armor_rank,deterministic=True)
    needle=normalized(q)
    if kind=='weapon':
        register(db)
        where=['v.weapon_type=?',f'(instr(norm(v.name_source),?)>0 OR instr(norm({JA}),?)>0)']; params=[weapon_type,needle,needle]
        base=JOIN
        select=f'v.weapon_type,v.upstream_id,v.page,v.anchor,v.name_source AS en,COALESCE({JA},v.name_source) AS ja,{JA} AS name_ja,v.level,v.rarity,v.attack,v.affinity,v.category,v.slots_reported AS slots,v.slot_mode,w.conflict'
        orders={'rarity':'v.rarity DESC','name':'norm('+(f'COALESCE({JA},v.name_source)' if lang=='ja' else 'v.name_source')+')','defense':'v.attack DESC','attack':'v.attack DESC'}
        order=orders[sort]+', v.page,v.anchor'
    else:
        where=['e.kind=?','(instr(norm(e.ja),?)>0 OR instr(norm(e.en),?)>0 OR e.id=?)'];params=[kind,needle,needle,q]
        base='equipment e'; select='e.*'
        if hide_unavailable: where.append("COALESCE(e.class_code,'') NOT IN ('(未)','(不)')")
        if hide_paid: where.append("COALESCE(e.class_code,'') NOT GLOB '(ガ*' AND COALESCE(e.class_code,'') NOT GLOB '(キ*' AND COALESCE(e.class_code,'') NOT GLOB '(パ*' AND COALESCE(e.class_code,'') NOT GLOB '(ネ*'")
        if hide_festival: where.append("COALESCE(e.class_code,'') NOT GLOB '(祭*'")
        if kind in ARMOR:
            if rank: where.append('armor_rank(e.ja,e.en,e.type_name)=?'); params.append(rank)
            if job: where.append("(e.job IS NULL OR e.job='共' OR e.job=?)"); params.append(job)
            if sex: where.append("(e.sex IS NULL OR e.sex='共' OR e.sex=?)"); params.append(sex)
        level_order='ASC' if level_mode=='first' else 'DESC'
        orders={'rarity':'e.rarity DESC','name':'norm(e.'+lang+')','defense':f'(SELECT l.defense FROM levels l WHERE l.equipment_id=e.id AND l.slots IS NOT NULL ORDER BY CAST(substr(l.level,2) AS INTEGER) {level_order},l.level {level_order} LIMIT 1) DESC','attack':'e.rarity DESC'}
        order=orders[sort]+', e.id'
    condition=' WHERE '+' AND '.join(where)
    total=db.execute('SELECT count(*) FROM '+base+condition,params).fetchone()[0]
    rows=db.execute('SELECT '+select+' FROM '+base+condition+' ORDER BY '+order+' LIMIT ? OFFSET ?',params+[page_size,(page-1)*page_size]).fetchall()
    if kind=='weapon':
        items=[]
        for row in rows:
            r=dict(row)
            r['skills']=[dict(x) for x in db.execute('SELECT s.ja,s.en,s.kind,z.points FROM ferias_zenith z JOIN skills s ON s.id=z.skill_id WHERE z.weapon_type=? AND z.page=? AND z.anchor=? ORDER BY z.ordinal',(weapon_type,r['page'],r['anchor']))]
            items.append(r)
    else: items=[decorate_item(db,r,level_mode) for r in rows]
    return {'items':items,'total':total,'page':page,'page_size':page_size,'pages':(total+page_size-1)//page_size}
