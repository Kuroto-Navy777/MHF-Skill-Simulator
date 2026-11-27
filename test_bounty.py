"""Source rule and real database integration checks for Phase 7A."""
import os
import sqlite3
import unittest
from bounty import GROUPS, rules, item_allowed, weapon_allowed, public_rules
from search_engine import Searcher
from fastapi.testclient import TestClient
from web_api import create_app

def preset(group,n,mode='solo'):
    return {'group':group,'number':n,'mode':mode}

class RuleTests(unittest.TestCase):
    def test_all_presets(self):
        for group,nums in GROUPS.items():
            for n in nums:
                for mode in ('solo','multi'):
                    self.assertTrue(public_rules(preset(group,n,mode))['partial'])
        with self.assertRaises(ValueError):rules(preset('Silver',21))
    def test_bronze_exception(self):
        self.assertTrue(rules(preset('Bronze',20))['no_secret'])
        self.assertFalse(rules(preset('Bronze',21))['no_secret'])
    def test_silver_boundaries(self):
        a,b,c=[rules(preset('Silver',n)) for n in (8,9,18)]
        self.assertEqual(a['cuff'],'g');self.assertEqual(b['armor_prefix'],'コリニィ');self.assertEqual(b['max_rarity'],11)
        self.assertNotIn('tower',b['weapon_allow']);self.assertIn('tower',c['weapon_allow'])
    def test_gold_boundaries(self):
        self.assertEqual(rules(preset('Gold',10))['armor_ranks'],['Z'])
        self.assertNotIn('ZP',rules(preset('Gold',11))['armor_ranks'])
        self.assertIn('MS',rules(preset('Gold',18))['weapon_types_deny'])
        self.assertNotIn('MS',rules(preset('Gold',21))['weapon_types_deny'])
    def test_mode(self):
        self.assertNotIn('MS',rules(preset('ABYSS',22))['weapon_types_deny'])
        self.assertIn('MS',rules(preset('ABYSS',22,'multi'))['weapon_types_deny'])
        self.assertEqual(rules(preset('Event',3,'multi'))['cuff'],'none')
        self.assertTrue(rules(preset('Event',9))['no_sigils'])

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)
    @classmethod
    def tearDownClass(cls):cls.db.close()
    def test_real_filters(self):
        r=rules(preset('Silver',9));s=self.s
        self.assertTrue(item_allowed(s.e.equipment('コリニィZXバンド','head'),r))
        self.assertFalse(item_allowed(s.e.equipment('フィンスZPヘッド','head'),r))
        self.assertFalse(weapon_allowed({'category':'zenith','rarity':12},r))
        self.assertTrue(weapon_allowed({'category':'zenith','rarity':11},r))
        self.assertFalse(weapon_allowed({'category':'tower','rarity':11},r))
    def test_banned_required_and_weapon(self):
        req={'weapon_type':'MS','required':[{'skill':'剛撃+6'}],'auto_weapon':True,'bounty':preset('Bronze',1)}
        with self.assertRaisesRegex(ValueError,'weapon type prohibited'):self.s.search(req)
        req.update(weapon_type='Tonfas',required=[{'skill':'不退ノ構'}])
        with self.assertRaisesRegex(ValueError,'required skill prohibited'):self.s.search(req)
    def test_silver_search(self):
        req={'weapon_type':'Tonfas','sex':'男','g_poogie':True,'premium_poogie_clothes':True,'required':[{'skill':'剛撃+3'}],'auto_weapon':True,'weapon_filters':{'max_rarity':11},'bounty':preset('Silver',9),'limit':1,'seconds':12,'weapon_group_limit':2}
        result=self.s.search(req);self.assertTrue(result['results'],result)
        h=result['results'][0];r=rules(req['bounty']);self.assertEqual(h['evaluation']['bounty']['number'],9)
        for part,a in h['build']['armor'].items():self.assertTrue(item_allowed(self.s.e.equipment(a['item'],part),r))
        self.assertFalse(any(x['ja']=='不退' and x['threshold'] and x['threshold']>0 for x in h['evaluation']['skills']))
        w=h['build']['weapon'];row=self.db.execute('SELECT * FROM ferias_variants WHERE weapon_type=? AND page=? AND anchor=?',('Tonfas',w['page'],w['anchor'])).fetchone();self.assertTrue(weapon_allowed(row,r))
    def test_api(self):
        with TestClient(create_app(os.environ['MHF_TEST_DB'])) as c:
            self.assertEqual(c.get('/api/bounties').json()['groups']['ABYSS'],[22,23,24]);self.assertEqual(c.get('/api/bounty',params={'group':'Silver','number':9}).json()['max_rarity'],11)
            self.assertEqual(c.get('/api/bounty',params={'group':'Silver','number':21}).status_code,400)

if __name__=='__main__':unittest.main()
