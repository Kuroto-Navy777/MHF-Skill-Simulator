"""Recipe parser and real-source integration tests."""
import json
from contextlib import closing
import os
import unittest
from pathlib import Path
from lxml import html
from fastapi.testclient import TestClient
from materials import Planner, weapon_cell
from web_api import connect,create_app

class ParserTests(unittest.TestCase):
    def test_alternatives(self):
        c=html.fromstring('<td><a>Iron Ore</a>x2<br>or<br><a>Earth Crystal</a>x3</td>')
        self.assertEqual(weapon_cell(c),[[('Iron Ore',2)],[('Earth Crystal',3)]])
    def test_unknown_rejected(self):
        self.assertIsNone(weapon_cell(html.fromstring('<td>Unknown x2<br>special condition</td>')))
    def test_empty(self):
        self.assertEqual(weapon_cell(html.fromstring('<td><br></td>')),[])

@unittest.skipUnless(os.getenv('MHF_MATERIAL_DB'),'local source database and archives required')
class RealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=Path(os.environ['MHF_MATERIAL_DB']);cls.build=json.loads(Path('example_build.json').read_text())
        with TestClient(create_app(cls.path)) as c:
            r=c.post('/api/material-plan',json=cls.build); assert r.status_code==200,r.text;cls.plan=r.json()
    def test_armor_chain(self):
        body=[s for s in self.plan['steps'] if s['group']=='body']
        self.assertEqual(body[-1]['ja'],'グリディZXメイル');self.assertEqual(body[-1]['level'],'L1')
        self.assertEqual(body[-2]['ja'],'グリディZYメイル');self.assertEqual(body[-2]['level'],'L7')
        self.assertIn(('氷獰竜の冷透玉',1),[(m['ja'],m['qty']) for m in body[-1]['options'][0]['materials']])
    def test_jewel_quantities(self):
        step=next(s for s in self.plan['steps'] if s['ja']=='真磁星珠・白虎')
        self.assertEqual(step['count'],3);self.assertEqual(len(step['options'][0]['materials']),4)
    def test_weapon_chain(self):
        w=[s for s in self.plan['steps'] if s['group']=='weapon'];self.assertEqual(len(w),4)
        self.assertIn(('照雷鳥の極絶翼',3),[(m['ja'],m['qty']) for m in w[-1]['options'][0]['materials']])
    def test_refine_route(self):
        self.assertTrue(self.plan['complete'],self.plan['warnings'])
        step=next(s for s in self.plan['steps'] if s['ja']=='ラヴィ剣珠GX2')
        self.assertEqual(step['count'],2)
        self.assertEqual(step['options'][0]['source'],'ラヴィGXメイル')
        self.assertEqual(step['options'][0]['type'],'refine')
        self.assertTrue(step['options'][0]['materials'])
    def test_stable_id(self):
        with closing(connect(self.path)) as db:
            p=Planner(db,self.path.parent).plan(self.build)
        self.assertEqual(p['plan_id'],self.plan['plan_id'])
    def test_invalid_level(self):
        b=json.loads(json.dumps(self.build));b['armor']['head']['level']='L99'
        with TestClient(create_app(self.path)) as c:self.assertEqual(c.post('/api/material-plan',json=b).status_code,400)

if __name__=='__main__': unittest.main()
