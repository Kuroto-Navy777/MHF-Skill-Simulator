"""Regression tests for diversity and inventory restrictions."""
import copy
import json
import os
import sqlite3
import unittest
from collections import Counter
from pathlib import Path
from search_engine import Searcher

@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class Phase5CTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB'])
        cls.s=Searcher(cls.db)
        cls.fixed=json.loads(Path('example_search.json').read_text())
        cls.build=json.loads(Path('example_build.json').read_text())
    @classmethod
    def tearDownClass(cls): cls.db.close()

    # Use a previously validated set as a known feasible owned-only case.
    def owned(self):
        counts=Counter()
        for p,a in self.build['armor'].items(): counts[self.s.e.equipment(a['item'],p)['id']]+=1
        for a in [*self.build['armor'].values(),self.build['weapon']]:
            for j in a['jewels']: counts[self.s.e.equipment(j,'jewel')['id']]+=1
        for c in self.build['cuffs']: counts[self.s.e.equipment(c,'cuff')['id']]+=1
        return dict(counts)

    def test_owned_search(self):
        req=copy.deepcopy(self.fixed);req['inventory']=self.owned();req['limit']=1;del req['cuffs']
        result=self.s.search(req);self.assertTrue(result['results'],result['status'])
        b=result['results'][0]['build']; self.assertTrue(result['results'][0]['evaluation']['valid'])
        used=Counter()
        for p,a in b['armor'].items(): used[a['item']]+=1
        for a in [*b['armor'].values(),b['weapon']]: used.update(a['jewels'])
        used.update(b['cuffs']);self.assertTrue(all(n<=req['inventory'].get(k,0) for k,n in used.items()))

    def test_fixed_unowned_jewel(self):
        req=copy.deepcopy(self.fixed);req['inventory']=self.owned();req['armor']['head']['jewels']=['真磁星珠・白虎']*4
        with self.assertRaisesRegex(ValueError,'exceeds owned'): self.s.search(req)

    def test_fixed_unowned_cuff(self):
        req=copy.deepcopy(self.fixed);req['inventory']=self.owned();req['inventory'].pop(self.s.e.equipment(req['cuffs'][0],'cuff')['id'])
        with self.assertRaisesRegex(ValueError,'exceeds owned'): self.s.search(req)

    def test_owned_intersection(self):
        req=copy.deepcopy(self.fixed);req['inventory']=self.owned();req['armor_candidates']={'head':[]}
        with self.assertRaisesRegex(ValueError,'not owned or excluded'): self.s.search(req)

    def test_distinct_fixed(self):
        req=copy.deepcopy(self.fixed);req['diverse_armor']=True;req['limit']=2
        r=self.s.search(req);self.assertEqual(len(r['results']),1,r['status'])

    def test_distinct_auto(self):
        req=copy.deepcopy(self.fixed);del req['armor']['head'];req['required']=[{'skill':'剛撃+6'}];req['diverse_armor']=True;req['limit']=2
        r=self.s.search(req);self.assertEqual(len(r['results']),2,r['status'])
        self.assertNotEqual(*(h['build']['armor']['head']['item'] for h in r['results']))

if __name__=='__main__': unittest.main()
