"""Generate private search data locally; game data is never uploaded by this tool."""
import argparse,copy,json,sqlite3,time
from pathlib import Path
from search_archive import SearchArchive
from activation import supplied_points
from candidate_validation import validate
from external import normalize
from armor_levels import endpoint
from skill_engine import WEAPON_SECRET,PARTS


def default_request(wt,sex='男'):
 return dict(weapon_type=wt,job='ガンナー' if wt in ('HBG','LBG','Bow') else '剣士',sex=sex,g_poogie=True,premium_poogie_clothes=True,armor={},
  auto_weapon=True,integrated_weapon=True,sigil_mode='auto',weapon={'sigils':0,'jewels':[]},weapon_filters={'max_rarity':12},
  search_mode='automatic',external=normalize(),armor_level_mode='max',min_stats={},stat_mode='adjusted',required=[],optional=[],forbidden=[],
  limit=3,seconds=6,g_armor_only=False,search_strategy='adaptive',exclude=[],exclude_classes=[],diverse_armor=True,collect_variants=True,structured_outcomes=True,live_preview=True)


def populate(archive,weapon_types,seconds=6,max_builds=128,sex='男'):
 from search_engine import Searcher
 start=time.perf_counter();results={}
 with sqlite3.connect(archive.source.resolve().as_uri()+'?mode=ro',uri=True) as db:
  solver=Searcher(db)
  for wt in weapon_types:
   req=default_request(wt,sex);base=copy.deepcopy(req);base['seconds']=seconds
   sid=solver.e.names[('normal',WEAPON_SECRET[wt])];pt=max(t['points'] for t in solver.e.levels[sid] if t['points']>0)
   base['required']=[{'skill':sid,'points':pt},{'skill':'剛撃+6'},{'skill':'一閃+3'},{'skill':'不退ノ構'}]
   found=solver.search(base)
   if not found['results']:
    base['required']=[{'skill':'剛撃+6'}];base['seconds']=seconds;found=solver.search(base)
   hits=[];seen=set()
   for h in found['results']:
    report,reasons=validate(solver,solver.prepare_request(req),h['build'])
    if report:hits.append({**h,'evaluation':report});seen.add(__import__('search_archive').build_identity(h['build']))
   anchors=list(hits)
   for part in PARTS:
    if not anchors or len(hits)>=max_builds:break
    rows=[]
    for eid,r in solver.by_kind[part].items():
     if r['job'] not in (None,'共',req['job']) or r['sex'] not in (None,'共',sex) or not solver.levels[eid]:continue
     rows.append(eid)
    # Cover every represented family, then diversify source IDs. No equipment
    # IDs are merged or removed from the exact catalogue by this finite corpus.
    by_family={}
    for eid in rows:
     for skill,value in {**solver.points[eid],**solver.zen[eid]}.items():
      if value>0 and (skill not in by_family or value>by_family[skill][0]):by_family[skill]=(value,eid)
    order=list(dict.fromkeys([eid for _,eid in by_family.values()]+rows))
    budget=max(1,(max_builds-len(hits))//max(1,len(PARTS)-PARTS.index(part)))
    added=0
    for eid in order:
     if added>=budget or len(hits)>=max_builds:break
     lv,slots,defense=endpoint(solver.levels[eid],'max')
     b=copy.deepcopy(anchors[added%len(anchors)]['build']);b['armor'][part]={'item':eid,'level':lv,'jewels':[]}
     key=__import__('search_archive').build_identity(b)
     if key in seen:continue
     report,reasons=validate(solver,solver.prepare_request(req),b)
     if report:
      seen.add(key);hits.append({'build':b,'evaluation':report});added+=1
   archive.ingest(req,hits,exportable=True)
   results[wt]={'generated_builds':len(hits),'baseline_status':found['status'],'confirmed_patterns':len({json.dumps(h['evaluation']['attained'],sort_keys=True) for h in hits})}
   print(wt,results[wt],flush=True)
 return {'elapsed_seconds':round(time.perf_counter()-start,6),'weapons':results,'archive':archive.status()}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 p.add_argument('--populate',action='store_true');p.add_argument('--weapons',nargs='+',choices=list(WEAPON_SECRET),default=list(WEAPON_SECRET));p.add_argument('--seconds',type=float,default=6);p.add_argument('--max-builds',type=int,default=128);p.add_argument('--sex',choices=['男','女'],default='男');p.add_argument('--packages',type=Path);p.add_argument('--codec',choices=['lzma2','zstd','zlib'],default='lzma2');p.add_argument('--report',type=Path)
 a=p.parse_args();start=time.perf_counter();archive=SearchArchive(a.db,a.out)
 try:
  report={'facts':archive.prepare_facts() if archive.open_facts() is None else archive.status()['statistics']}
  if a.populate:report['population']=populate(archive,a.weapons,a.seconds,a.max_builds,a.sex)
  if a.packages:
   from data_packages import export_packages
   catalog=export_packages(archive,a.packages,codec=a.codec);report['packages']={k:catalog[k] for k in ('all_weapons_download_bytes','all_weapons_expanded_bytes','rights')}
  report['total_seconds']=round(time.perf_counter()-start,6)
  if a.report:a.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(report,ensure_ascii=False,indent=2))
 finally:archive.close()

if __name__=='__main__':main()
