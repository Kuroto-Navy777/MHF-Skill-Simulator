"""Round-trip build exchange tests using the real local database."""
import json
import os
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from web_api import create_app

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class SharingTests(unittest.TestCase):
    def setUp(self):
        self.context=TestClient(create_app(os.environ['MHF_TEST_DB']))
        self.client=self.context.__enter__()
        self.build=json.loads(Path('example_build.json').read_text(encoding='utf-8'))
    def tearDown(self): self.context.__exit__(None,None,None)
    def export(self,fmt='json',b=None):
        r=self.client.post('/api/share/export',json={'format':fmt,'build':self.build if b is None else b})
        self.assertEqual(r.status_code,200,r.text);return r.json()['text']
    def read(self,text,fmt='json',ctx=None):
        return self.client.post('/api/share/import',json={'text':text,'format':fmt,'context':ctx})
    def test_json_roundtrip(self):
        text=self.export();doc=json.loads(text)
        self.assertEqual(set(doc),{'format','version','baseline','build'})
        r=self.read(text);self.assertEqual(r.status_code,200,r.text)
        h=r.json();self.assertEqual(h['build'],doc['build']);self.assertTrue(h['evaluation']['valid'])
        self.assertEqual(next(s['points'] for s in h['evaluation']['skills'] if s['ja']=='剛撃'),53)
    def test_legacy_json_ignores_forged_points(self):
        self.build['evaluation']={'valid':True,'skills':[{'points':9999}]}
        r=self.read(json.dumps(self.build));self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn('evaluation',r.json()['build']);self.assertEqual(r.json()['evaluation']['slots']['capacity'],16)
    def test_clip_roundtrip_with_context(self):
        text=self.export('clip');r=self.read(text,'clip',self.build);self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(r.json()['build'],json.loads(self.export())['build']);self.assertTrue(r.json()['import_warnings'])
    def test_clip_no_weapon(self):
        self.build.pop('weapon');text=self.export('clip');r=self.read(text,'clip',self.build)
        self.assertEqual(r.status_code,200,r.text);self.assertNotIn('weapon',r.json()['build'])
    def test_clip_requires_weapon(self):
        text=self.export('clip');self.build.pop('weapon');self.assertEqual(self.read(text,'clip',self.build).status_code,400)
    def test_bad_data(self):
        for text in ['{','[]','{"format":"mhf-skill-build","version":2}', 'x'*100001]:
            self.assertEqual(self.read(text).status_code,400)
        self.build['armor']['head']['item']='not real';self.assertEqual(self.read(json.dumps(self.build)).status_code,400)
    def test_slots_and_level(self):
        self.build['weapon']['sigils']=3;self.assertEqual(self.read(json.dumps(self.build)).status_code,400)
        self.build['weapon']['sigils']=1;self.build['armor']['head']['level']='L99';self.assertEqual(self.read(json.dumps(self.build)).status_code,400)
    def test_partial_clip_refused(self):
        self.build['armor'].pop('head');self.assertEqual(self.client.post('/api/share/export',json={'format':'clip','build':self.build}).status_code,400)
    def test_public_mhsx_style(self):
        text=self.export('clip').replace('  Lv1','　　　　 (辿ZX)　　Lv1').replace('剣士(男)','剣士（男）').replace('Pスロット２','Ｐスロット２')
        r=self.read(text,'clip',self.build);self.assertEqual(r.status_code,200,r.text)

if __name__=='__main__': unittest.main()
