"""Solver tests and integration tests against a locally imported database."""
import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from collections import Counter
from search_engine import Model, Searcher

ROOT=Path(__file__).resolve().parent

class ModelTests(unittest.TestCase):
    def test_signed_constraints(self):
        m=Model(); a=m.var(cost=1); b=m.var(cost=2)
        m.add({a:5,b:-3},low=4)
        r=m.solve(3); self.assertEqual(r.status,0); self.assertEqual(list(r.x),[1,0])

    def test_infeasible_model(self):
        m=Model(); a=m.var();m.add({a:1},low=2)
        self.assertEqual(m.solve(3).status,2)

@unittest.skipUnless(os.environ.get('MHF_TEST_DB'),'set MHF_TEST_DB to test imported local data')
class SearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']); cls.s=Searcher(cls.db)
        cls.fixed=json.loads((ROOT/'example_search.json').read_text())
        cls.auto=json.loads((ROOT/'example_auto_search.json').read_text())
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def request(self):
        return copy.deepcopy(self.fixed)
    def all_jewels(self,b):
        return [self.s.e.equipment(j,'jewel')['id'] for a in list(b['armor'].values())+[b['weapon']] for j in a.get('jewels',[])]
    def verify(self,result,req):
        self.assertTrue(result['results'],result['status'])
        for hit in result['results']:
            r=self.s.e.evaluate(hit['build']); self.assertTrue(r['valid']);self.assertEqual(r,hit['evaluation'])
            self.assertFalse(r['fully_verified']);self.assertFalse(result['complete_game_search'])
            normal={x['id']:x for x in r['skills']}; zen={x['id']:x for x in r['zenith']}
            for wanted in req['required']:
                sid,pt=self.s.requirement(wanted)
                if sid.startswith('normal:'):
                    self.assertEqual(normal[sid]['status'],'active');self.assertGreaterEqual(normal[sid]['threshold'],pt)
                else:
                    self.assertGreaterEqual(zen[sid]['level'],pt);self.assertIsNot(zen[sid]['has_base_skill'],False)
            for a in r['slots']['equipment']:
                self.assertLessEqual(a['used']+a.get('sigils',0),a['capacity'])
    def test_fixed_multiple(self):
        req=self.request(); r=self.s.search(req);self.verify(r,req);self.assertEqual(len(r['results']),2)
        self.assertNotEqual(Counter(self.all_jewels(r['results'][0]['build'])),Counter(self.all_jewels(r['results'][1]['build'])))
        for h in r['results']:
            for part,a in req['armor'].items(): self.assertEqual(h['build']['armor'][part]['item'],self.s.e.equipment(a['item'],part)['id']);self.assertEqual(h['build']['armor'][part]['level'],a['level'])
            self.assertEqual(h['build']['cuffs'],req['cuffs']);self.assertEqual(h['build']['weapon']['sigils'],1)
    def test_auto_protection(self):
        r=self.s.search(self.auto);self.verify(r,self.auto)
        self.assertTrue(all(p['super_protection'] for p in r['results'][0]['evaluation']['protection']))
    def test_fixed_jewel_and_inventory(self):
        req=self.request();req['limit']=1;req['armor']['head']['jewels']=['真磁星珠・白虎'];req['jewel_limits']={'真磁星珠・白虎':3};req['exclude']=['ラヴィ狂射珠GX5']
        r=self.s.search(req);self.verify(r,req)
        b=r['results'][0]['build'];ids=self.all_jewels(b); j=self.s.e.equipment('真磁星珠・白虎','jewel')['id'];bad=self.s.e.equipment('ラヴィ狂射珠GX5','jewel')['id']
        self.assertIn(j,b['armor']['head']['jewels']);self.assertLessEqual(ids.count(j),3);self.assertNotIn(bad,ids)
    def test_excluded_fixed_armor(self):
        req=self.request();req['exclude']=[req['armor']['head']['item']]
        with self.assertRaises(ValueError):self.s.search(req)
    def test_empty_jewel_pool(self):
        req=self.request();req['jewel_candidates']=[]
        r=self.s.search(req);self.assertFalse(r['results']);self.assertEqual(r['status'],'model_exhausted')
    def test_over_inventory_fixed(self):
        req=self.request();req['armor']['head']['jewels']=['真磁星珠・白虎']*2;req['jewel_limits']={'真磁星珠・白虎':1}
        with self.assertRaises(ValueError):self.s.search(req)
    def test_english_level(self):
        sid,pt=self.s.requirement({'skill':'剛撃+6'});en=next(x['en'] for x in self.s.e.levels[sid] if x['points']==pt)
        self.assertEqual(self.s.requirement({'skill':en}),(sid,pt))

if __name__=='__main__': unittest.main()
