"""Phase 8F regression coverage against imported local source archives."""
import json
import os
from pathlib import Path
from contextlib import closing
import unittest
from fastapi.testclient import TestClient
from search_engine import Model,Searcher
from web_api import create_app,connect

class SparseModelTests(unittest.TestCase):
    def test_appended_cuts_and_new_variables(self):
        m=Model();a=m.var(cost=-1);b=m.var(cost=-2);m.add({a:1,b:1},high=1)
        self.assertEqual(list(m.solve(2).x),[0,1]);m.add({b:1},high=0)
        self.assertEqual(list(m.solve(2).x),[1,0]);c=m.var(cost=-3);m.add({a:1,c:1},high=1)
        self.assertEqual(list(m.solve(2).x),[0,0,1])

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local source DB required')
class Phase8FTests(unittest.TestCase):
    def setUp(self):
        self.path=Path(os.environ['MHF_TEST_DB']);self.ctx=TestClient(create_app(self.path));self.client=self.ctx.__enter__()
    def tearDown(self):self.ctx.__exit__(None,None,None)
    def test_skill_details(self):
        rows=self.client.get('/api/skill-reference').json();self.assertEqual(len(rows),523)
        for name in ['剛撃+6','不退ノ構','巧撃','磁斬鎚技【磁星】','猛進強化']:
            self.assertTrue(next(x for x in rows if x['ja']==name)['description_ja'])
        self.assertIn('200',next(x for x in rows if x['ja']=='剛撃+6')['description_ja'])
        print('Japanese descriptions',sum(bool(x['description_ja']) for x in rows))
    def test_weapon_local_names(self):
        for wt, name in [('MS','トリド・ウジ'),('SnS','極神剣ガラティーン'),('MS','ファントムディバイン')]:
            r=self.client.get('/api/catalog',params={'kind':'weapon','weapon_type':wt,'q':name}).json()
            self.assertTrue(any(x['ja']==name for x in r['items']),name)
    def test_material_lookup(self):
        r=self.client.get('/api/material-source',params={'name':'Giaorugu Frost Gem'}).json()
        self.assertTrue(any(x['name']=='Giaorugu' and 'Carve' in x['detail'] for x in r['sources']))
        self.assertEqual(self.client.get('/api/material-source',params={'name':'does-not-exist'}).json()['sources'],[])
    def test_dedupe_equivalence(self):
        with closing(connect(self.path)) as db:
            s=Searcher(db);b=json.loads(Path('example_build.json').read_text());r=s.e.evaluate(b)
            self.assertEqual(s.effect_key(b,r),s.effect_key(b,r))
            altered=json.loads(json.dumps(r));altered['skills'][0]['points']+=1
            self.assertNotEqual(s.effect_key(b,r),s.effect_key(b,altered))
            req=json.loads(Path('example_search.json').read_text());req.update(dedupe_effects=True,limit=2,seconds=12)
            hits=s.search(req)['results'];self.assertTrue(hits)
            self.assertEqual(len({s.effect_key(h['build'],h['evaluation']) for h in hits}),len(hits))
    def test_refine_count(self):
        b=json.loads(Path('example_build.json').read_text());r=self.client.post('/api/material-plan',json=b).json()
        self.assertTrue(r['complete']);self.assertEqual(sum(x['count'] for x in r['steps'] if x['ja'].startswith('ラヴィ')),5)
        self.assertTrue(all(x['options'][0]['type']=='refine' for x in r['steps'] if x['ja'].startswith('ラヴィ')))
