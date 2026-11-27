"""Phase 8I regression tests against a local, user-imported master."""
import json
import os
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from skill_engine import Engine
from search_engine import Searcher

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local data required')
class Phase8ITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB'])
        cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls): cls.db.close()

    def test_meal_skill_no_slot_and_no_boost(self):
        b={'weapon_type':'MS','external':{'meal':'protection','quality':3},'weapon':{'template':'辿異武器(耳栓強化)','slots':3,'slot_mode':'shared'}}
        r=self.s.e.evaluate(b)
        self.assertEqual(r['slots']['used'],0)
        self.assertEqual(r['automatic'][0]['source'],'meal')
        self.assertEqual(r['automatic'][0]['ja'],'豪放+3')
        self.assertEqual(r['protection'][0]['effective_level'],'超高級耳栓')
        self.assertFalse(r['protection'][0]['super_protection'])
        self.assertFalse(r['zenith'][0]['has_base_skill'])

    def test_meal_search_and_prohibition(self):
        q=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        q.update(required=[{'skill':'薬仙人'}],external={'meal':'medicine','quality':3},jewel_candidates=[],cuffs=[],limit=1,seconds=8)
        r=self.s.search(q);self.assertTrue(r['results'],r['status'])
        self.assertEqual(r['results'][0]['new_jewels'],0)
        self.assertTrue(any(x['ja']=='薬仙人' for x in r['results'][0]['evaluation']['automatic']))
        q.update(required=[{'skill':'豪放+1'}],forbidden=[{'skill':'薬仙人'}])
        self.assertFalse(self.s.search(q)['results'])

    def test_resistance_meal_direct(self):
        r=self.s.e.evaluate({'weapon_type':'MS','external':{'meal':'all','quality':3}})
        self.assertEqual(r['automatic'][0]['ja'],'各耐性+20')
        self.assertEqual(r['defense_stats']['adjusted']['Fire'],0)
        self.assertEqual(r['defense_stats']['external']['Fire'],20)

    def test_exotic_armor_direct_search(self):
        q=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        q['armor']['head']={'item':'ギルドバードGXハット','level':'L7','jewels':[]}
        q.update(required=[{'skill':'広域化+3'}],cuffs=[],jewel_candidates=[],limit=1,seconds=8)
        r=self.s.search(q);self.assertTrue(r['results'],r['status'])
        self.assertEqual(r['results'][0]['new_jewels'],0)
        self.assertTrue(any(x['ja']=='広域化+3' and x['source']=='equipment' for x in r['results'][0]['evaluation']['automatic']))

    def test_composite_resistance_and_blue_soul(self):
        # Isolate exact point contributions while keeping the real imported skill definitions.
        with closing(sqlite3.connect(':memory:')) as db:
            self.db.backup(db);e=Engine(db)
            eid=e.equipment('ガスラZXヘルム','head')['id']
            db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,))
            names={'炎寵':15,'火耐性':20,'喝':-10}
            db.executemany('INSERT INTO equipment_skills VALUES (?,?,?)',[(eid,e.names['normal',n],pt) for n,pt in names.items()])
            b={'weapon_type':'MS','armor':{'head':{'item':eid,'level':'L1'}},'external':{'meal':'Fire','quality':3}}
            r=e.evaluate(b);stats=r['defense_stats']
            self.assertEqual(stats['bonus']['Fire'],30)
            self.assertEqual(stats['external_bonus']['Fire'],0)
            self.assertTrue(next(x for x in r['zenith'] if x['target']=='喝')['has_base_skill'])

    def test_composite_resistance_solver(self):
        q=json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        with closing(sqlite3.connect(':memory:')) as db:
            self.db.backup(db);e=Engine(db)
            eid=e.equipment(q['armor']['head']['item'],'head')['id']
            db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,))
            db.execute('INSERT INTO equipment_skills VALUES (?,?,?)',(eid,e.names['normal','炎寵'],15))
            s=Searcher(db)
            q.update(required=[],cuffs=[],jewel_candidates=[],min_stats={'Fire':33},stat_mode='adjusted',limit=1,seconds=8)
            r=s.search(q);self.assertTrue(r['results'],r['status'])
            self.assertEqual(r['results'][0]['evaluation']['defense_stats']['adjusted']['Fire'],33)

if __name__=='__main__':unittest.main()
