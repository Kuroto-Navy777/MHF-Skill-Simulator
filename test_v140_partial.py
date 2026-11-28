"""Partial locks are hard constraints in solving, reuse and current-point display."""
import copy,json,os,sqlite3,tempfile,unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from candidate_validation import validate
from candidate_service import CandidateService
from partial_build import current,fixed_jewels,placements
from search_engine import Searcher
from web_api import create_app
ROOT=Path(__file__).parent

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Partial140Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db);cls.f=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def request(self):
  q=copy.deepcopy(self.f['road16']['build']);q.update(required=self.f['road16']['required'][:4],search_mode='partial',armor_level_mode='first',seconds=8,limit=1,structured_outcomes=True,search_strategy='adaptive',g_armor_only=False)
  q.pop('cuffs');q['fixed_cuffs']=['cuff:1:1185'];q['armor']={'head':q['armor']['head']};q['armor']['head']['jewels']=q['armor']['head']['jewels'][:1];q['pinned_jewels']={'leg':[self.f['road16']['build']['armor']['leg']['jewels'][0]]}
  return q
 def test_unselected_armor_and_pinned_jewels_are_jointly_completed(self):
  q=self.request();result=self.s.search(q);self.assertTrue(result['results'],result)
  for h in result['results']:
   b=h['build'];report,why=validate(self.s,self.s.prepare_request(q),b);self.assertIsNotNone(report,why)
   self.assertEqual(b['armor']['head']['item'],q['armor']['head']['item']);self.assertEqual(set(b['armor']),set(self.f['road16']['build']['armor']))
   self.assertLessEqual(Counter(q['pinned_jewels']['leg']),Counter(b['armor']['leg']['jewels']));self.assertIn('cuff:1:1185',b['cuffs'])
   tags=placements(self.s,q,b);self.assertTrue(tags['decorations']['leg'][0]['fixed']);self.assertTrue(next(c for c in tags['cuffs'] if c['item']=='cuff:1:1185')['fixed'])
 def test_partial_cuff_can_fill_remaining_slot_and_use_identical_cuff_twice(self):
  q=copy.deepcopy(self.f['road16']['build']);q.pop('cuffs');q.update(required=[],live_preview=True,limit=1,seconds=5,search_strategy='full',armor_level_mode='first')
  base=self.s.e.evaluate({**q,'cuffs':[]});existing={s['id']:s['points'] for s in base['skills']}
  # Find a real one-slot cuff supplying 5P to a 10P tier, with no other
  # contribution in this exact set. Two identical cuffs must be selected.
  cuff,sid=next((eid,sid) for eid,row in self.s.by_kind['cuff'].items() if row['slots']==1 and row['class_code'] not in ('(未)','(不)') for sid,amount in self.s.points[eid].items() if amount==5 and existing.get(sid,0)==0 and any(t['points']==10 for t in self.s.e.levels[sid]))
  q.update(fixed_cuffs=[cuff],cuff_candidates=[cuff],jewel_candidates=[],required=[{'skill':sid,'points':10}])
  r=self.s.search(q);self.assertTrue(r['results'],r);self.assertEqual(r['results'][0]['build']['cuffs'].count(cuff),2)
 def test_current_points_slots_and_multislot_decoration(self):
  for slots in range(4):
   q=self.request();q['armor']={};q['fixed_cuffs']=['cuff:0:48'];q['weapon']={'virtual':True,'slots':slots,'slot_mode':'decoration','sigils':0,'jewels':['jewel:0:28'] if slots>=2 else []};q['pinned_jewels']={}
   r=current(self.s,q);self.assertTrue(r['evaluation']['valid']);self.assertEqual(r['cuff_free'],1);self.assertEqual(r['unselected_armor'],list(self.f['road16']['build']['armor']))
   w=next(x for x in r['equipment_slots'] if x['part']=='weapon');self.assertEqual(w['used'],2 if slots>=2 else 0);self.assertEqual(w['free'],slots-w['used'])
   if slots>=2:self.assertEqual(r['placement']['decorations']['weapon'][0]['slots'],2)
  q['weapon'].update(slot_mode='shared',slots=3,sigils=2,jewels=['jewel:0:28']);self.assertFalse(current(self.s,q)['evaluation']['valid'])
 def test_fixed_locks_are_revalidated_on_reuse_and_restored_without_solver(self):
  q=copy.deepcopy(self.f['road16']['build']);q.update(required=self.f['road16']['required'],pinned_jewels={},fixed_cuffs=q['cuffs'][:1],armor_level_mode='first')
  b=self.f['road16']['build']
  with tempfile.TemporaryDirectory() as folder:
   cache=Path(folder)/'cache.json';service=CandidateService(os.environ['MHF_TEST_DB'],cache)
   try:
    service.ingest(q,{'results':[{'build':b,'evaluation':self.s.e.evaluate(b)}]});self.assertTrue(service.query(q)['results'])
    changed=copy.deepcopy(q);changed['fixed_cuffs']=['cuff:0:48'];changed.pop('cuffs');self.assertFalse(service.query(changed)['results'])
    altered=copy.deepcopy(b);altered['cuffs']=[];self.assertIsNone(validate(self.s,self.s.prepare_request(q),altered)[0])
   finally:service.close()
 def test_partial_api_returns_current_not_cached_or_completed_points(self):
  q=self.request()
  with tempfile.TemporaryDirectory() as folder,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(folder)/'cache.json')) as c:
   r=c.post('/api/partial/evaluate',json=q);self.assertEqual(r.status_code,200,r.text);data=r.json();self.assertEqual(len(data['build']['armor']),1);self.assertEqual(len(data['unselected_armor']),4);self.assertIn('leg',data['pending_decorations'])
   self.assertEqual(data['evaluation'],c.post('/api/evaluate',json=data['build']).json()['evaluation'])
 def test_virtual_weapon_pins_and_reserved_sigils_are_preserved(self):
  for slots in range(4):
   q=self.request();q['armor']=copy.deepcopy(self.f['road16']['build']['armor']);q['pinned_jewels']={'weapon':['jewel:0:28']} if slots>=2 else {}
   q['weapon']={'virtual':True,'slots':slots,'slot_mode':'shared','sigils':1 if slots==3 else 0,'jewels':[]};q.update(required=[],live_preview=True,jewel_candidates=[],cuff_candidates=[],fixed_cuffs=[],search_strategy='full')
   r=self.s.search(q);self.assertTrue(r['results'],r);b=r['results'][0]['build'];self.assertEqual(b['weapon']['sigils'],1 if slots==3 else 0)
   self.assertEqual(b['weapon']['jewels'],['jewel:0:28'] if slots>=2 else []);self.assertIsNotNone(validate(self.s,self.s.prepare_request(q),b)[0])
 def test_empty_inventory_and_incompatible_cuff_or_fixed_weapon_are_input_errors(self):
  q=self.request();q['inventory']={};self.assertEqual(self.s.search(q)['status'],'input_conflict')
  q=self.request();q['g_poogie']=False;self.assertEqual(self.s.search(q)['status'],'input_conflict')
  q=self.request();q['cuffs']=[];self.assertEqual(self.s.search(q)['status'],'input_conflict')
 def test_green_partial_witness_survives_joint_skill_addition_without_solver(self):
  q=self.request();b=self.f['road16']['build'];report=self.s.e.evaluate(b)
  target={'skill':'豪放+3'};sid,pt=self.s.requirement(target)
  with tempfile.TemporaryDirectory() as folder:
   service=CandidateService(os.environ['MHF_TEST_DB'],Path(folder)/'cache.json')
   try:
    service.ingest(q,{'results':[{'build':b,'evaluation':report}]})
    with patch('subprocess.Popen',side_effect=AssertionError('Confirmed witness must not start solver')),patch('skill_engine.Engine.evaluate',side_effect=AssertionError('Authenticated same-scope witness must not recalculate')):
     before=service.query(q,[target]);self.assertEqual(before['candidate_states'][f'{sid}|{pt}']['state'],'confirmed')
     after=service.query({**q,'required':q['required']+[target]});self.assertTrue(after['results'])
     self.assertTrue(after['results'][0]['placement']['decorations']['leg'][0]['fixed'])
   finally:service.close()

if __name__=='__main__':unittest.main()
