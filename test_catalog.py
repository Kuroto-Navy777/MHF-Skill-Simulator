"""Phase 5B catalog regression checks against a locally imported DB."""
import os
import unittest
from fastapi.testclient import TestClient
from web_api import create_app
from catalog import armor_rank

class RankTests(unittest.TestCase):
    def test_rank(self):
        self.assertEqual(armor_rank('コリニィＺバンド','Corinyi Z Band','辿異防具'),'Z')
        self.assertEqual(armor_rank('コリニィZXバンド','Corinyi ZX Band','辿異防具'),'ZX')
        self.assertEqual(armor_rank('フィンスZPヘッド','Fins ZP Head','辿異狩護防具'),'ZP')
        self.assertEqual(armor_rank('ピエトラＧヘルム','','Ｇ級防具'),'G')
        self.assertEqual(armor_rank('ピエトラGFヘルム','','Ｇ級防具'),'GF')
        self.assertEqual(armor_rank('ピエトラGXヘルム','','Ｇ級防具'),'GX')

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.context=TestClient(create_app(os.environ['MHF_TEST_DB']))
        self.client=self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None,None,None)
    def query(self,**params):
        response=self.client.get('/api/catalog',params={'kind':'head',**params})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()
    def test_full_count_and_paging(self):
        a=self.query(hide_unavailable=False,page_size=60)
        b=self.query(hide_unavailable=False,page_size=60,page=2)
        z=self.query(hide_unavailable=False,page_size=60,page=a['pages'])
        self.assertEqual(a['total'],8988)
        self.assertEqual(len(a['items']),60)
        self.assertFalse({x['id'] for x in a['items']}&{x['id'] for x in b['items']})
        self.assertEqual(len(z['items']),8988%60)
    def test_filter_and_rank(self):
        a=self.query(q='コリニィ',rank='ZX')
        self.assertEqual(a['total'],2)
        self.assertTrue(all(x['rank']=='ZX' for x in a['items']))
        self.assertEqual(self.query(q='コリニィZバンド')['total'],1)
    def test_details_and_sort(self):
        r=self.query(q='フィンスZPヘッド')['items'][0]
        self.assertEqual(r['latest']['defense'],356)
        self.assertEqual(r['slots'],3)
        self.assertEqual(r['resistances']['Fire'],'1')
        self.assertTrue(r['skills'])
        a=self.query(sort='defense')['items']
        v=[x['latest']['defense'] for x in a if x['latest'].get('defense') is not None]
        self.assertEqual(v,sorted(v,reverse=True))
    def test_exclusion(self):
        a=self.query(hide_unavailable=True,hide_paid=True,hide_festival=True,page_size=100)
        self.assertLess(a['total'],self.query(hide_unavailable=False)['total'])
        self.assertTrue(all(not (x['class_code'] or '').startswith(('(ガ','(キ','(パ','(ネ','(祭','(未','(不')) for x in a['items']))
    def test_job_sex(self):
        a=self.query(kind='body',job='剣士',sex='男',page_size=100)
        self.assertTrue(all(x['job'] in ('剣士','共',None) and x['sex'] in ('男','共',None) for x in a['items']))
    def test_weapon_jewel_cuff(self):
        for kind in ('weapon','jewel','cuff'):
            a=self.query(kind=kind,page_size=10)
            self.assertTrue(a['total']>10)
            self.assertEqual(len(a['items']),10)
            self.assertIn('skills',a['items'][0])
    def test_zero_and_bad_parameters(self):
        self.assertEqual(self.query(q='this cannot exist 123')['total'],0)
        self.assertEqual(self.client.get('/api/catalog',params={'kind':'head','sort':'invalid'}).status_code,400)
        self.assertEqual(self.client.get('/api/catalog',params={'kind':'head','page_size':101}).status_code,422)

if __name__=='__main__': unittest.main()
