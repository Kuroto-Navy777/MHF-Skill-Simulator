"""Phase 4B tests using a locally imported DB (not distributed)."""
import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from search_engine import Searcher

ROOT=Path(__file__).resolve().parent

@unittest.skipUnless(os.environ.get('MHF_TEST_DB'),'set MHF_TEST_DB to test imported local data')
class AdvancedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']); cls.s=Searcher(cls.db)
        cls.base=json.loads((ROOT/'example_search.json').read_text())
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def request(self, **kwargs):
        q=copy.deepcopy(self.base); q.update(limit=1,seconds=12,**kwargs); return q
    def verify(self, h, req):
        report=self.s.e.evaluate(h['build']); self.assertEqual(report,h['evaluation']); self.assertTrue(report['valid'])
        for sid,pt in self.s.requirements(req['required']).items(): self.assertTrue(self.s.achieved(report,sid,pt))
        self.assertEqual(h['metrics'],self.s.metrics(h,req))
    def test_optional(self):
        q=self.request(objective='optional',optional=[{'skill':'幕無','weight':3},{'skill':'猛進','weight':2},{'skill':'剣神+3','weight':4}])
        r=self.s.search(q); self.assertTrue(r['results']); h=r['results'][0]; self.verify(h,q);self.assertEqual(h['metrics']['optional_score'],9)
    def test_surplus(self):
        q=self.request(objective='surplus');r=self.s.search(q);self.assertTrue(r['results']);h=r['results'][0];self.verify(h,q);self.assertEqual(h['metrics']['required_surplus'],0)
    def test_max_skills(self):
        q=self.request(objective='max_skills');r=self.s.search(q);self.assertTrue(r['results']);h=r['results'][0];self.verify(h,q);self.assertGreaterEqual(h['metrics']['active_normal_skills'],12)
    def test_grouped_weapon_search(self):
        q=self.request(auto_weapon=True,weapon={'sigils':1},weapon_group_limit=2,weapon_filters={'categories':['zenith'],'min_rarity':12});q['limit']=2
        r=self.s.search(q);self.assertTrue(r['results']);self.assertEqual(r['weapon_groups_searched'],2);self.assertGreater(r['weapon_groups'],2)
        keys=set()
        for h in r['results']:
            self.verify(h,q);w=h['build']['weapon'];k=(w['page'],w['anchor']);self.assertNotIn(k,keys);keys.add(k);self.assertEqual(w['sigils'],1)
            self.assertGreaterEqual(h['weapon_group']['equivalent_count'],1)
        self.assertFalse(r['complete_game_search'])
    def test_fixed_weapon_filter(self):
        q=self.request(weapon_filters={'categories':['normal_hr']})
        with self.assertRaisesRegex(ValueError,'fixed physical weapon excluded'):self.s.search(q)
    def test_weapon_exclusion(self):
        q=self.request(auto_weapon=True,weapon={'sigils':1},weapon_filters={'categories':['zenith']})
        groups,_=self.s.weapon_groups(q); row=groups[0][2][0]; key=f"{row['page']}#{row['anchor']}";q['exclude']=[key]
        groups,_=self.s.weapon_groups(q); self.assertFalse(any(f"{r['page']}#{r['anchor']}"==key for _,_,rs in groups for r in rs))
    def test_probe(self):
        q=self.request();c=[{'skill':'幕無'},{'skill':'剣神+3'},{'skill':'剛撃+6'}];r=self.s.probe(q,c,10)
        self.assertEqual([x['status'] for x in r['results']],['found','found','already_required'])
        for x in r['results'][:2]:self.verify(x['witness'],{**q,'required':q['required']+[x['target']]})
    def test_auto_probe(self):
        q=self.request();r=self.s.probe(q,seconds=8,candidate_limit=2);self.assertTrue(r['auto_candidates']);self.assertEqual(len(r['results']),2);self.assertGreater(r['unselected_candidate_count'],0)
        for x in r['results']:
            if x['status']=='found': self.verify(x['witness'],{**q,'required':q['required']+[x['target']]})
    def test_build_key_ignores_jewel_order_and_placement(self):
        q=self.request();r=self.s.search(q);b=r['results'][0]['build'];clone=copy.deepcopy(b)
        for a in clone['armor'].values():a['jewels'].reverse()
        self.assertEqual(self.s.build_key(b),self.s.build_key(clone))
    def test_bad_objective_and_weight(self):
        with self.assertRaises(ValueError):self.s.search(self.request(objective='unknown'))
        with self.assertRaises(ValueError):self.s.search(self.request(optional=[{'skill':'幕無','weight':0}]))

if __name__=='__main__':unittest.main()
