"""Phase 8A: independent armor totals and solver constraints."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from defense import armor_values, evaluate_stats, skill_modifier, constraints, satisfies
from skill_engine import Engine
from search_engine import Searcher

class StatsTests(unittest.TestCase):
    def test_signed_and_tier_amounts(self):
        p=armor_values('{"elemental":{"Fire":"-2","Water":"1","Thunder":"2","Ice":"3","Dragon":"4"}}',100)
        r=evaluate_stats([p,p],['防御+90','各耐性+20','火耐性-10','各耐性+20'])
        self.assertEqual(r['adjusted'],{'defense':290,'Fire':6,'Water':22,'Thunder':24,'Ice':26,'Dragon':28})
        self.assertEqual(skill_modifier('火耐性+30'),{'Fire':30})

    def test_missing_and_invalid(self):
        r=evaluate_stats([armor_values('{}',None)],['各耐性+20'])
        self.assertIsNone(r['adjusted']['Fire'])
        self.assertFalse(satisfies({'defense_stats':r},{'min_stats':{'Fire':0}}))
        for v in (True,1.5,'10'):
            with self.assertRaises(ValueError): constraints({'min_stats':{'Fire':v}})

    def test_base_and_adjusted(self):
        r=evaluate_stats([armor_values('{"elemental":{"Fire":"5"}}',20)],['火耐性+10'])
        self.assertTrue(satisfies({'defense_stats':r},{'min_stats':{'Fire':15}}))
        self.assertFalse(satisfies({'defense_stats':r},{'min_stats':{'Fire':15},'stat_mode':'base'}))

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local DB required')
class RealStatsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']); cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def request(self):
        r=json.loads(Path('example_search.json').read_text()); r.update(required=[],limit=1,seconds=8,cuffs=[])
        return r
    def test_known_armor_totals(self):
        b=json.loads(Path('example_build.json').read_text()); r=self.s.e.evaluate(b)['defense_stats']
        self.assertEqual(r['base'],{'defense':1954,'Fire':3,'Water':5,'Thunder':4,'Ice':5,'Dragon':0})
    def test_base_limits_and_impossible(self):
        r=self.request();r.update(min_stats={'defense':1954,'Fire':3},stat_mode='base')
        h=self.s.search(r);self.assertTrue(h['results'],h['status']);self.assertTrue(satisfies(h['results'][0]['evaluation'],r))
        r['min_stats']['defense']=9999
        self.assertFalse(self.s.search(r)['results'])
    def test_adjusted_search(self):
        r=self.request();r.update(min_stats={'Fire':13},stat_mode='adjusted')
        h=self.s.search(r);self.assertTrue(h['results'],h['status']);p=h['results'][0]['evaluation']['defense_stats'];self.assertGreaterEqual(p['adjusted']['Fire'],13);self.assertEqual(p['base']['Fire'],3)
    def test_stat_objective(self):
        r=self.request();r.update(objective='defense',stat_mode='base')
        h=self.s.search(r);self.assertTrue(h['results'],h['status']);self.assertEqual(h['results'][0]['metrics']['defense'],1954)
