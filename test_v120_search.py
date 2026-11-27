"""Real integrated DB regressions for Road sets, witnesses, virtual slots and diversity."""
import copy
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from activation import attained
from candidate_service import CandidateService
from candidate_validation import validate
from search_engine import Searcher
from sharing import canonical_build,envelope,decode_json

ROOT=Path(__file__).parent
FIXTURES=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))
OLD=json.loads((ROOT/'ci/regression_builds.json').read_text(encoding='utf-8'))


@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Search120Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)

    @classmethod
    def tearDownClass(cls):cls.db.close()

    def request(self,name='road15',**changes):
        f=FIXTURES[name];q=copy.deepcopy(f['build'])
        for a in q['armor'].values():a['jewels']=[]
        if 'weapon' in q:q['weapon']['jewels']=[]
        q.update(required=f['required'],seconds=10,limit=1,armor_level_mode='first',search_strategy='adaptive')
        q.update(changes);return q

    def verify(self,q,r):
        self.assertTrue(r['results'],r)
        prepared=self.s.prepare_request(q)
        for h in r['results']:
            report,reasons=validate(self.s,prepared,h['build'])
            self.assertIsNotNone(report,reasons);self.assertEqual(report,h['evaluation'])
            self.assertEqual(report['attained'],attained(report))

    def test_real_15_and_16_skill_known_builds_and_fixed_search(self):
        for name,minimum in [('road15',15),('road16',16)]:
            with self.subTest(name=name):
                f=FIXTURES[name];report=self.s.e.evaluate(f['build'])
                self.assertTrue(report['valid']);self.assertGreaterEqual(sum(s['status'] in ('active','overlap') for s in report['skills']),minimum)
                q=self.request(name);r=self.s.search(q);self.verify(q,r)

    def test_earplug_probe_witness_is_reused_in_normal_search(self):
        q=self.request();q.pop('cuffs')
        probe=self.s.probe(q,[{'skill':'耳栓強化+1'}],seconds=12)
        self.assertEqual(probe['results'][0]['status'],'found',probe)
        witness=probe['results'][0]['witness']
        extended={**q,'required':q['required']+[{'skill':'耳栓強化+1'}]}
        r=self.s.search(extended);self.verify(extended,r)
        self.assertGreaterEqual(r['reused_witnesses'],1)
        sid,pt=self.s.requirement({'skill':'耳栓強化+1'})
        self.assertTrue(self.s.achieved(witness['evaluation'],sid,pt))

    def test_probe_witness_immediate_index_and_restriction_scope(self):
        service=CandidateService(Path(os.environ['MHF_TEST_DB']))
        self.addCleanup(service.close)
        q=self.request();q.pop('cuffs')
        witness=FIXTURES['road-earplug']['build'];report=self.s.e.evaluate(witness)
        service.ingest(q,{'results':[{'target':{'skill':'耳栓強化+1'},'status':'found',
                                   'witness':{'build':witness,'evaluation':report,'new_jewels':15}}]},persist=False)
        sid,pt=self.s.requirement({'skill':'耳栓強化+1'})
        result=service.query(q,[{'skill':sid,'points':pt}])
        self.assertGreaterEqual(result['candidate_counts'][f'{sid}|{pt}'],1)
        extended={**q,'required':q['required']+[{'skill':sid,'points':pt}]}
        self.assertTrue(service.query(extended)['results'])
        # The original cuff lock is a different condition; the earplug cuff must not leak into it.
        locked={**extended,'cuffs':FIXTURES['road15']['build']['cuffs']}
        self.assertFalse(service.query(locked)['results'])

    def test_virtual_zero_to_three_slots_and_shared_sigils(self):
        b=copy.deepcopy(OLD['optional']['build'])
        for a in b['armor'].values():a['jewels']=['真磁星珠・白虎']*3
        jewel,sid,pt,_=OLD['optional']['choices'][0]
        base={**b,'required':[{'skill':'磁斬鎚技【磁星】'},{'skill':sid,'points':pt}],
              'jewel_candidates':[jewel],'seconds':5,'limit':1}
        for slots in range(4):
            q={**base,'weapon':{'virtual':True,'slots':slots,'slot_mode':'decoration','sigils':0,'jewels':[]}}
            r=self.s.search(q)
            if slots==0:self.assertFalse(r['results'])
            else:
                self.verify(q,r);w=r['results'][0]['build']['weapon']
                self.assertTrue(w['virtual']);self.assertEqual(w['jewels'],[jewel]);self.assertNotIn('page',w)
        for sigils in (2,3):
            q={**base,'weapon':{'virtual':True,'slots':3,'slot_mode':'shared','sigils':sigils,'jewels':[]}}
            r=self.s.search(q)
            if sigils==2:self.verify(q,r)
            else:self.assertFalse(r['results'])
        bad={**base,'weapon':{'virtual':True,'slots':3,'slot_mode':'decoration','sigils':1}}
        with self.assertRaises(ValueError):self.s.search(bad)

    def test_virtual_round_trip_and_selector_separation(self):
        b=copy.deepcopy(FIXTURES['road16']['build'])
        canon=canonical_build(self.db,b)
        self.assertTrue(canon['weapon']['virtual'])
        self.assertEqual(canonical_build(self.db,decode_json(json.dumps(envelope(canon)))),canon)
        bad=copy.deepcopy(b);bad['weapon']['page']='buki/magspike.htm';bad['weapon']['anchor']='l4244'
        with self.assertRaises(ValueError):self.s.e.evaluate(bad)
        with self.assertRaises(ValueError):canonical_build(self.db,bad)

    def test_physical_weapon_witness_keeps_weapon_metadata_and_is_reusable(self):
        q=json.loads((ROOT/'example_search.json').read_text(encoding='utf-8'))
        q.update(limit=1,seconds=8)
        first=self.s.search(q);self.verify(q,first)
        reused=self.s.search({**q,'_seed_builds':[first['results'][0]['build']]})
        self.verify(q,reused);self.assertGreaterEqual(reused['reused_witnesses'],1)
        self.assertEqual(reused['results'][0]['build']['weapon']['page'],q['weapon']['page'])

    def test_diverse_free_search_changes_multiple_parts(self):
        q={'weapon_type':'MS','sex':'男','g_poogie':True,'premium_poogie_clothes':True,
           'required':[{'skill':x} for x in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+3']],
           'seconds':12,'limit':5,'search_strategy':'adaptive','diverse_armor':True,'collect_variants':True}
        r=self.s.search(q);self.verify(q,r)
        self.assertEqual(r['distinct_armor'],5)
        first=r['results'][0]['build']['armor']
        self.assertTrue(any(sum(first[p]['item']!=h['build']['armor'][p]['item'] for p in first)>=3 for h in r['results'][1:]))

    def test_fixed_armor_group_keeps_real_variations_without_dropping_results(self):
        q=self.request(limit=5,diverse_armor=True,collect_variants=True)
        r=self.s.search(q);self.verify(q,r)
        self.assertEqual(r['distinct_armor'],1);self.assertEqual(len(r['armor_groups']),1)
        self.assertGreater(r['armor_groups'][0]['variant_count'],1)
        self.assertTrue(r['armor_groups'][0]['variants'])

    def test_13_skill_free_search_can_keep_known_witness_and_find_alternatives(self):
        q=self.request('road16',limit=5,seconds=12,diverse_armor=True)
        q['armor']={}
        remove={'巧流','雌伏','餓狼+2'}
        q['required']=[x for x in q['required'] if x['skill'] not in remove]
        q['_seed_builds']=[FIXTURES['road16']['build']]
        r=self.s.search(q);self.verify(q,r)
        self.assertGreaterEqual(r['reused_witnesses'],1)
        self.assertEqual(r['distinct_armor'],5)
        self.assertTrue(all(g['armor_distance']>=3 for g in r['armor_groups'][1:]))

    def test_composite_protection_supplies_zenith_prerequisite(self):
        q=json.loads((ROOT/'example_search.json').read_text(encoding='utf-8'))
        q.pop('weapon');q.pop('cuffs');q.update(required=[{'skill':'豪放+3'},{'skill':'耳栓強化+1'}],seconds=8,limit=1)
        base=self.s.e.names['normal','三界の護り'];secret=self.s.e.names['normal','磁斬鎚技']
        q['jewel_candidates']=[eid for eid,row in self.s.by_kind['jewel'].items()
                               if self.s.points[eid].get(base,0)>0 and not self.s.points[eid].get(secret,0)]
        r=self.s.search(q);self.verify(q,r)
        report=r['results'][0]['evaluation']
        self.assertTrue(any(x['source']=='豪放+3' and '耳栓' in x['target'] for x in report['relations']))
        self.assertTrue(next(x for x in report['zenith'] if x['id']==self.s.e.names['zenith','耳栓強化'])['has_base_skill'])

    def test_outcome_states_are_distinct_and_conflict_is_not_cached_impossibility(self):
        service=CandidateService(Path(os.environ['MHF_TEST_DB']));self.addCleanup(service.close)
        q=self.request()
        self.assertEqual(service.query(q)['status'],'unexplored')
        service.ingest(q,{'status':'time_limit','results':[]},persist=False)
        self.assertEqual(service.query(q)['status'],'time_limit')
        service.ingest(q,{'status':'model_exhausted','results':[]},persist=False)
        self.assertEqual(service.query(q)['status'],'model_exhausted')
        conflict={**q,'forbidden':[q['required'][0]]}
        self.assertEqual(service.query(conflict)['status'],'input_conflict')

    def test_bootstrap_coverage_never_replaces_user_required_or_optional_skills(self):
        service=CandidateService(Path(os.environ['MHF_TEST_DB']));self.addCleanup(service.close)
        q={'weapon_type':'MS','required':[],'optional':[]}
        self.assertEqual(service.coverage_targets(q,1),[])
        targets=service.coverage_targets(q,2);self.assertTrue(targets)
        secret=self.s.e.names['normal','磁斬鎚技']
        self.assertTrue(any(t['skill']==secret and t['points']==30 for t in targets))
        self.assertEqual(service.coverage_targets({**q,'required':[{'skill':'剛撃+6'}]},2),[])
        self.assertEqual(service.coverage_targets({**q,'optional':[{'skill':'雌伏','weight':100}]},2),[])
        self.assertEqual(q,{'weapon_type':'MS','required':[],'optional':[]})

    def test_restored_cache_revalidates_builds_against_current_db(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cache.json';q=self.request();f=FIXTURES['road15'];report=self.s.e.evaluate(f['build'])
            service=CandidateService(Path(os.environ['MHF_TEST_DB']),p)
            service.ingest(q,{'results':[{'build':f['build'],'evaluation':report,'new_jewels':15}]});service.close()
            data=json.loads(p.read_text());key=next(iter(data['scopes']))
            data['scopes'][key][0]['armor']['head']['jewels']=['真磁星珠・白虎']*20
            p.write_text(json.dumps(data))
            restored=CandidateService(Path(os.environ['MHF_TEST_DB']),p)
            self.addCleanup(restored.close)
            self.assertFalse(restored.query(q)['results'])


if __name__=='__main__':unittest.main()
