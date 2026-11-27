"""Phase 7C regression tests against the locally generated DB."""
import copy
import json
import os
import sqlite3
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from web_api import create_app
from weapon_names import clean_name, japanese_name
from weapon_inventory import restrict_weapons
from search_engine import Searcher


class NameTests(unittest.TestCase):
    def test_prefix(self):
        self.assertEqual(clean_name('B718・角竜剣クリムシーザ',6327),'角竜剣クリムシーザ')
        self.assertIsNone(clean_name('FFFF・角竜剣クリムシーザ',6327))
        self.assertIsNone(clean_name('Chroma Pillar',16909))

    def test_conflict(self):
        self.assertIsNone(japanese_name(1,None,'武器甲','武器乙',None))
        self.assertEqual(japanese_name(1,'武器甲','武器乙',None,None),'武器甲')


@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB'])
        cls.db.row_factory=sqlite3.Row
        cls.searcher=Searcher(cls.db)
        cls.request=json.loads(Path('example_search.json').read_text())
        cls.selector={'weapon_type':cls.request['weapon_type'],**{k:cls.request['weapon'][k] for k in ('page','anchor')}}

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_fixed_owned(self):
        r=copy.deepcopy(self.request)
        r.update(owned_weapons=[self.selector],limit=1)
        result=self.searcher.search(r)
        self.assertTrue(result['results'],result['status'])
        self.assertEqual(result['results'][0]['build']['weapon']['anchor'],self.selector['anchor'])

    def test_unowned_fixed(self):
        r=copy.deepcopy(self.request)
        p,a=self.db.execute('SELECT page,anchor FROM ferias_variants WHERE weapon_type=? AND NOT(page=? AND anchor=?) LIMIT 1',(self.selector['weapon_type'],self.selector['page'],self.selector['anchor'])).fetchone()
        r['owned_weapons']=[{**self.selector,'page':p,'anchor':a}]
        with self.assertRaisesRegex(ValueError,'fixed weapon is not owned'):
            self.searcher.search(r)

    def test_auto_owned(self):
        r=copy.deepcopy(self.request)
        r.update(auto_weapon=True,weapon={'sigils':1},owned_weapons=[self.selector],limit=1)
        filtered=restrict_weapons(r,self.db)
        groups,_=self.searcher.weapon_groups(filtered)
        self.assertEqual(sum(len(g[2]) for g in groups),1)
        result=self.searcher.search(r)
        self.assertTrue(result['results'],result['status'])
        self.assertEqual(result['results'][0]['build']['weapon']['anchor'],self.selector['anchor'])

    def test_allowlist_intersection(self):
        r=copy.deepcopy(self.request)
        r.update(owned_weapons=[self.selector],weapon_candidates=[])
        with self.assertRaisesRegex(ValueError,'no owned weapons'):
            restrict_weapons(r,self.db)

    def test_bad_selector(self):
        r=copy.deepcopy(self.request)
        r['owned_weapons']=[{**self.selector,'anchor':'no-such-weapon'}]
        with self.assertRaisesRegex(ValueError,'unknown owned weapon'):
            restrict_weapons(r,self.db)

    def test_catalog_japanese(self):
        with TestClient(create_app(os.environ['MHF_TEST_DB'])) as client:
            data=client.get('/api/catalog',params={'kind':'weapon','weapon_type':'SnS','q':'角竜剣クリムシーザ'}).json()
            self.assertTrue(data['total'])
            r=data['items'][0]
            self.assertEqual(r['ja'],'角竜剣クリムシーザ')
            self.assertEqual(r['upstream_id'],6327)
            self.assertEqual(r['weapon_type'],'SnS')
            legacy=client.get('/api/items',params={'kind':'weapon','weapon_type':'SnS','q':'角竜剣クリムシーザ'}).json()
            self.assertTrue(legacy)

    def test_reference(self):
        with TestClient(create_app(os.environ['MHF_TEST_DB'])) as client:
            response=client.get('/api/sigil-effects')
            self.assertEqual(response.status_code,200)
            rows=response.json()
            self.assertTrue(any(x['name']=='Attack Adjustment' and x['range']=='-10～+15' for x in rows))
            print('Sigil reference effects:',len(rows))


if __name__=='__main__':
    unittest.main()
