"""Extract Japanese names already present in the imported source data."""
import re
import json
import zipfile
from pathlib import Path
from functools import lru_cache
from collections import defaultdict

JAPANESE = re.compile(r'[ぁ-ゖァ-ヺ一-龯々]')
PREFIX = re.compile(r'^([0-9A-Fa-f]{4})[・：:]\s*(.+)$')


def clean_name(value, weapon_id):
    # Strip a hexadecimal source prefix only when it encodes this weapon ID.
    if not value or not JAPANESE.search(value):
        return None
    match = PREFIX.match(value)
    if match:
        raw = bytes.fromhex(match[1])
        if int.from_bytes(raw, 'little') != weapon_id and int.from_bytes(raw, 'big') != weapon_id:
            return None
        value = match[2]
    return value


def japanese_name(weapon_id, explicit, variant, base, pax):
    # Prefer the explicit name; do not invent translations or choose between conflicting sources.
    if explicit and JAPANESE.search(explicit):
        return clean_name(explicit, weapon_id)
    names = [clean_name(v, weapon_id) for v in (variant, base, pax)]
    names = {v for v in names if v}
    return next(iter(names)) if len(names) == 1 else None


# The local Ferias equipment search explicitly maps this type prefix to each weapon family.
TYPE_PREFIX = dict(zip(['GS','HBG','Hammer','Lance','SnS','LBG','DB','LS','HH','GL','Bow','Tonfas','SA','MS'],'0123456789ABCD'))
NAME_RECORD = re.compile(r'^,?"([0-9A-Fa-f]{5})":("(?:[^"\\]|\\.)*")$')


def name_section(text):
    body=text.split('Name : {',1)[1].split('\n}',1)[0]
    result=defaultdict(set)
    for line in body.splitlines():
        m=NAME_RECORD.fullmatch(line.strip())
        if m:
            try:result[m[1]].add(json.loads(m[2]))
            except ValueError:continue
    return {k:next(iter(v)) for k,v in result.items() if len(v)==1}


@lru_cache(maxsize=2)
def local_names(path,mtime):
    with zipfile.ZipFile(path) as z:
        paths=[n for n in z.namelist() if n.endswith('/sozai/buki_sozai.js')]
        if len(paths)!=1:return {}
        data=z.read(paths[0]).decode('utf-8-sig')
    en,ja=data.split('var setBukiJP = function ()',1)
    en,ja=name_section(en),name_section(ja)
    return {k:(en[k],v) for k,v in ja.items() if k in en and JAPANESE.search(v)}


def normalized_name(s):
    # The two Ferias tables use brackets versus quotes for the same suffix.
    return re.sub(r'\s+',' ',(s or '').replace('[','"').replace(']','"')).strip().casefold()


def matched_local_name(mapping,wt,wid,variant,base):
    prefix=TYPE_PREFIX.get(wt)
    if prefix is None or not isinstance(wid,int):return None
    pair=mapping.get(prefix+f'{wid:04X}')
    if not pair:return None
    en,ja=pair
    # Match the variant itself, never replace a different progression name with a base name.
    if normalized_name(variant)==normalized_name(en) or clean_name(variant,wid)==ja:
        return clean_name(ja,wid)
    return None


def register(db):
    db.create_function('weapon_ja', 5, japanese_name, deterministic=True)
    mapping={}
    from master_data import has_master, read_weapon_mapping
    if has_master(db):
        mapping=read_weapon_mapping(db)
        db.create_function('weapon_ja_local',4,lambda wt,wid,v,b:matched_local_name(mapping,wt,wid,v,b),deterministic=True)
        return
    try:
        from materials import archive_path
        path=Path(db.execute('PRAGMA database_list').fetchone()[2])
        archive=archive_path(db,path.parent,'ferias')
        mapping=local_names(archive,archive.stat().st_mtime_ns)
    except (ValueError,OSError,IndexError,TypeError,KeyError):
        pass
    db.create_function('weapon_ja_local',4,lambda wt,wid,v,b:matched_local_name(mapping,wt,wid,v,b),deterministic=True)


JA = 'COALESCE(weapon_ja_local(v.weapon_type,v.upstream_id,v.name_source,w.name_source),weapon_ja(v.upstream_id,w.name_ja,v.name_source,w.name_source,p.name))'
JOIN = 'ferias_variants v JOIN ferias_weapons w USING(weapon_type,upstream_id) LEFT JOIN weapons p ON p.id=w.pax_id'
