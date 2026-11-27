"""Measure a selected engine checkout using the user's local integrated DB."""
import argparse
import copy
import ctypes
import gc
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--engine-dir',type=Path,default=ROOT)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--export-candidates',type=Path)
a=p.parse_args();sys.path.insert(0,str(a.engine_dir.resolve()))
import_start=time.perf_counter()
from search_engine import Searcher,Model
import_seconds=time.perf_counter()-import_start


def memory():
    if os.name!='nt':return {}
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                    ('peak','working','page_peak','page','nonpage_peak','nonpage','pagefile','pagefile_peak','private')]
    value=Counters();value.cb=ctypes.sizeof(value)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    api=ctypes.WinDLL('psapi');api.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
    if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb):raise ctypes.WinError()
    return {'working_set_mib':round(value.working/1024**2,3),'peak_working_set_mib':round(value.peak/1024**2,3)}


fixtures=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
with sqlite3.connect(a.db) as db:
    start=time.perf_counter();s=Searcher(db);cold=time.perf_counter()-start
    start=time.perf_counter();warm=Searcher(db);warm_seconds=time.perf_counter()-start
    del warm;gc.collect()
    report={'engine_version':(a.engine_dir/'VERSION').read_text().strip(),
            'module_import_seconds':round(import_seconds,6),'cold_init_seconds':round(cold,6),
            'warm_init_seconds':round(warm_seconds,6),'initial_memory':memory(),'cases':{}}
    basic=dict(weapon_type='MS',sex='男',g_poogie=True,premium_poogie_clothes=True,
               required=[{'skill':n} for n in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+3']],
               seconds=20,limit=5,search_strategy='adaptive',armor_level_mode='first')
    high=copy.deepcopy(fixtures['road15']['build']);high.pop('cuffs')
    for cfg in high['armor'].values():cfg['jewels']=[]
    high.update(required=fixtures['road15']['required'],seconds=20,limit=5,search_strategy='adaptive',armor_level_mode='first')
    ears={**high,'required':high['required']+[{'skill':'耳栓強化+1'}]}
    cases={'four_skills_standard':{**basic,'diverse_armor':hasattr(s,'prepare_request')},
           'four_skills_diverse':{**basic,'diverse_armor':True},'road15_fixed':high,'road15_earplug':ears}
    original_solve=Model.solve
    for name,q in cases.items():
        times=[];first=[]
        def solve(model,seconds):
            tick=time.perf_counter();times.append([tick,0]);r=original_solve(model,seconds);times[-1][1]=time.perf_counter()-tick;return r
        Model.solve=solve
        s.progress=lambda result:first.append(time.perf_counter()) if result['results'] and not first else None
        cpu=time.process_time();start=time.perf_counter();r=s.search(copy.deepcopy(q));elapsed=time.perf_counter()-start
        armors=[h['build']['armor'] for h in r['results']]
        distances=[min(sum(cur[p]['item']!=other[p]['item'] for p in cur) for other in armors[:i]) for i,cur in enumerate(armors) if i]
        report['cases'][name]={'wall_seconds':round(elapsed,6),'model_build_seconds':round(times[0][0]-start,6) if times else None,
                              'solver_seconds':round(sum(t[1] for t in times),6),
                              'first_candidate_seconds':round(first[0]-start,6) if first else None,
                              'cpu_seconds':round(time.process_time()-cpu,6),'results':len(r['results']),
                              'distinct_armor':len({tuple((p,cfg['item']) for p,cfg in sorted(h.items())) for h in armors}),
                              'prior_armor_distances':distances,'rejected':r['rejected'],'status':r['status'],**memory()}
    Model.solve=original_solve
    if hasattr(s,'prepare_request'):
        from candidate_service import CandidateService
        from candidate_validation import validate
        broad={**basic,'required':[],'cuffs':fixtures['road15']['build']['cuffs'],'armor':{},'live_preview':True}
        prepared=s.prepare_request(broad);hits=[]
        for eid,row in s.by_kind['head'].items():
            if not any(lv[0]=='L1' and lv[1]==3 for lv in s.levels[eid]):continue
            build=copy.deepcopy(fixtures['road15']['build']);build['armor']['head']['item']=eid
            evaluation,reasons=validate(s,prepared,build)
            if evaluation:hits.append({'build':build,'evaluation':evaluation,'new_jewels':15})
            if len(hits)==256:break
        service=CandidateService(a.db);service.ingest(broad,{'results':hits},persist=False)
        targets=[{'skill':sid,'points':t['points']} for sid,tiers in s.e.levels.items() for t in tiers if s.selectable(t)]
        latencies=[]
        for _ in range(20):
            tick=time.perf_counter();query=service.query(broad,targets);latencies.append(time.perf_counter()-tick)
        latencies.sort()
        report['reservoir']={'builds':query['reservoir_counts']['confirmed_builds'],
                             'index_filter_seconds':query['filter_seconds'],
                             'query_median_seconds':latencies[len(latencies)//2],
                             'query_p95_seconds':latencies[int(len(latencies)*.95)-1],
                             'bounded_payload_mib':round(query['memory_bytes']/1024**2,3),**memory()}
        if a.export_candidates:a.export_candidates.write_text(json.dumps(hits,ensure_ascii=False),encoding='utf-8')
        service.close()
a.out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
