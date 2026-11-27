"""Phase 8E: catalog and conservative forbidden-tier regression tests."""
import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from skill_catalog import catalog
from search_engine import Searcher
from skill_engine import WEAPON_SECRET


@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class SkillCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = sqlite3.connect(os.environ['MHF_TEST_DB'])
        cls.s = Searcher(cls.db)
        cls.rows = catalog(cls.db)
        cls.req = json.loads(Path('example_search.json').read_text(encoding='utf-8'))

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_catalog_preserves_thresholds_and_categories(self):
        self.assertEqual(len(self.rows), self.db.execute('SELECT count(*) FROM skill_levels').fetchone()[0])
        self.assertTrue(any(x['points']<0 for x in self.rows))
        self.assertEqual({x['family_ja'] for x in self.rows if x['category']=='secret'},set(WEAPON_SECRET.values()))
        self.assertTrue(any(x['ja']=='剛撃+6' and x['points']==50 and x['category']=='offense' for x in self.rows))

    def test_source_relations(self):
        furta=next(x for x in self.rows if x['ja']=='不退ノ構')
        self.assertIn({'type':'DeactivateSkills','name':'一閃+3'},furta['relations']['ja'])
        ear=next(x for x in self.rows if x['ja']=='耳栓強化+1')
        self.assertEqual(ear['target']['ja'],'聴覚保護')

    def test_conflict_and_tier_boundary(self):
        req=copy.deepcopy(self.req); req['forbidden']=[{'skill':'剛撃+5'}]
        with self.assertRaisesRegex(ValueError,'conflict'): self.s.search(req)
        req['required']=[{'skill':'剛撃+4'}]
        self.assertEqual(self.s.conflicts(req),{self.s.e.names['normal','剛撃']:40})

    def test_automatic_and_zenith_validation(self):
        sid=self.s.e.names['normal','不退']; z=self.s.e.names['zenith','耳栓強化']
        r={'skills':[],'zenith':[],'automatic':[{'id':sid,'ja':'不退ノ構'}]}
        self.assertTrue(self.s.forbidden_hit(r,{sid:10}))
        r={'skills':[],'zenith':[{'id':z,'raw_points':1}],'automatic':[]}
        self.assertTrue(self.s.forbidden_hit(r,{z:1}))
        self.assertFalse(self.s.forbidden_hit(r,{z:2}))

    def test_real_search_with_forbidden_tier(self):
        req=copy.deepcopy(self.req); req.update(required=[{'skill':'巧撃'}],forbidden=[{'skill':'不退ノ構'}],limit=1,seconds=12)
        result=self.s.search(req)
        self.assertTrue(result['results'], result['status'])
        for h in result['results']:
            self.assertFalse(self.s.forbidden_hit(h['evaluation'],self.s.conflicts(req)))

    def test_probe_skips_forbidden(self):
        req=copy.deepcopy(self.req);req['forbidden']=[{'skill':'一閃+1'}]
        r=self.s.probe(req,candidates=[{'skill':'一閃+3'}],seconds=1)
        self.assertEqual(r['results'],[])

if __name__=='__main__': unittest.main()
