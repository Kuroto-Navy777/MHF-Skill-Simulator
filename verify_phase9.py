"""Replay known valid builds and benchmark bounded searches using local master data."""
import copy
import json
import sqlite3
import time
from pathlib import Path
from search_engine import Searcher

# Use the same independent evaluator for baseline and each returned result.
with sqlite3.connect('mhf_master.sqlite') as db:
    t=time.monotonic();s=Searcher(db)
    print('Searcher init',round(time.monotonic()-t,3),flush=True)
    b=json.loads(Path('example_build.json').read_text())
    r=s.e.evaluate(b)
    active=[{'skill':x['id'],'points':x['threshold']} for x in r['skills'] if x['status']=='active' and s.selectable({'ja':x['level_ja'],'points':x['threshold']})]
    zen=[{'skill':x['id'],'points':x['level']} for x in r['zenith'] if x['level'] and x['has_base_skill'] is not False]
    print('baseline',json.dumps({'valid':r['valid'],'normal':[(x['level_ja'],x['points']) for x in r['skills'] if x['status']=='active'],'zenith':[(x['ja'],x['level']) for x in r['zenith'] if x['has_base_skill'] is not False],'slots':r['slots']['capacity'],'warnings':r['configuration_warnings']},ensure_ascii=False),flush=True)
    assert r['valid']
    q=copy.deepcopy(b);q.update(required=active+zen,limit=1,seconds=10,search_strategy='full')
    # Retain a known witness to separate evaluator issues from optimization performance.
    scenarios=[('known_witness',q)]
    fixed=copy.deepcopy(q)
    for a in fixed['armor'].values(): a['jewels']=[]
    fixed['weapon']['jewels']=[]
    scenarios.append(('fixed_armor_full',fixed))
    free=copy.deepcopy(fixed);free.pop('armor');free.pop('cuffs');free.update(seconds=20,search_strategy='adaptive')
    scenarios.append(('free_armor_adaptive',free))
    wide=copy.deepcopy(free);wide.update(seconds=20,search_strategy='full')
    scenarios.append(('free_armor_full',wide))
    basic=json.loads(Path('example_auto_search.json').read_text());basic.update(seconds=10,limit=1,search_strategy='adaptive',armor_level_mode='first')
    scenarios.append(('seven_conditions',basic))
    empty=copy.deepcopy(fixed);empty.update(jewel_candidates=[],seconds=5)
    scenarios.append(('no_jewels',empty))
    for name,req in scenarios:
        t=time.monotonic()
        try:
            out=s.search(req)
            for hit in out['results']:
                replay=s.e.evaluate(hit['build']);assert replay['valid']
                assert replay==hit['evaluation']
                assert all(s.achieved(replay,sid,pt) for sid,pt in s.requirements(req['required']).items())
            print(name,json.dumps({k:out.get(k) for k in ('status','elapsed_seconds','attempts','rejected','model_variables','pool_mode','search_passes')},ensure_ascii=False),'hits',len(out['results']),'wall',round(time.monotonic()-t,3),flush=True)
        except Exception as ex:
            print(name,'ERROR',repr(ex),flush=True)
            raise
