"""Signed Blue Soul requirements and exact description alias regression tests."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from skill_catalog import matched_description, description_key
from search_engine import Searcher

class AliasTests(unittest.TestCase):
    def test_exact_signed_threshold(self):
        r={'ja':'片手剣技【剣聖】','en':'SnS Tech (Sword Saint)','kind':'normal','points':30}
        d={description_key('normal','Sword Saint',30):'matched'}
        self.assertEqual(matched_description(r,d),'matched')
        self.assertIsNone(matched_description({**r,'points':20},d))
        self.assertIsNone(matched_description({**r,'kind':'zenith'},d))
        self.assertIsNone(matched_description({**r,'ja':'unknown'},d))

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local database required')
class SoulTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)
        cls.sid=cls.s.e.names['normal','喝']
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def request(self):
        q=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        q.update(required=[{'skill':'青魂'}],cuffs=[],jewel_candidates=['マグシア射珠GX1'],limit=1,seconds=8)
        return q
    def test_signed_requirements(self):
        self.assertEqual(self.s.requirement({'skill':'青魂'}),(self.sid,-10))
        self.assertEqual(self.s.requirements([{'skill':'青魂'},{'skill':'青魂'}]),{self.sid:-10})
        with self.assertRaises(ValueError): self.s.requirements([{'skill':'青魂'},{'skill':'赤魂'}])
        with self.assertRaises(ValueError): self.s.conflicts({'required':[{'skill':'青魂'}],'forbidden':[{'skill':'青魂'}]})
        self.s.conflicts({'required':[{'skill':'赤魂'}],'forbidden':[{'skill':'青魂'}]})
        with self.assertRaises(ValueError): self.s.requirement({'skill':'毒倍加'})
    def test_actual_search(self):
        q=self.request();r=self.s.search(q);self.assertTrue(r['results'],r['status']);h=r['results'][0]
        self.assertTrue(self.s.achieved(h['evaluation'],self.sid,-10));self.assertFalse(self.s.achieved(h['evaluation'],self.sid,10))
        self.assertGreater(h['new_jewels'],0)
        self.assertGreaterEqual(h['metrics']['required_surplus'],0)
        self.assertTrue(self.s.forbidden_hit(h['evaluation'],{self.sid:-10}));self.assertFalse(self.s.forbidden_hit(h['evaluation'],{self.sid:10}))
    def test_forbidden_search(self):
        q=self.request();q['required']=[{'skill':'剛撃+3'}];q['forbidden']=[{'skill':'青魂'}]
        q['armor']['head']['jewels']=['マグシア射珠GX1']*3
        q['armor']['body']['jewels']=['マグシア射珠GX1']
        self.assertFalse(self.s.search(q)['results'])
    def test_optional_search(self):
        q=self.request();q['required']=[{'skill':'剛撃+3'}];q['optional']=[{'skill':'青魂','weight':10}];q['objective']='optional'
        r=self.s.search(q);self.assertTrue(r['results'],r['status']);self.assertEqual(r['results'][0]['metrics']['optional_score'],10)

if __name__=='__main__': unittest.main()
