"""Armor groups are presentation units; each decoration/cuff witness remains intact."""
import json
from skill_engine import PARTS


def armor_key(build):
    return tuple((p,build.get('armor',{}).get(p,{}).get('item')) for p in PARTS)


def distance(a,b):
    return sum(a.get('armor',{}).get(p,{}).get('item')!=b.get('armor',{}).get(p,{}).get('item') for p in PARTS)


def group_hits(hits):
    groups={}
    for hit in hits:
        key=armor_key(hit['build'])
        if key not in groups:
            groups[key]={**hit,'armor_group_key':json.dumps(key,separators=(',',':')),'variants':[],'variant_count':1}
        else:
            group=groups[key];group['variant_count']+=1
            if len(group['variants'])<8: group['variants'].append(hit)
    result=list(groups.values())
    for i,h in enumerate(result):
        h['armor_distance']=min((distance(h['build'],g['build']) for g in result[:i]),default=5)
    return result


def counts(hits):
    n=len(hits);groups=len({armor_key(h['build']) for h in hits})
    return {'confirmed_builds':n,'distinct_armor':groups,'decoration_variants':n-groups}
