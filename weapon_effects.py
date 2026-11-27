"""Exact declared Ferias weapon skill mappings; unknown text is never guessed.

Only the source-labelled Burst/Origin skills are automatic. This does not model
armor rank-up, tower stones, random sigils or Rain-specific weapon overrides.
"""
import json
import re

ALIASES={'Wrath Awoken':'逆鱗','Buchigire':'ブチギレ','Evade Distance Up':'回避距離UP'}

def intrinsic_levels(engine,row):
    entries=json.loads(row['intrinsic_raw']);levels=[];unmapped=[]
    for text in entries:
        m=re.fullmatch(r'≪(Burst|Origin) Weapon[:：]([^≪≫]+)≫',text.strip())
        category={'Burst':'烈種武器','Origin':'始種武器'}
        if not m or row['category']!=category[m[1]]:
            unmapped.append(text);continue
        label=m[2].strip();ja=ALIASES.get(label)
        normalize=lambda s:re.sub(r'\s+','',s or '').casefold()
        matches=[t for sid,tiers in engine.levels.items() if sid.startswith('normal:') for t in tiers
                 if (t['ja']==ja if ja else normalize(t['en'])==normalize(label))]
        if len(matches)==1 and matches[0]['points']>0:levels.append(matches[0])
        else:unmapped.append(text)
    return levels,unmapped
