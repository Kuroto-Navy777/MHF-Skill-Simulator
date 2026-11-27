"""Tests use local DB supplied by the user; no upstream data is bundled."""
import os
import sqlite3
import unittest
from skill_engine import Engine, reached, PARTS

class ThresholdTests(unittest.TestCase):
    def test_signed_thresholds(self):
        levels=[{'points':p} for p in (-20,-10,10,15,30)]
        for total,expected in [(-40,-20),(-11,-10),(-9,None),(0,None),(9,None),(10,10),(29,15),(30,30)]:
            with self.subTest(total=total):
                self.assertEqual((reached(levels,total) or {}).get('points'),expected)

@unittest.skipUnless(os.environ.get('MHF_TEST_DB'),'set MHF_TEST_DB to test imported local data')
class ImportedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.e=Engine(cls.db)
    @classmethod
    def tearDownClass(cls): cls.db.close()
    def base(self): return {'weapon_type':'MS','g_poogie':True,'premium_poogie_clothes':True}
    def skill(self,r,name): return next(x for x in r['skills'] if x['ja']==name)
    def test_secret_cuff(self):
        b=self.base();b.update(armor={'body':{'item':'グリディZXメイル','level':'L1','jewels':['真磁星珠・白虎']*3}},cuffs=['磁星カフ・剛撃','猛進強化カフPZ２'])
        r=self.e.evaluate(b);self.assertTrue(r['valid']);s=self.skill(r,'磁斬鎚技');self.assertEqual((s['points'],s['slot_cost'],s['status']),(30,0,'active'));self.assertEqual(r['slots']['cuff_used'],2)
    def test_cuff_count(self):
        b=self.base();b['cuffs']=['磁星カフ・剛撃']*2;self.assertFalse(self.e.evaluate(b)['valid'])
    def test_armor_overflow(self):
        b=self.base();b['armor']={'body':{'item':'グリディZXメイル','level':'L1','jewels':['真磁星珠・白虎']*4}};self.assertFalse(self.e.evaluate(b)['valid'])
    def test_invalid_level(self):
        b=self.base();b['armor']={'head':{'item':'フィンスZPヘッド','level':'L7'}}
        with self.assertRaises(ValueError):self.e.evaluate(b)
    def test_shared_weapon(self):
        b=self.base();b['weapon']={'page':'buki/magspike.htm','anchor':'l4244','jewels':['真磁星珠・白虎']*2,'sigils':2};self.assertFalse(self.e.evaluate(b)['valid'])
        b['weapon']['sigils']=1;r=self.e.evaluate(b);self.assertTrue(r['valid']);self.assertEqual(r['zenith'][0]['ja'],'血気活性強化');self.assertFalse(r['zenith'][0]['has_base_skill'])
    def test_zenith_cap(self):
        b=self.base();b['armor']={p:{'item':n,'level':'L1'} for p,n in zip(PARTS,['フィンスZPヘッド','グリディZXメイル','バルラZXアーム','グラビZXコイル','プリブZPフット'])};r=self.e.evaluate(b);self.assertEqual(r['slots']['capacity'],16)
    def test_priority_and_overlap(self):
        # A temporary local copy of the evaluator's data allows isolated threshold/priority assertions.
        db=sqlite3.connect(':memory:');self.db.backup(db);e=Engine(db)
        sid=e.names[('normal','不退')]; i=e.names[('normal','一閃')]; g=e.names[('normal','剛撃')];
        eid=e.equipment('グリディZXメイル','body')['id'];db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,));db.executemany('INSERT INTO equipment_skills VALUES(?,?,?)',[(eid,sid,10),(eid,i,30),(eid,g,50)])
        b=self.base();b['armor']={'body':{'item':eid,'level':'L1'}};r=e.evaluate(b);self.assertEqual(self.skill(r,'一閃')['status'],'overlap');self.assertEqual(self.skill(r,'一閃')['slot_cost'],1);self.assertEqual(self.skill(r,'剛撃')['status'],'active');db.close()
    def test_priority_overflow(self):
        db=sqlite3.connect(':memory:');self.db.backup(db);e=Engine(db)
        eid=e.equipment('グリディZXメイル','body')['id'];db.execute('DELETE FROM equipment_skills WHERE equipment_id=?',(eid,))
        # Choose 15 non-secret skill trees; intentionally assign the lowest priority high points.
        ids=sorted(k for k in e.skills if k.startswith('normal:') and int(k.split(':')[1])>=160)[:15]
        db.executemany('INSERT INTO equipment_skills VALUES(?,?,?)',[(eid,sid,max(x['points'] for x in e.levels[sid])+i) for i,sid in enumerate(ids)])
        b=self.base();b['armor']={'body':{'item':eid,'level':'L1'}};r=e.evaluate(b)
        self.assertEqual(r['slots']['used'],10)
        self.assertEqual([x['id'] for x in r['skills'] if x['status']=='overflow'],ids[10:]);db.close()
    def test_protection(self):
        db=sqlite3.connect(':memory:');self.db.backup(db);e=Engine(db);eid=e.equipment('グリディZXメイル','body')['id'];sid=e.names[('normal','三界の護り')];db.execute('INSERT INTO equipment_skills VALUES(?,?,?)',(eid,sid,20));b=self.base();b['armor']={'body':{'item':eid,'level':'L1'}};b['weapon']={'template':'辿異武器(耳栓強化)','slots':3,'slot_mode':'shared'};r=e.evaluate(b);self.assertTrue(r['protection'][0]['super_protection']);db.close()

if __name__=='__main__': unittest.main()
