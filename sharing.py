"""Portable build exchange and conservative MHSX2G-style text parsing."""
import json
import re
import unicodedata
from skill_engine import Engine, PARTS, WEAPON_SECRET
from external import normalize

FORMAT = 'mhf-skill-build'
MAX_TEXT = 100_000

# Names may differ only in width or decorative brackets in forum clips.
def norm(value):
    return unicodedata.normalize('NFKC', value).translate(str.maketrans('〖〗【】','[][]')).casefold().strip()

# Prefer exact IDs/names, and never select one of multiple matching entries arbitrarily.
def resolve(db, kind, key, job, sex):
    if not isinstance(key, str) or not key.strip() or len(key)>300:
        raise ValueError(f'{kind}: invalid item name or ID')
    rows = db.execute('SELECT id,ja,en,job,sex FROM equipment WHERE kind=? AND (id=? OR ja=? OR en=?)',(kind,key,key,key)).fetchall()
    if not rows:
        db.create_function('clip_norm',1,norm,deterministic=True)
        rows=db.execute('SELECT id,ja,en,job,sex FROM equipment WHERE kind=? AND (clip_norm(ja)=? OR clip_norm(en)=?)',(kind,norm(key),norm(key))).fetchall()
    compatible=[r for r in rows if r['job'] in (None,'共',job) and r['sex'] in (None,'共',sex)]
    if len(compatible)!=1:
        raise ValueError(f'{kind}: {key}: {len(compatible)} compatible matches (expected 1)')
    return compatible[0]['id']

# Only build fields are accepted; never trust exported evaluations or search results.
def canonical_build(db, raw):
    if not isinstance(raw,dict): raise ValueError('build must be an object')
    wt=raw.get('weapon_type'); sex=raw.get('sex'); job=raw.get('job')
    if wt not in WEAPON_SECRET or sex not in ('男','女') or job!=('ガンナー' if wt in ('LBG','HBG','Bow') else '剣士'):
        raise ValueError('invalid weapon type, sex or job')
    b={'weapon_type':wt,'sex':sex,'job':job,'armor':{}}
    for k in ('g_poogie','premium_poogie_clothes'):
        if type(raw.get(k)) is not bool: raise ValueError(f'{k}: boolean required')
        b[k]=raw[k]
    def items(kind, values, limit):
        if not isinstance(values,list) or len(values)>limit: raise ValueError(f'{kind}: invalid item list')
        return [resolve(db,kind,x,job,sex) for x in values]
    arm=raw.get('armor')
    if not isinstance(arm,dict) or set(arm)-set(PARTS): raise ValueError('invalid armor parts')
    for p,a in arm.items():
        if not isinstance(a,dict) or not isinstance(a.get('level'),str) or not re.fullmatch(r'L[0-9]{1,3}',a['level']): raise ValueError(f'{p}: explicit level required')
        b['armor'][p]={'item':resolve(db,p,a.get('item'),job,sex),'level':a['level'],'jewels':items('jewel',a.get('jewels',[]),3)}
    w=raw.get('weapon')
    if w is not None:
        if not isinstance(w,dict) or 'template' in w or not all(isinstance(w.get(k),str) and 0<len(w[k])<=300 for k in ('page','anchor')): raise ValueError('select a physical weapon variant; templates are not supported for exchange')
        s=w.get('sigils',0)
        if type(s) is not int or not 0<=s<=3: raise ValueError('invalid sigil count')
        b['weapon']={'page':w['page'],'anchor':w['anchor'],'sigils':s,'jewels':items('jewel',w.get('jewels',[]),3)}
    b['cuffs']=items('cuff',raw.get('cuffs',[]),2)
    if 'external' in raw: b['external']=normalize(raw['external'])
    return b

# Share stable selectors, not third-party database records or cached evaluations.
def envelope(b):
    return {'format':FORMAT,'version':1,'baseline':'MHF-ZZ / Rain unverified','build':b}

# Accept the previous raw JSON copy format as well as the new versioned envelope.
def decode_json(text):
    obj=json.loads(text)
    if not isinstance(obj,dict): raise ValueError('JSON build must be an object')
    if 'format' in obj:
        if obj['format']!=FORMAT or type(obj.get('version')) is not int or obj['version']!=1: raise ValueError('unsupported build format/version')
        return obj.get('build')
    return obj

# Slot symbols delimit the equipment and decoration/cuff names in common Japanese clips.
MARK=re.compile(r'[●○■□★☆－−]+')
def tail(line):
    m=MARK.search(line)
    if not m: return []
    return [v.strip() for v in re.split('[,、，]',line[m.end():]) if v.strip() and not re.fullmatch(r'[【〖\[]?空き.*?[】〗\]]?',v.strip())]

# Weapon type is not present in the usual clip header; the user must supply it.
def decode_clip(text, context):
    lines=[x.strip() for x in text.splitlines() if x.strip()]
    if not lines: raise ValueError('empty clip')
    h=re.fullmatch(r'MHSX2G?\s+装備クリップ\s*(剣士|ガンナー)\s*\(\s*(男|女)\s*\)',unicodedata.normalize('NFKC',lines[0]))
    if not h: raise ValueError('MHSX2G header required (Japanese, multiline)')
    if not isinstance(context,dict): raise ValueError('clip context required')
    b={'job':h[1],'sex':h[2],'weapon_type':context.get('weapon_type'),'g_poogie':context.get('g_poogie'),'premium_poogie_clothes':context.get('premium_poogie_clothes'),'armor':{},'cuffs':[]}
    warnings=['Clip weapon type and Poogie settings are taken from the current editor; skill summaries are recalculated.']
    if len(lines)<2: raise ValueError('weapon line required')
    wline=lines[1]; nline=unicodedata.normalize('NFKC',wline)
    if not nline.startswith('武器スロットなし'):
        w=context.get('weapon')
        if not isinstance(w,dict): raise ValueError('Weapon line needs a physical weapon: select the matching fixed weapon in the editor, then retry.')
        b['weapon']={**w,'jewels':tail(wline)}
        warnings.append('Clip weapon name/Zenith effect/sigil count is not inferred: selected physical weapon and reserved sigils are used. Verify the match.')
    else:
        warnings.append('The no-weapon-slot line is imported without a physical weapon. Select one manually if needed.')
    idx=0; cuff_seen=False
    for line in lines[2:]:
        if line.startswith(('防御値','防御力','発動スキル','辿異スキル','遷悠防具スキル','自動発動')): break
        if re.match(r'服[PSＰＳ]?スロット',line):
            if cuff_seen: raise ValueError('duplicate cuff line')
            b['cuffs']=tail(line);cuff_seen=True;continue
        if cuff_seen or idx>=5: raise ValueError(f'unrecognized equipment line: {line[:100]}')
        # Strip the source classification suffix and defense; leave the actual item name intact.
        m=re.search(r'\s+Lv\s*(\d+)\s*',unicodedata.normalize('NFKC',line),re.I)
        if not m: raise ValueError(f'armor level missing: {line[:100]}')
        prefix=re.split(r'\s+Lv\s*\d+',line,maxsplit=1,flags=re.I)[0].strip()
        prefix=re.sub(r'\s+[（(][^()（）]*[)）]\s*$','',prefix).strip()
        b['armor'][PARTS[idx]]={'item':prefix,'level':'L'+m[1],'jewels':tail(line)};idx+=1
    if idx!=5 or not cuff_seen: raise ValueError('five armor lines and one cuff line required')
    return b,warnings

# Produce a readable clip; exact weapon identity and other metadata are preserved in JSON instead.
def encode_clip(db,b,evaluation):
    if set(b['armor'])!=set(PARTS): raise ValueError('clip export requires five armor parts; use JSON for partial builds')
    def item(k): return db.execute('SELECT ja,slots FROM equipment WHERE id=?',(k,)).fetchone()
    def jewels(keys): return ', '.join(item(k)['ja'] for k in keys)
    def marks(keys,cap,filled='●',empty='○'):
        used=sum(item(k)['slots'] for k in keys)
        return filled*used+empty*max(0,cap-used)
    lines=[f"MHSX2G 装備クリップ {b['job']}({b['sex']})"]
    w=b.get('weapon')
    if w:
        a=next(x for x in evaluation['slots']['equipment'] if x['part']=='weapon')
        keys=w['jewels']; cap=max(0,(a['capacity'] or 0)-w['sigils']) if a['mode'] in ('shared','decoration') else 0
        lines.append(f'武器スロット{cap}  {marks(keys,cap)}  {jewels(keys)}'.rstrip())
    else: lines.append('武器スロットなし')
    for p in PARTS:
        a=b['armor'][p]; r=item(a['item']); lv=db.execute('SELECT defense,slots FROM levels WHERE equipment_id=? AND level=?',(a['item'],a['level'])).fetchone()
        lines.append(f"{r['ja']}  Lv{a['level'][1:]}  {lv['defense'] if lv['defense'] is not None else '-'}  {marks(a['jewels'],lv['slots'])}  {jewels(a['jewels'])}".rstrip())
    c=b['cuffs']; secret=any(db.execute("SELECT 1 FROM abilities WHERE equipment_id=? AND type_ja='スキル枠消費なし'",(k,)).fetchone() for k in c)
    lines.append(f'服Pスロット２  {"●" if secret else ""}{marks(c,2,"★","－")}  {jewels(c)}'.rstrip())
    lines.append('発動スキル（シミュレーター計算・Rain未検証）')
    lines.append(', '.join(s['level_ja'] for s in evaluation['skills'] if s['status']=='active'))
    lines.append('辿異スキル');lines.append(', '.join(s['ja'] for s in evaluation['zenith'] if s['level']>0))
    return '\n'.join(lines)

# Resolve and recalculate on the receiving user's database before displaying the build.
def import_build(db,text,fmt,context):
    if not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT: raise ValueError('invalid or oversized import text')
    if fmt=='json': raw=decode_json(text); warnings=[]
    elif fmt=='clip': raw,warnings=decode_clip(text,context)
    else: raise ValueError('unsupported import format')
    b=canonical_build(db,raw); r=Engine(db).evaluate(b)
    if not r['valid']: raise ValueError('; '.join(r['errors']))
    return b,r,warnings
