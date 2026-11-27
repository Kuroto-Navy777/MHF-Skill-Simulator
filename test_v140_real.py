"""Real DB coverage, source-aware witnesses, complete-model proofs and warm persistence."""
import copy,json,os,sqlite3,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from candidate_service import CandidateService
from candidate_validation import validate
from search_archive import SearchArchive
from search_precompute import MappedVectors
from search_engine import Searcher
from activation import supplied_points

ROOT=Path(__file__).parent

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Precompute140RealTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);cls.source=Path(os.environ['MHF_TEST_DB']);cls.cache=cls.root/'cache.json'
  cls.service=CandidateService(cls.source,cls.cache);cls.service.prepare_index();cls.service.index_thread.join(40)
  if cls.service.index_status()['state']!='ready':
   status=cls.service.index_status();cls.service.close();cls.temp.cleanup();raise AssertionError(status)
  cls.db=sqlite3.connect(cls.source);cls.solver=Searcher(cls.db);cls.fixtures=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
 @classmethod
 def tearDownClass(cls):cls.service.close();cls.db.close();cls.temp.cleanup()
 def fixture_request(self,name='road15'):
  f=self.fixtures[name];q=copy.deepcopy(f['build']);q['required']=f['required'];q.update(armor_level_mode='first',seconds=5,limit=1)
  return q
 def test_complete_catalogue_and_mapped_vectors_match_original_rows(self):
  a=self.service.archive;f=a.open_facts();stats=a.fact_stats
  self.assertEqual(stats['source_equipment'],self.db.execute('SELECT count(*) FROM equipment').fetchone()[0]);self.assertEqual(stats['weapon_variants'],self.db.execute('SELECT count(*) FROM ferias_variants').fetchone()[0])
  self.assertEqual(f.execute("SELECT count(*) FROM vector WHERE kind='normal'").fetchone()[0],self.db.execute('SELECT count(*) FROM equipment_skills').fetchone()[0])
  mm=MappedVectors(a.facts_path.with_suffix('.csr'))
  try:
   for eid, in f.execute('SELECT DISTINCT entity_id FROM vector WHERE points<0 LIMIT 100'):
    expected=[tuple(r) for r in f.execute('SELECT skill_id,CASE kind WHEN "normal" THEN 1 WHEN "zenith" THEN 2 ELSE 3 END,points FROM vector WHERE entity_id=? ORDER BY skill_id,kind',(eid,))]
    self.assertEqual(mm.get(eid),expected)
  finally:mm.close()
 def test_factorized_weapon_and_cuff_rules_preserve_all_legal_allocations(self):
  from ferias_import import validate_slots
  f=self.service.archive.open_facts()
  classes={r[0] for r in f.execute('SELECT DISTINCT slot_class FROM weapon WHERE supported=1')}
  for cls in classes:
   mode,n=cls.split(':');n=int(n);actual={tuple(r) for r in f.execute('SELECT decoration_used,sigils FROM weapon_pattern WHERE slot_class=?',(cls,))}
   expected={(u,s) for u in range(4) for s in range(4) if validate_slots(mode,n,u,s)['valid']};self.assertEqual(actual,expected)
  pairs={tuple(r) for r in f.execute('SELECT class_a,class_b FROM cuff_pair')};self.assertIn(('',''),pairs)
  groups={r[0] for r in f.execute('SELECT DISTINCT class_id FROM cuff_member')}
  for a in sorted(groups):
   self.assertIn(('',a),pairs)
   for b in sorted(groups):
    aa,bb=json.loads(a),json.loads(b);legal=aa[0]+bb[0]<=2 and aa[1]+bb[1]<=1
    self.assertEqual(tuple(sorted((a,b))) in pairs,legal)
 def test_authenticated_compiled_vectors_equal_source_and_reject_tampering(self):
  from search_precompute import load_solver_vectors
  env=self.service.archive.worker_environment()
  with patch.dict(os.environ,env):
   compiled=load_solver_vectors(self.db,self.solver.items,self.solver.e.skills)
  self.assertIsNotNone(compiled)
  for actual,expected in zip(compiled,(self.solver.points,self.solver.zen,self.solver.auto)):
   self.assertEqual({k:v for k,v in actual.items() if v},{k:v for k,v in expected.items() if v})
  with patch.dict(os.environ,{**env,'MHF_PRECOMPUTED_SHA':'0'*64}):
   self.assertIsNone(load_solver_vectors(self.db,self.solver.items,self.solver.e.skills))
 def test_full_model_infeasibility_is_persisted_only_with_complete_scope(self):
  q=self.fixture_request();q['required']=q['required']+[{'skill':'耳栓強化+1'}]
  for a in q['armor'].values():a['jewels']=[]
  r=self.solver.feasibility(q);self.assertEqual(r['status'],'proven_infeasible');self.assertEqual(r['pool_mode'],'full')
  cert=self.service.accept_proof(q,r['certificate']);self.assertTrue(cert['coverage_complete'],cert)
  base={**q,'required':self.fixtures['road15']['required']};sid,pt=self.solver.requirement({'skill':'耳栓強化+1'})
  queried=self.service.query(base,[{'skill':sid,'points':pt}]);self.assertEqual(queried['candidate_states'][f'{sid}|{pt}']['state'],'proven_infeasible')
 def test_automatic_scope_with_unhandled_source_data_remains_undetermined(self):
  from precompute_tool import default_request
  req=default_request('MS');coverage=self.service.archive.coverage(self.service.searcher.prepare_request(req));self.assertFalse(coverage['complete']);self.assertTrue(coverage['examples'])
  sid,pt=self.solver.requirement({'skill':'剛撃+6'});cert={'kind':'full_model_infeasible','scope':'supported_search_model','source':self.service.identity,'calculation':self.service.archive.calculation}
  checked=self.service.accept_proof({**req,'required':[{'skill':sid,'points':pt}]},cert);self.assertFalse(checked['coverage_complete'])
  result=self.service.query(req,[{'skill':sid,'points':pt}]);self.assertNotEqual(result['candidate_states'][f'{sid}|{pt}']['state'],'proven_infeasible')
 def test_source_only_jewel_impossibility_and_wrong_weapon_secret_are_sound(self):
  from precompute_tool import default_request
  req=default_request('MS');ear,pt=self.solver.requirement({'skill':'耳栓強化+1'});req['zenith_sources']={ear:['jewel']}
  other,other_pt=self.solver.requirement({'skill':'片手剣技【剣聖】'})
  result=self.service.query(req,[{'skill':ear,'points':pt},{'skill':other,'points':other_pt}])
  self.assertEqual(result['candidate_states'][f'{ear}|{pt}']['state'],'proven_infeasible')
  self.assertEqual(result['candidate_states'][f'{other}|{other_pt}']['state'],'proven_infeasible')
 def test_time_limit_never_becomes_infeasibility(self):
  from precompute_tool import default_request
  req=default_request('MS');req.update(required=self.fixtures['road16']['required'],seconds=.05)
  result=self.solver.feasibility(req);self.assertEqual(result['status'],'unknown');self.assertNotIn('certificate',result)
 def test_weapon_source_constraint_matches_independent_validation_and_index(self):
  req=self.fixture_request();req.pop('weapon',None);req.update(auto_weapon=True,integrated_weapon=True,sigil_mode='auto',weapon={'sigils':0})
  for a in req['armor'].values():a['jewels']=[]
  sid,pt=self.solver.requirement({'skill':'耳栓強化+1'});req['required']=req['required']+[{'skill':sid,'points':pt}];req['zenith_sources']={sid:['weapon']}
  result=self.solver.feasibility(req);self.assertTrue(result['results'],result['status'])
  for h in result['results']:
   self.assertGreaterEqual(supplied_points(h['evaluation'],sid,['weapon']),pt);report,reasons=validate(self.solver,self.solver.prepare_request(req),h['build']);self.assertIsNotNone(report,reasons)
  self.service.ingest(req,result);cached=self.service.query(req);self.assertTrue(cached['results'])
 def test_restart_uses_authenticated_reports_without_recalculation(self):
  req=self.fixture_request('road16');b=self.fixtures['road16']['build'];report=self.service.evaluate(b);self.service.ingest(req,{'results':[{'build':b,'evaluation':report}]})
  self.service.close();self.service=CandidateService(self.source,self.cache);type(self).service=self.service
  with patch('skill_engine.Engine.evaluate',side_effect=AssertionError('cached query must not recalculate')):
   r=self.service.query(req);self.assertTrue(r['results']);self.assertEqual(r['results'][0]['evaluation'],report)
 def test_pack_round_trip_revalidates_real_builds_without_losing_source_ids(self):
  from data_packages import export_packages,download_selected,import_weapon_builds
  req=self.fixture_request('road16');req.pop('inventory',None);b=self.fixtures['road16']['build'];r=self.service.evaluate(b);self.service.archive.ingest(req,[{'build':b,'evaluation':r}],exportable=True)
  out=self.root/'packs';catalog=export_packages(self.service.archive,out,codec='zlib')
  self.assertEqual(catalog['rights']['status'],'unverified');self.assertLess(catalog['all_weapons_download_bytes'],1024**3)
  def fetch(v,name,target,limit,expected):target.write_bytes((out/name).read_bytes())
  result=download_selected(catalog,'MS',self.root/'packcache',self.root/'packinstall',fetch,require_rights=False,include_common=False)
  other=SearchArchive(self.source,self.root/'import.sqlite')
  try:
   checked=import_weapon_builds(other,result['files']['MS/builds.json'],self.service.searcher);self.assertGreater(checked['accepted'],0);self.assertEqual(checked['rejected'],0)
   q=other.query(req,self.service.searcher.requirements(req['required']));self.assertTrue(q['results']);self.assertEqual(q['results'][0]['build'],b)
  finally:other.close()

if __name__=='__main__':unittest.main()
