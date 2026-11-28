"""Real DB partial-set evaluation and verified completion latency."""
import argparse,copy,json,sqlite3,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from search_engine import Searcher
from partial_build import current
from candidate_service import CandidateService
from ci.profile_precompute_queries import timings
from ci.profile_precompute_formats import memory

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 f=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))['road16'];q=copy.deepcopy(f['build']);q.pop('cuffs');q['armor']={'head':q['armor']['head']};q['armor']['head']['jewels']=q['armor']['head']['jewels'][:1]
 q.update(required=f['required'][:4],pinned_jewels={'leg':[f['build']['armor']['leg']['jewels'][0]]},fixed_cuffs=['cuff:1:1185'],search_mode='partial',g_armor_only=False,armor_level_mode='first',search_strategy='adaptive',seconds=8,limit=5,structured_outcomes=True,diverse_armor=True)
 with sqlite3.connect(a.db) as db:
  solver=Searcher(db);start=time.perf_counter();found=solver.search(q);elapsed=time.perf_counter()-start;assert found['results'],found['status']
  with tempfile.TemporaryDirectory() as folder:
   service=CandidateService(a.db,Path(folder)/'cache.json')
   try:
    service.ingest(q,found);reader=service._ready();current(reader,q);service.query(q,limit=5)
    result={'completion_wall_seconds':elapsed,'completion_status':found['status'],'confirmed_builds':len(found['results']),'distinct_armor':found['distinct_armor'],'rejected':found['rejected'],'solver_timings':found['timings'],'warm_current_evaluation':timings(lambda:current(reader,q)),'warm_cached_partial_query':timings(lambda:service.query(q,limit=5)),'scope':'one fixed armor, one fixed armor jewel, one detached pinned jewel, one zero-slot secret cuff; remaining armor/jewels/cuffs automatic',**memory()}
   finally:service.close()
 a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
