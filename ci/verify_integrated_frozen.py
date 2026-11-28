"""Verify new joint search in the actual portable EXE before signing/publishing."""
import argparse,copy,json,subprocess,tempfile,types,zipfile,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from update_core import inspect_archive
from candidate_reader import CandidateReader
from candidate_validation import validate

def normalized(c):
 if isinstance(c,types.CodeType):
  return (c.co_code,tuple(normalized(x) for x in c.co_consts),c.co_names,c.co_varnames,c.co_freevars,c.co_cellvars,c.co_argcount,c.co_kwonlyargcount,c.co_flags)
 return c

def verify(archive,db,report_path):
 from PyInstaller.archive.readers import CArchiveReader
 result={'ok':False,'cases':{}}
 with tempfile.TemporaryDirectory(prefix='mhf-frozen-130-') as folder:
  folder=Path(folder)
  with zipfile.ZipFile(archive) as z:
   inspect_archive(z,True)
   assert z.read('MHF_SkillSimulator/app/web/app.js')==(ROOT/'web/app.js').read_bytes()
   assert not any(n.lower().endswith(('.db','.sqlite','.sqlite3','.pem','.key')) for n in z.namelist())
   z.extractall(folder)
  exe=folder/'MHF_SkillSimulator/app/MHFDesktop.exe';c=CArchiveReader(str(exe))
  pyz=c.open_embedded_archive(next(n for n in c.toc if n.endswith('.pyz')))
  modules=['search_engine','search_contract','skill_engine','weapon_effects','candidate_validation','candidate_reader','candidate_pool','candidate_service','web_api']
  if (ROOT/'VERSION').read_text().strip()>='1.4.0':
   modules+=['partial_build','inventory','calculation_identity','search_archive','search_precompute','data_packages','precompute_distribution','precompute_idle']
  for name in modules:
   assert normalized(pyz.extract(name))==normalized(compile((ROOT/(name+'.py')).read_text(encoding='utf-8'),name+'.py','exec',optimize=0)),name
  result['compiled_modules_match']=modules
  fixtures=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
  with sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True) as conn:
   reader=CandidateReader(conn)
   for name,key,mode,limit,seconds in [('fixed16','road16','fixed',1,12),('fully_automatic15','road15','automatic',3,20),('partial_locks','road16','partial',1,15)]:
    f=fixtures[key];q=copy.deepcopy(f['build']);q.pop('cuffs',None)
    for a in q['armor'].values():a['jewels']=[]
    q.update(search_mode=mode,auto_weapon=True,integrated_weapon=True,sigil_mode='auto',weapon={'sigils':0,'jewels':[]},required=f['required'],seconds=seconds,limit=limit,diverse_armor=True,armor_level_mode='first',search_strategy='adaptive',structured_outcomes=True)
    if mode=='partial':
     q['armor']={'head':copy.deepcopy(f['build']['armor']['head'])};q['armor']['head']['jewels']=q['armor']['head']['jewels'][:1]
     q['pinned_jewels']={'leg':[f['build']['armor']['leg']['jewels'][0]]};q['fixed_cuffs']=['cuff:1:1185'];q['required']=f['required'][:4]
    request=folder/(name+'.request.json');out=folder/(name+'.out.json');log=folder/(name+'.log')
    request.write_text(json.dumps(q,ensure_ascii=False),encoding='utf-8')
    proc=subprocess.run([str(exe),'--search-worker','--db',str(db.resolve()),'--request',str(request),'--out',str(out),'--worker-log',str(log)],timeout=90)
    if proc.returncode or not out.is_file():raise RuntimeError(name+' frozen worker failed')
    r=json.loads(out.read_text(encoding='utf-8'));assert len(r['results'])==limit,(name,r['status'],len(r['results']))
    prepared=reader.prepare_request(q)
    for h in r['results']:
     actual,why=validate(reader,prepared,h['build']);assert actual is not None,why;assert actual==h['evaluation']
     assert h['build']['weapon'].get('page')
    result['cases'][name]={k:r[k] for k in ['status','elapsed_seconds','distinct_armor','rejected','integrated_weapon']}
  if (ROOT/'VERSION').read_text().strip()>='1.4.0':
   report=folder/'precompute-smoke.json'
   subprocess.run([str(exe),'--self-test','--db',str(db.resolve()),'--precompute-check','--report',str(report)],check=True,timeout=150)
   smoke=json.loads(report.read_text(encoding='utf-8'));assert smoke['ok'],smoke
   result['precompute']=smoke['checks']['precompute_restart']
 result['ok']=True;report_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',required=True,type=Path);p.add_argument('--db',required=True,type=Path);p.add_argument('--report',required=True,type=Path);a=p.parse_args();verify(a.archive,a.db,a.report)
