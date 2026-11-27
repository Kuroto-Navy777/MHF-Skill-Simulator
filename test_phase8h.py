"""Phase 8H external effects and compatibility checks."""
import unittest
import os
import sqlite3
import json
from pathlib import Path
from external import normalize, road_cost, road_special, meal_reference, upper_bonus
from defense import evaluate_stats

class Phase8HTests(unittest.TestCase):
    def test_progress_boundaries(self):
        for floor,expected in [(1,0),(5,0),(6,60),(10,60),(11,70),(16,80),(21,90),(26,100),(100,100)]:
            e=normalize({'road_floor':floor,'road':{'advance':3}})
            self.assertEqual(road_special(e)['advance_attack'],expected)
            self.assertEqual(road_cost(e),40)

    def test_last_stand_and_revival(self):
        e=normalize({'road':{'last_stand':2,'revival':1}})
        r=road_special(e)
        self.assertEqual(road_cost(e),130)
        self.assertEqual((r['last_stand_attack'],r['last_stand_affinity'],r['revival_limit'],r['revival_bonus']),(120,50,1,0))
        self.assertEqual(road_special(normalize({'road':{'revival':1}}))['revival_bonus'],1)

    def test_reward_options(self):
        e=normalize({'road':{'points':3,'initial_gm':2}})
        self.assertEqual(road_cost(e),75)
        self.assertEqual(road_special(e)['points_bonus_percent'],40)
        self.assertEqual(road_special(e)['initial_gm_bonus'],3000)

    def test_utility_meal_no_false_stat_bonus(self):
        e=normalize({'meal':'medicine','quality':3})
        self.assertEqual(meal_reference(e),'薬仙人')
        self.assertTrue(all(v==0 for v in upper_bonus(e).values()))
        stats=evaluate_stats([dict(defense=10,Fire=0,Water=0,Thunder=0,Ice=0,Dragon=0)],[],e)
        self.assertEqual(stats['weapon_delta']['meal_reference'],'薬仙人')
        self.assertEqual(stats['external']['Fire'],0)
        self.assertIsNone(meal_reference(normalize({'meal':'medicine','quality':0})))

    def test_legacy_settings_and_validation(self):
        e=normalize({'meal':'all','quality':3,'road':{'all':3}})
        self.assertEqual(e['road_floor'],1)
        self.assertEqual(road_cost(e),30)
        self.assertEqual(upper_bonus(e)['Fire'],35)
        for req in ({'road_floor':0},{'road_floor':True},{'road':{'advance':4}},{'road':{'revival':2}},{'road':{'last_stand':3}}):
            with self.assertRaises(ValueError): normalize(req)

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local database required')
class Phase8HDataTests(unittest.TestCase):
    def test_real_search_preserves_external_report(self):
        from search_engine import Searcher
        from contextlib import closing
        req=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        req.update(limit=1,seconds=15,external={'road_floor':26,'road':{'advance':3,'last_stand':1},'meal':'medicine','quality':3})
        with closing(sqlite3.connect(os.environ['MHF_TEST_DB'])) as db:
            result=Searcher(db).search(req)
            self.assertTrue(result['results'],result['status'])
            hit=result['results'][0]
            self.assertTrue(hit['evaluation']['valid'])
            w=hit['evaluation']['defense_stats']['weapon_delta']
            self.assertEqual(w['road_special']['advance_attack'],100)
            self.assertEqual(w['road_special']['last_stand_attack'],80)
            self.assertEqual(w['meal_reference'],'薬仙人')
            self.assertEqual(hit['evaluation']['defense_stats']['road_cost'],90)
            print('Phase 8H real search seconds:',result['elapsed_seconds'])

if __name__=='__main__': unittest.main()
