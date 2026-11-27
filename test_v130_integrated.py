import os,copy,json,sqlite3,unittest
from pathlib import Path
from search_engine import Searcher
from candidate_validation import validate
from weapon_effects import intrinsic_levels

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Integrated130Tests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)
  cls.fixtures=json.loads(Path('ci/v120_regression_builds.json').read_text(encoding='utf-8'))
  cls.ear=cls.s.e.names['zenith','聴覚保護強化'] if ('zenith','聴覚保護強化') in cls.s.e.names else cls.s.requirement({'skill':'耳栓強化+1'})[0]
  cls.weapons={}
  for _,_,rows in cls.s.weapon_groups({'weapon_type':'MS','required':[],'weapon':{}})[0]:
   r=rows[0];pts=dict(cls.db.execute('select skill_id,points from ferias_zenith where weapon_type=? and page=? and anchor=?',('MS',r['page'],r['anchor'])))
   if r['slot_mode']=='shared' and r['slots_reported']==3:cls.weapons.setdefault('ear' if pts.get(cls.ear,0)>=1 else 'other',dict(r))
 @classmethod
 def tearDownClass(cls):cls.db.close()
 def base(self,name='road15'):
  f=self.fixtures[name];q=copy.deepcopy(f['build'])
  for a in q['armor'].values():a['jewels']=[]
  q.pop('weapon',None);q.pop('cuffs',None)
  q.update(required=f['required'],seconds=12,limit=1,search_strategy='adaptive',armor_level_mode='first',search_mode='fixed',auto_weapon=True,integrated_weapon=True,weapon={'sigils':0})
  return q
 def selector(self,key):
  r=self.weapons[key];return {'page':r['page'],'anchor':r['anchor']}
 def verify(self,q,r):
  self.assertTrue(r['results'],r.get('reason',r['status']))
  prepared=self.s.prepare_request(q)
  for h in r['results']:
   report,why=validate(self.s,prepared,h['build']);self.assertIsNotNone(report,why);self.assertEqual(report,h['evaluation'])
 def test_automatic_clears_stale_fixed_gear_without_inventory_registration(self):
  q={'weapon_type':'MS','search_mode':'automatic','sigil_mode':'auto','armor':{'head':{'item':'does-not-exist'}},'cuffs':['invalid'],'weapon':{'page':'bad','anchor':'bad'},'required':[{'skill':n} for n in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+3','耳栓強化+1']],'seconds':12,'limit':5,'diverse_armor':True,'search_strategy':'adaptive'}
  r=self.s.search(q);self.verify(q,r);self.assertEqual(r['distinct_armor'],5);self.assertTrue(r['integrated_weapon']);self.assertEqual(r['rejected'],0)
  self.assertTrue(all(h['build']['g_poogie'] and h['build']['premium_poogie_clothes'] for h in r['results']))
 def test_joint_mode_supports_all_fourteen_weapon_types(self):
  from skill_engine import WEAPON_SECRET
  for wt in WEAPON_SECRET:
   with self.subTest(weapon_type=wt):
    q={'weapon_type':wt,'search_mode':'automatic','sigil_mode':'auto','required':[{'skill':'剛撃+6'}],'seconds':4,'limit':1,'search_strategy':'adaptive'}
    r=self.s.search(q);self.verify(q,r);self.assertTrue(r['integrated_weapon'])
 def test_weapon_zenith_releases_cuff_and_cuff_compensates_for_other_weapon(self):
  q=self.base();q['required']=q['required']+[{'skill':'耳栓強化+1'}];q['cuffs']=self.fixtures['road15']['build']['cuffs'];q['weapon_candidates']=[self.selector('ear')]
  r=self.s.search(q);self.verify(q,r)
  q['weapon_candidates']=[self.selector('other')];bad=self.s.search(q);self.assertFalse(bad['results'])
  q.pop('cuffs');r=self.s.search(q);self.verify(q,r);self.assertNotEqual(r['results'][0]['build']['cuffs'],self.fixtures['road15']['build']['cuffs'])
 def test_physical_weapon_slots_and_16_skills_without_registered_items(self):
  q=self.base('road16');q['weapon_candidates']=[self.selector('ear')];r=self.s.search(q);self.verify(q,r)
  self.assertGreaterEqual(r['results'][0]['metrics']['active_normal_skills'],16)
  allocation=next(x for x in r['results'][0]['evaluation']['slots']['equipment'] if x['part']=='weapon');self.assertGreater(allocation['used'],0)
 def test_high_difficulty_free_search_without_owned_or_known_build_seed(self):
  # A fresh Searcher has no previous witness or registered inventory.
  for name in ('road15','road16'):
   solver=Searcher(self.db);q=self.base(name);q.update(search_mode='automatic',sigil_mode='auto',limit=3,seconds=20,diverse_armor=True)
   r=solver.search(q);self.verify(q,r);self.assertEqual(r['distinct_armor'],3)
   self.assertGreaterEqual(r['results'][0]['metrics']['active_normal_skills'],15 if name=='road15' else 16)
 def test_sigil_shared_capacity_and_fixed_reservation(self):
  b=copy.deepcopy(self.fixtures['road16']['build']);b['weapon']={**self.selector('ear'),'jewels':b['weapon']['jewels'],'sigils':0}
  used=sum(self.s.e.equipment(j,'jewel')['slots'] for j in b['weapon']['jewels']);self.assertGreater(used,0)
  for n in range(4):
   b['weapon']['sigils']=n;r=self.s.e.evaluate(b);self.assertEqual(r['valid'],used+n<=3)
 def test_owned_inventory_is_only_applied_when_requested(self):
  q=self.base();r=self.s.search(q);self.verify(q,r)
  q['inventory']={};q['structured_outcomes']=True;r=self.s.search(q);self.assertEqual(r['status'],'input_conflict');self.assertFalse(r['results'])
 def test_declared_intrinsic_is_mapped_but_unknown_text_is_not(self):
  row=self.db.execute("select * from ferias_variants where category='始種武器' and intrinsic_raw like '%Issen+2%' limit 1").fetchone();self.assertIsNotNone(row)
  tiers,unknown=intrinsic_levels(self.s.e,row);self.assertFalse(unknown);self.assertEqual(tiers[0]['ja'],'一閃+2')
  b={'weapon_type':row['weapon_type'],'armor':{},'weapon':{'page':row['page'],'anchor':row['anchor'],'sigils':0,'jewels':[]}}
  report=self.s.e.evaluate(b);self.assertTrue(self.s.achieved(report,tiers[0]['skill_id'],tiers[0]['points']))
  altered=dict(row);altered['intrinsic_raw']='["≪Origin Weapon：Unknown invented effect≫"]';self.assertTrue(intrinsic_levels(self.s.e,altered)[1])
 def test_intrinsic_weapon_participates_in_joint_optimization(self):
  row=self.db.execute("select * from ferias_variants where category='始種武器' and intrinsic_raw like '%Issen+2%' and weapon_type='SnS' limit 1").fetchone()
  q=self.base();q.update(weapon_type='SnS',weapon_candidates=[dict(page=row['page'],anchor=row['anchor'])],required=[{'skill':'一閃+2'}],jewel_candidates=[],cuff_candidates=[])
  r=self.s.search(q);self.verify(q,r);self.assertTrue(any(s['ja']=='一閃+2' for s in r['results'][0]['evaluation']['automatic']))
 def test_fixed_physical_weapon_can_optimize_sigil_reservation(self):
  q=self.base();q['auto_weapon']=False;q['weapon']={**self.selector('ear'),'sigils':3,'jewels':[]};q['sigil_mode']='auto'
  r=self.s.search(q);self.verify(q,r)
  self.assertTrue(all(h['build']['weapon']['page']==q['weapon']['page'] and h['build']['weapon']['anchor']==q['weapon']['anchor'] for h in r['results']))
 def test_probe_input_errors_are_visible_and_do_not_become_impossibility(self):
  q=self.base();q['structured_outcomes']=True
  r=self.s.probe(q,seconds=0);self.assertEqual(r['status'],'input_conflict');self.assertTrue(r['reason']);self.assertTrue(r['auto_candidates'])
 def test_probe_is_paginated_beyond_twelve_and_witness_reused(self):
  q=self.base();q['required']=[{'skill':'剛撃+6'}];q['weapon_candidates']=[self.selector('ear')]
  a=self.s.probe(q,candidates=[{'skill':'耳栓強化+1'}],seconds=5);self.assertEqual(a['results'][0]['status'],'found')
  q['required'].append({'skill':'耳栓強化+1'});q['_seed_builds']=[a['results'][0]['witness']['build']];r=self.s.search(q);self.verify(q,r);self.assertGreater(r['reused_witnesses'],0)
  a=self.s.probe(q,seconds=1,candidate_limit=24);b=self.s.probe(q,seconds=1,candidate_limit=24,candidate_offset=a['next_offset'])
  keys=lambda r:{(x['target']['skill'],x['target']['points']) for x in r['results']}
  self.assertEqual(len(a['results']),24);self.assertFalse(keys(a)&keys(b));self.assertGreater(a['unselected_candidate_count'],12)

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class JointExhaustive130Tests(unittest.TestCase):
 def test_joint_weapons_sigils_and_jewels_match_all_legal_packings(self):
  import itertools
  from test_v120_exhaustive import ExhaustiveTests
  fixture=ExhaustiveTests
  fixture.setUpClass()
  try:
   db=fixture.db;old=fixture.s
   groups,_=old.weapon_groups({'weapon_type':'MS','required':[],'weapon':{}})
   rows=[dict(g[2][0]) for g in groups if g[2][0]['slot_mode']=='shared'][:2]
   self.assertEqual(len(rows),2)
   for cap,r in enumerate(rows,1):
    db.execute('UPDATE ferias_variants SET slots_reported=? WHERE weapon_type=? AND page=? AND anchor=?',(cap,'MS',r['page'],r['anchor']))
    db.execute('DELETE FROM ferias_zenith WHERE weapon_type=? AND page=? AND anchor=?',('MS',r['page'],r['anchor']))
   db.commit();solver=Searcher(db)
   q=copy.deepcopy(fixture.base);q.pop('weapon');q['armor']={}
   q.update(auto_weapon=True,integrated_weapon=True,sigil_mode='auto',weapon={'sigils':0},
    weapon_candidates=[{'page':r['page'],'anchor':r['anchor']} for r in rows],
    required=[{'skill':fixture.g,'points':50}],armor_level_mode='first',g_armor_only=False,
    armor_candidates={p:fixture.heads if p=='head' else [fixture.base['armor'][p]['item']] for p in fixture.parts},
    jewel_candidates=fixture.jewels,jewel_limits={j:1 for j in fixture.jewels},seconds=15,limit=30,search_strategy='full')
   def key(b):
    jewels=[j for a in list(b['armor'].values())+[b['weapon']] for j in a.get('jewels',[])]
    return b['armor']['head']['item'],b['weapon']['page'],b['weapon']['anchor'],b['weapon']['sigils'],tuple(jewels.count(j) for j in fixture.jewels)
   expected=set();checked=0
   for cap,r in enumerate(rows,1):
    for sigils in range(cap+1):
     capacities=fixture.capacities+[cap-sigils]
     placements=[[(a,b) for a in range(2) for b in range(2) if a+2*b<=size] for size in capacities]
     for head,packing in itertools.product(fixture.heads,itertools.product(*placements)):
      if any(sum(p[j] for p in packing)>1 for j in (0,1)):continue
      build=copy.deepcopy(fixture.base);build['armor']['head']['item']=head
      build['weapon']={'page':r['page'],'anchor':r['anchor'],'sigils':sigils,'jewels':[]}
      for part,(a,b) in zip(fixture.parts+['weapon'],packing):
       target=build['weapon'] if part=='weapon' else build['armor'][part]
       target['jewels']=[fixture.jewels[0]]*a+[fixture.jewels[1]]*b
      checked+=1;report=solver.e.evaluate(build)
      if report['valid'] and solver.achieved(report,fixture.g,50):expected.add(key(build))
   actual=set()
   for n in range(3):
    request={**q,'sigil_mode':'fixed','weapon':{'sigils':n}}
    result=solver.search(request);self.assertEqual(result['status'],'model_exhausted')
    actual.update(key(h['build']) for h in result['results'])
   self.assertEqual(actual,expected)
   optimized=solver.search(q)
   self.assertEqual({key(h['build']) for h in optimized['results']},{k for k in expected if k[3]==0})
   self.assertTrue(expected);self.assertGreater(checked,50)
  finally:fixture.tearDownClass()

if __name__=='__main__':unittest.main()
