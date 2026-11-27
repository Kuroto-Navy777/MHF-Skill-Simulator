"""Compare the previous source on exactly the same confirmed 128-build corpus."""
import argparse,json,sqlite3,sys,tempfile,time,zlib,statistics
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--db',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();sys.path.insert(0,str(a.source.resolve()))
 from candidate_service import CandidateService
 with sqlite3.connect(a.archive) as conn:
  scope,request=conn.execute("SELECT id,request FROM scope WHERE exportable=1 AND json_extract(request,'$.weapon_type')='MS' LIMIT 1").fetchone()
  hits=[json.loads(zlib.decompress(r[0])) for r in conn.execute('SELECT w.payload FROM witness w JOIN membership m ON m.witness_id=w.id WHERE m.scope_id=?',(scope,))]
 req=json.loads(request);req['required']=[]
 def measure(fn):
  values=[]
  for _ in range(30):
   start=time.perf_counter();fn();values.append((time.perf_counter()-start)*1000)
  return {'median_ms':statistics.median(values),'p95_ms':sorted(values)[27]}
 with tempfile.TemporaryDirectory() as folder:
  start=time.perf_counter();s=CandidateService(a.db,Path(folder)/'cache.json');s._ready();init=time.perf_counter()-start
  s.ingest(req,{'results':hits});targets=[{'skill':r['id'],'points':t['points']} for r in s.searcher.e.skills.values() for t in s.searcher.e.levels[r['id']] if t['points']>0]
  first=s.query(req,targets,limit=5);skill=next(t for t in targets if first['candidate_counts'].get(f"{t['skill']}|{t['points']}",0)>0)
  result={'version':'1.3.0','same_MS_corpus':len(hits),'initialization_seconds':init,'warm_skill_list':measure(lambda:s.query(req,targets,limit=5)),'warm_skill_add':measure(lambda:s.query({**req,'required':[skill]},limit=5)),'warm_skill_delete':measure(lambda:s.query(req,limit=5)),'warm_candidates':measure(lambda:s.query(req,limit=5))}
  s.close();s=CandidateService(a.db,Path(folder)/'cache.json');start=time.perf_counter();r=s.query(req,targets,limit=5);result['restart_first_query_ms']=(time.perf_counter()-start)*1000;result['restored_confirmed_builds']=r['confirmed_builds'];s.close()
 a.out.write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))

if __name__=='__main__':main()
