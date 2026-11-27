"""Regression for automatic weapon selection and known complex skill builds."""
import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from search_engine import Searcher

@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'user-generated DB required')
class Phase9Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB'])
        cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_single_weapon_group_returns_requested_count(self):
        q=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        w=q.pop('weapon')
        # Use explicit small jewel pool containing multiple established solutions.
        baseline=json.loads(Path('example_build.json').read_text(encoding='utf-8'))
        q['jewel_candidates']=sorted({j for a in [*baseline['armor'].values(),baseline['weapon']] for j in a['jewels']})
        q.update(auto_weapon=True,weapon={'sigils':1},weapon_candidates=[{'page':w['page'],'anchor':w['anchor']}],search_strategy='full',limit=2,seconds=15)
        r=self.s.search(q)
        self.assertEqual(r['weapon_groups'],1)
        self.assertEqual(len(r['results']),2,r['status'])
        self.assertNotEqual(self.s.build_key(r['results'][0]['build']),self.s.build_key(r['results'][1]['build']))
        q['results_per_weapon_group']=1
        self.assertEqual(len(self.s.search(q)['results']),1)

    def test_known_complex_build_replay(self):
        b=json.loads(Path('example_build.json').read_text(encoding='utf-8'))
        r=self.s.e.evaluate(b)
        self.assertTrue(r['valid'])
        normal=[{'skill':x['id'],'points':x['threshold']} for x in r['skills'] if x['status']=='active' and self.s.selectable({'ja':x['level_ja'],'points':x['threshold']})]
        zen=[{'skill':x['id'],'points':x['level']} for x in r['zenith'] if x['level'] and x['has_base_skill'] is not False]
        self.assertEqual(len(normal),16)
        self.assertEqual(len(zen),3)
        q=copy.deepcopy(b);q.update(required=normal+zen,limit=1,seconds=10,search_strategy='full')
        out=self.s.search(q)
        self.assertTrue(out['results'],out['status'])
        for h in out['results']:
            self.assertTrue(h['evaluation']['valid'])
            self.assertEqual(self.s.e.evaluate(h['build']),h['evaluation'])
            self.assertTrue(all(self.s.achieved(h['evaluation'],sid,pt) for sid,pt in self.s.requirements(q['required']).items()))

if __name__=='__main__': unittest.main()
