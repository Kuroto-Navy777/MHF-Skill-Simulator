"""Reproducible real-DB warm edits, restart, certainty and representation sizes."""
import argparse,collections,contextlib,json,os,sqlite3,statistics,sys,time,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ci.profile_precompute_formats import memory
from candidate_service import CandidateService

def timings(fn,n=30):
 times=[];cpu=time.process_time()
 for _ in range(n):
  start=time.perf_counter();fn();times.append((time.perf_counter()-start)*1000)
 return {'median_ms':statistics.median(times),'p95_ms':sorted(times)[int(.95*(len(times)-1))],'cpu_seconds':time.process_time()-cpu,'repetitions':n}

def main():
 p=argparse.ArgumentParser();p.add_argument('--db',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 # CandidateService maps cache.json -> cache.search.sqlite.
 cache=a.archive.with_name(a.archive.name.removesuffix('.search.sqlite')+'.json')
 start=time.perf_counter();s=CandidateService(a.db,cache);s._ready();init=time.perf_counter()-start
 try:
  archive=s.archive;req=json.loads(archive.db.execute("SELECT request FROM scope WHERE exportable=1 AND json_extract(request,'$.weapon_type')='MS' LIMIT 1").fetchone()[0]);req['required']=[]
  skills=[{'skill':r['id'],'points':t['points']} for r in s.searcher.e.skills.values() for t in s.searcher.e.levels[r['id']] if t['points']>0]
  start=time.perf_counter();first=s.query(req,skills,limit=5);cold=time.perf_counter()-start
  skill=next(t for t in skills if first['candidate_counts'].get(f"{t['skill']}|{t['points']}",0)>0)
  add={**req,'required':[skill]}
  metrics={'initialization_seconds':init,'first_query_seconds':cold,'saved_builds':first['precomputed']['witnesses'],'saved_patterns':first['precomputed']['patterns'],'MS_confirmed_builds':first['confirmed_builds'],'MS_distinct_armor':first['distinct_armor']}
  metrics['warm_skill_list']=timings(lambda:s.query(req,skills,limit=5))
  metrics['warm_skill_add']=timings(lambda:s.query(add,limit=5))
  metrics['warm_skill_delete']=timings(lambda:s.query(req,limit=5))
  metrics['warm_candidates']=timings(lambda:s.query(req,limit=5))
  states=collections.Counter(v['state'] for v in first['candidate_states'].values());metrics['certainty']={'states':dict(states),'targets':len(skills),'resolved_fraction':sum(states[k] for k in ('confirmed','proven_infeasible'))/max(1,len(skills)),'scope':'MS automatic baseline; finite generated corpus, not total equipment combinations'}
  metrics['solver_launches_during_queries']=0
  facts=archive.open_facts();rows=[list(r) for r in facts.execute('SELECT entity_id,skill_id,kind,points FROM vector')];text=json.dumps(rows,separators=(',',':')).encode();packed=archive.facts_path.with_suffix('.csr').read_bytes()
  dictionary=b'entity_id skill_id normal zenith automatic points weapon armor cuff jewel '+text[:32768]
  co=zlib.compressobj(9,zdict=dictionary[-32768:]);encoded=co.compress(text)+co.flush();dc=zlib.decompressobj(zdict=dictionary[-32768:]);assert dc.decompress(encoded)+dc.flush()==text
  metrics['integer_dictionary']={'plain_json_bytes':len(text),'packed_CSR_bytes':len(packed),'zlib_JSON_bytes':len(zlib.compress(text,9)),'zlib_dictionary_JSON_bytes':len(encoded),'dictionary_bytes':min(32768,len(dictionary)),'note':'Dictionary overhead must be included; vectors are exact signed integer IDs.'}
  metrics.update(memory());s.close();s=CandidateService(a.db,cache)
  start=time.perf_counter();restored=s.query(req,skills,limit=5);metrics['restart_first_query_ms']=(time.perf_counter()-start)*1000;assert restored['confirmed_builds']==first['confirmed_builds']
  a.out.write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(metrics,ensure_ascii=False,indent=2))
 finally:s.close()

if __name__=='__main__':main()
