"""Phase 8D regression checks using the user's locally imported data."""
import json
import os
import sqlite3
import unittest
from pathlib import Path
from search_engine import Searcher
from skill_engine import WEAPON_SECRET


@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class SearchQualityTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(os.environ['MHF_TEST_DB'])
        self.s = Searcher(self.db)
        self.req = json.loads(Path('example_search.json').read_text(encoding='utf-8'))
        self.req.update(limit=1, seconds=12)

    def tearDown(self):
        self.db.close()

    def test_zenith_dependency_and_composite(self):
        # The ordinary source skill and its composite provider must be in the focused pool.
        zid = self.s.e.names['zenith', '耳栓強化']
        targets = self.s.dependency_targets({zid})
        self.assertIn(self.s.e.names['normal', '聴覚保護'], targets)
        self.assertIn(self.s.e.names['normal', '三界の護り'], targets)

    def test_zenith_only_search(self):
        # The fixed weapon already has Vigorous Up; its ordinary prerequisite needs jewels.
        self.req['required'] = [{'skill':'血気活性強化'}]
        r = self.s.search(self.req)
        self.assertTrue(r['results'], r['status'])
        report = r['results'][0]['evaluation']
        self.assertTrue(any(s['ja']=='血気活性' and s['status']=='active' for s in report['skills']))
        self.assertTrue(any(s['ja']=='血気活性強化' and s['has_base_skill'] for s in report['zenith']))

    def test_full_pool_includes_cuffs(self):
        # Compare pool sizes with and without the wide search checkbox.
        self.req.pop('cuffs')
        self.req['jewel_candidates'] = []
        self.req['required'] = [{'skill':'巧撃'}]
        narrow = self.s.search(self.req)
        self.req['full_jewel_pool'] = True
        wide = self.s.search(self.req)
        self.assertGreater(wide['pool_counts']['cuff'], narrow['pool_counts']['cuff'])

    def test_overflow_cut(self):
        # Construct a fixed set with 14 ordinary skills, no exemptions or expansion.
        db = sqlite3.connect(':memory:')
        try:
            self.db.backup(db)
            ids = [self.s.e.equipment(a['item'],part)['id'] for part,a in self.req['armor'].items()]
            for eid in ids:
                db.execute('DELETE FROM abilities WHERE equipment_id=?',(eid,))
                db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,))
            families = sorted((sid for sid,s in self.s.e.skills.items() if sid.startswith('normal:') and s['ja'] not in WEAPON_SECRET.values() and any(x['points']>0 for x in self.s.e.levels[sid])),key=lambda x:int(x.split(':')[1]))[:14]
            points = {sid:min(x['points'] for x in self.s.e.levels[sid] if x['points']>0) for sid in families}
            db.executemany('INSERT INTO equipment_skills VALUES(?,?,?)',[(ids[0],sid,pt) for sid,pt in points.items()])
            s = Searcher(db)
            self.req.pop('weapon')
            self.req.update(cuffs=[],jewel_candidates=[],required=[{'skill':families[-1],'points':points[families[-1]]}])
            r = s.search(self.req)
            self.assertFalse(r['results'])
            self.assertEqual(r['slot_cuts'],1)
            self.assertEqual(r['status'],'model_exhausted')
        finally:
            db.close()

if __name__ == '__main__':
    unittest.main()
