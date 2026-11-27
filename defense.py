"""Armor-only defense/resistance totals and explicit flat skill modifiers.
Not a lobby or quest damage model. No GR, road, food, weapon or dynamic buffs.
"""
import json
import re
from collections import Counter
from external import normalize, contributions, road_cost, weapon_delta

ELEMENTS = ('Fire', 'Water', 'Thunder', 'Ice', 'Dragon')
STATS = ('defense', *ELEMENTS)
PREFIX = {'防御':'defense', '各耐性':'all', **{j+'耐性':e for j,e in zip('火水雷氷龍', ELEMENTS)}}
OBJECTIVES = ('defense', 'resistance')

# The explicit numeric skill label is the effect magnitude, not the activation points.
def skill_modifier(name):
    m = re.fullmatch(r'(防御|各耐性|[火水雷氷龍]耐性)([+-]\d+)', name or '')
    if not m:
        return {}
    k = PREFIX[m[1]]
    return {e:int(m[2]) for e in (ELEMENTS if k=='all' else (k,))}

# Read source armor resistance values without silently treating missing data as zero.
def armor_values(metadata, defense):
    values = json.loads(metadata).get('elemental', {})
    return {'defense':defense, **{k:int(values[k]) if values.get(k) not in (None,'') else None for k in ELEMENTS}}

# Validate external JSON search options; a blank field is omitted by the browser.
def constraints(req):
    limits=req.get('min_stats',{})
    if not isinstance(limits,dict) or any(k not in STATS or type(v) is not int or not -10000<=v<=10000 or (k=='defense' and v<0) for k,v in limits.items()):
        raise ValueError('invalid minimum defense/resistance')
    mode=req.get('stat_mode','adjusted')
    if mode not in ('base','adjusted','external'):
        raise ValueError('invalid stat mode')
    return limits,mode

# Keep equipment and skill contributions separate and count only active effects.
def evaluate_stats(parts, active, external=None):
    base={k:sum(p[k] for p in parts) if all(p[k] is not None for p in parts) else None for k in STATS}
    bonus=Counter(); sources=[]
    for name in dict.fromkeys(active):
        delta=skill_modifier(name)
        if delta:
            bonus.update(delta); sources.append({'skill':name,'values':delta})
    e=normalize(external); extra=contributions(e, active); adjusted={k:None if base[k] is None else base[k]+bonus[k] for k in STATS}
    return {'base':base,'bonus':{k:bonus[k] for k in STATS},'adjusted':adjusted,'external_bonus':extra,'external':{k:None if adjusted[k] is None else adjusted[k]+extra[k] for k in STATS},'external_settings':e,'road_cost':road_cost(e),'weapon_delta':weapon_delta(e),'sources':sources,'armor_count':len(parts),'scope':'partial_ZZ_stats'}

# Independent validation after solver selection prevents false-positive candidates.
def satisfies(report, req):
    limits,mode=constraints(req)
    return all(report['defense_stats'][mode][k] is not None and report['defense_stats'][mode][k]>=v for k,v in limits.items())
