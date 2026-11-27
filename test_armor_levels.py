"""Phase 8J2: endpoint selection and comparison regressions."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from armor_levels import endpoint, comparison
from skill_engine import Engine
from search_engine import Searcher
from catalog import catalog

class LevelTests(unittest.TestCase):
    def test_endpoints(self):
        rows=[('L7',3,40),('L1',1,10),('L4',2,30)]
        self.assertEqual(endpoint(rows,'first'),rows[1])
        self.assertEqual(endpoint(rows,'max'),rows[0])
        self.assertEqual(endpoint([rows[1]],'max'),rows[1])
        self.assertIsNone(endpoint([], 'first'))
        with self.assertRaises(ValueError): endpoint(rows,'bad')
    def test_slot_overflow(self):
        r=comparison([('head','Example','L7',2,[('L1',1,10),('L7',3,40)])],{'bonus':{'defense':20},'external_bonus':{'defense':5}})
        self.assertEqual(r['first']['base'],10)
        self.assertFalse(r['first']['fits'])
        self.assertIsNone(r['first']['adjusted'])
        self.assertEqual(r['max']['external'],65)
    def test_unknown_defense(self):
        r=comparison([('head','Example','L1',0,[('L1',1,None)])],{'bonus':{'defense':0},'external_bonus':{'defense':0}})
        self.assertIsNone(r['max']['base'])

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local DB required')
class RealLevelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def test_same_armor_comparison(self):
        b=json.loads(Path('example_build.json').read_text());r=self.s.e.evaluate(b);v=r['defense_stats']['armor_levels']
        self.assertEqual(v['first']['base'],1954)
        self.assertEqual(v['max']['base'],2077)
        self.assertEqual(v['max']['slots'],15)
        self.assertEqual([x['level'] for x in v['max']['parts']],['L1','L7','L7','L7','L1'])
        for a,x in zip(b['armor'].values(),v['max']['parts']): a['level']=x['level']
        upgraded=self.s.e.evaluate(b)
        self.assertEqual(r['skills'],upgraded['skills']);self.assertEqual(r['zenith'],upgraded['zenith'])
        self.assertEqual(upgraded['defense_stats']['base']['defense'],2077)
    def test_solver_mode_and_explicit_override(self):
        q=json.loads(Path('example_search.json').read_text());q.update(required=[],objective='defense',stat_mode='base',limit=1,seconds=8)
        for a in q['armor'].values(): a.pop('level')
        for mode,expected in [('first',1954),('max',2077)]:
            q['armor_level_mode']=mode
            r=self.s.search(q);self.assertTrue(r['results'],r['status']);self.assertEqual(r['results'][0]['metrics']['defense'],expected)
        q['armor']['body']['level']='L1'
        r=self.s.search(q);self.assertTrue(r['results']);self.assertEqual(r['results'][0]['metrics']['defense'],2036)
    def test_catalog_endpoints(self):
        args=dict(kind='body',q='グリディZXメイル',weapon_type='MS',page=1,page_size=10,rank='',job='',sex='',hide_unavailable=True,hide_paid=False,hide_festival=False,sort='defense',lang='ja')
        a=catalog(self.db,**args,level_mode='first')['items'][0]
        self.assertEqual(a['first']['defense'],400);self.assertEqual(a['latest']['defense'],441)
        self.assertEqual(a['slots'],3)
