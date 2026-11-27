"""Compare legacy outer weapon search with the joint model on a private real DB."""
import argparse,copy,json,sqlite3,sys,time,ctypes,os
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--engine-dir',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.engine_dir.resolve()));start=time.perf_counter()
from search_engine import Searcher
from skill_engine import PARTS
import_seconds=time.perf_counter()-start
root=Path(__file__).resolve().parents[1];fixtures=json.loads((root/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
def memory():
 if os.name!='nt':return {}
 from ctypes import wintypes
 class C(ctypes.Structure):
  _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['peak','working','page_peak','page','nonpage_peak','nonpage','pagefile','pagefile_peak','private']]
 v=C();v.cb=ctypes.sizeof(v);k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=wintypes.HANDLE
 api=ctypes.WinDLL('psapi');api.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD];api.GetProcessMemoryInfo(k.GetCurrentProcess(),ctypes.byref(v),v.cb)
 return {'working_set_mib':round(v.working/1024**2,3),'peak_working_set_mib':round(v.peak/1024**2,3)}
with sqlite3.connect(a.db) as db:
 start=time.perf_counter();s=Searcher(db);init=time.perf_counter()-start
 base=dict(weapon_type='MS',sex='男',g_poogie=True,premium_poogie_clothes=True,armor={},auto_weapon=True,integrated_weapon=True,search_mode='automatic',sigil_mode='auto',weapon={'sigils':0},g_armor_only=False,armor_level_mode='first',seconds=20,limit=3,diverse_armor=True,search_strategy='adaptive')
 basic=[{'skill':n} for n in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+3']]
 cases={'four_skills':basic,'with_earplug':basic+[{'skill':'耳栓強化+1'}],'free_road15':fixtures['road15']['required'],'free_road16':fixtures['road16']['required']}
 output={'version':(a.engine_dir/'VERSION').read_text().strip(),'import_seconds':round(import_seconds,6),'init_seconds':round(init,6),'cases':{}}
 original=s.search_fixed;models=[]
 def measured(*args,**kw):
  r=original(*args,**kw);models.append(r.get('timings',{}));return r
 s.search_fixed=measured
 for name,required in cases.items():
  models.clear();q={**copy.deepcopy(base),'required':required};start=time.perf_counter();cpu=time.process_time();r=s.search(q);wall=time.perf_counter()-start
  for h in r['results']:
   report=s.e.evaluate(h['build']);assert report==h['evaluation'] and report['valid']
   assert all(s.achieved(report,sid,pt) for sid,pt in s.requirements(required).items())
  output['cases'][name]={'wall_seconds':round(wall,6),'cpu_seconds':round(time.process_time()-cpu,6),'status':r['status'],'results':len(r['results']),'distinct_armor':r['distinct_armor'],'rejected':r['rejected'],'model_build_seconds':round(sum(t.get('model_build_seconds',0) for t in models),6),'first_candidate_seconds':next((t.get('first_candidate_seconds') for t in models if t.get('first_candidate_seconds') is not None),None),'weapon_groups':r.get('weapon_groups',r.get('pool_counts',{}).get('weapon_groups')),'weapon_groups_searched':r.get('weapon_groups_searched'),'weapon_rows_skipped':r.get('weapon_rows_skipped'),'integrated_weapon':r.get('integrated_weapon',False),**memory()}
  print(name,output['cases'][name],flush=True)
  if output['version']=='1.3.0':(root/'.local'/('v130-'+name+'-result.json')).write_text(json.dumps({'request':q,'response':r},ensure_ascii=False),encoding='utf-8')
 a.out.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
