"""Local API integration tests; MHF_TEST_DB points to the user's imported DB."""
import json
import os
import time
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from web_api import create_app

@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.context=TestClient(create_app(os.environ['MHF_TEST_DB']))
        self.client=self.context.__enter__()
    def tearDown(self):
        self.context.__exit__(None,None,None)
    def test_catalog(self):
        self.assertTrue(self.client.get('/api/health').json()['ready'])
        self.assertIn('MHF Skill Simulator',self.client.get('/').text)
        levels=self.client.get('/api/skills').json()
        self.assertTrue(any(s['ja']=='剛撃+6' and s['points']==50 for s in levels))
        jp=self.client.get('/api/items',params={'kind':'head','q':'フィンスZPヘッド'}).json()
        en=self.client.get('/api/items',params={'kind':'head','q':jp[0]['en']}).json()
        self.assertIn(jp[0]['id'],[r['id'] for r in en])
        self.assertTrue(self.client.get('/api/levels',params={'id':jp[0]['id']}).json())
        self.assertEqual(self.client.get('/api/items',params={'kind':'bad'}).status_code,400)
        self.assertEqual(self.client.get('/api/health',headers={'Origin':'https://example.com'}).status_code,403)
    def test_evaluate(self):
        b=json.loads(Path('example_build.json').read_text(encoding='utf-8'))
        r=self.client.post('/api/evaluate',json=b)
        self.assertEqual(r.status_code,200,r.text)
        hit=r.json();self.assertTrue(hit['evaluation']['valid']);self.assertFalse(hit['evaluation']['rain_verified'])
        self.assertTrue(any(s['ja']=='剛撃' and s['points']==53 for s in hit['evaluation']['skills']))
        self.assertTrue(hit['display']['weapon'])
    def test_multiple_search_results(self):
        req=json.loads(Path('example_search.json').read_text(encoding='utf-8'));req['limit']=2
        r=self.client.post('/api/search',json=req);self.assertEqual(r.status_code,200)
        key=r.json()['id'];deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            r=self.client.get('/api/search/'+key).json()
            if r['status']!='running':break
            time.sleep(.2)
        self.assertEqual(r['status'],'done',r)
        hits=r['result']['results'];self.assertEqual(len(hits),2,r['result']['status'])
        self.assertNotEqual(hits[0]['build'],hits[1]['build'])
        for h in hits:
            self.assertTrue(h['evaluation']['valid']);self.assertTrue(h['display']['items'])
            self.assertTrue(any(s['level_ja']=='剛撃+6' and s['status']=='active' for s in h['evaluation']['skills']))
        print('Multiple candidate search:',len(hits),'results;',r['result']['elapsed_seconds'],'seconds')
    def test_cancel(self):
        req=json.loads(Path('example_search.json').read_text(encoding='utf-8'));req['seconds']=60
        key=self.client.post('/api/search',json=req).json()['id']
        self.assertEqual(self.client.post('/api/search',json=req).status_code,409)
        self.assertEqual(self.client.delete('/api/search/'+key).json()['status'],'cancelled')
        self.assertEqual(self.client.get('/api/search/'+key).json()['status'],'cancelled')

if __name__=='__main__': unittest.main()
