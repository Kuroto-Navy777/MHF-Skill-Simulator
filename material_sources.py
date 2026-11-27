"""Parse local Ferias data records as text; never execute upstream JavaScript."""
import json
import re
from collections import defaultdict
from functools import lru_cache
import zipfile

# A quoted string is accepted only if JSON can decode it completely.
PAIR = re.compile(r'^\s*,?\s*("(?:[^"\\]|\\.)*")\s*:\s*("(?:[^"\\]|\\.)*")\s*,?\s*$')
ARRAY = re.compile(r'^\s*,?\s*"([0-9A-F]{4})"\s*:\s*(\[.*\])\s*,?\s*$')
SECTION = re.compile(r'^\s*,?\s*(\w+)\s*:\s*\{(.*)$')


def member(z, suffix):
    names=[n for n in z.namelist() if n.endswith('/sozai/'+suffix)]
    if len(names)!=1: raise ValueError('Ambiguous Ferias material file')
    return z.read(names[0]).decode('utf-8-sig')


def sections(text):
    out=defaultdict(dict); section=None
    for line in text.splitlines():
        m=SECTION.fullmatch(line)
        if m:
            section=m[1]; line=m[2]
            if not line.strip(): continue
        if line.strip().startswith('}'): section=None; continue
        m=PAIR.fullmatch(line)
        if section and m:
            try: out[section][json.loads(m[1])]=json.loads(m[2])
            except ValueError: continue
    return out


@lru_cache(maxsize=2)
def source_index(path, mtime_ns):
    # Exact unique English item names only. Different translations remain unresolved.
    names=defaultdict(set)
    with zipfile.ZipFile(path) as z:
        for line in member(z,'item.js').splitlines():
            m=ARRAY.fullmatch(line)
            if m:
                try:
                    data=json.loads(m[2]); names[data[0]].add(m[1])
                except (ValueError,IndexError,TypeError): continue
        monsters=sections(member(z,'mos_sozai.js'))
        quests=sections(member(z,'que_sozai.js'))
    return names,monsters,quests


def lookup(path,name):
    names,monsters,quests=source_index(path,path.stat().st_mtime_ns)
    ids=names.get(name,set())
    if len(ids)!=1:return []
    iid=next(iter(ids)); out=[]; ranks={'Kai':'HR1–4','Zyoui':'HR upper','Sugo':'HR5 / HC','G':'G / Zenith'}
    # Monster and quest text is retained in its source language. No probabilities are inferred.
    for rank,label in ranks.items():
        for entry in monsters.get(rank,{}).get(iid,'').split(','):
            if '|' not in entry:continue
            key,detail=entry.split('|',1); monster=monsters['Name'].get(key)
            if monster and detail:out.append({'kind':'monster','rank':label,'name':monster,'detail':detail})
        for entry in quests.get(rank,{}).get(iid,'').split(','):
            info=quests.get('Name',{}).get(entry[:4],'').split(',',4)
            if len(info)==5 and info[4]:out.append({'kind':'quest','rank':info[3] or label,'name':info[4],'detail':''})
    # Deduplicate and cap display without guessing missing entries.
    from localization import MONSTERS, material_detail
    for x in out:
        x['name_ja']=MONSTERS.get(x['name']) if x['kind']=='monster' else None
        x['detail_ja']=material_detail(x['detail'])
    return list({(x['kind'],x['rank'],x['name'],x['detail']):x for x in out}.values())[:100]
