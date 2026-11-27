"""Regression tests for localization, sparse validation, and UI name collisions."""
import os
import re
import unittest
from pathlib import Path
import numpy as np
from search_engine import Model
from material_sources import sections
from localization import material_detail, skill_summary, sigil_reference

class Phase8GUnit(unittest.TestCase):
    def test_inline_section_header(self):
        self.assertEqual(sections('Name : {"A":"First"\n,"B":"Second"\n}'), {'Name': {'A':'First','B':'Second'}})
    def test_localized_material_preserves_probability(self):
        self.assertEqual(material_detail('Zenith★3Break Part : Wing[Zenith] - 2x (75%)'), '辿異★3部位破壊 : 翼[辿異] - 2個 (75%)')
        self.assertEqual(material_detail('Unknown - 1x (1%)'),'Unknown - 1個 (1%)')
    def test_skill_uses_only_matched_source(self):
        self.assertIsNone(skill_summary({'ja':'早食い'},None))
        self.assertEqual(skill_summary({'ja':'体力+30'},'Increases maximum health by 30.'),'最大体力を30増やす。')
        self.assertIsNone(skill_summary({'ja':'unknown'},'Unknown effect.'))
    def test_sigil_ref(self):
        self.assertEqual(sigil_reference('Tech Boost[Tonfa]','Enhances certain techniques.')[0],'穿龍棍・技強化')
        self.assertEqual(sigil_reference('Unknown','Unknown'),(None,None))
    def test_sparse_validation(self):
        m=Model();a=m.var(cost=-1);b=m.var();m.add({a:1,b:1},low=1,high=1);m.solve(1)
        self.assertTrue(m.feasible(np.array([1,0])));self.assertFalse(m.feasible(np.array([1,1])));self.assertFalse(m.feasible(np.array([-1,2])))
        m.add({a:1},high=0);self.assertFalse(m.feasible(np.array([1,0])));m.solve(1);self.assertTrue(m.feasible(np.array([0,1])))
    def test_js_helper_names(self):
        js=Path('web/app.js').read_text();self.assertEqual(len(re.findall(r'function skillLabel\(',js)),1);self.assertIn('skillHelpButton(s)',js);self.assertIn('function pickerSkillLabel(',js)
        html=Path('web/index.html').read_text();ids=re.findall(r'\bid="([^"]+)"',html);self.assertEqual(len(ids),len(set(ids)));self.assertIn('sigilBrowse',ids)

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local data needed')
class Phase8GData(unittest.TestCase):
    def test_reference_api(self):
        from fastapi.testclient import TestClient
        from web_api import create_app
        with TestClient(create_app(Path(os.environ['MHF_TEST_DB']))) as c:
            rows=c.get('/api/skill-reference').json();self.assertEqual(len(rows),523);count=sum(bool(x['description_ja']) for x in rows);print('Japanese skill descriptions:',count);self.assertGreaterEqual(count,300)
            sigils=c.get('/api/sigil-effects').json();self.assertEqual(len(sigils),130);print('Japanese sigil labels:',sum(bool(x['name_ja']) for x in sigils));self.assertTrue(any(x['name_ja']=='マグネットスパイク強化' for x in sigils))
            src=c.get('/api/material-source',params={'name':'Giaorugu Frost Gem'}).json()['sources'];self.assertTrue(any(x['name_ja']=='ギアオルグ' and '剥ぎ取り' in x['detail_ja'] for x in src))
    def test_quest_source_index(self):
        from material_sources import source_index,lookup
        from materials import archive_path
        from web_api import connect
        from contextlib import closing
        path=Path(os.environ['MHF_TEST_DB']);
        with closing(connect(path)) as db: source=archive_path(db,path.parent,'ferias')
        names,_,quests=source_index(source,source.stat().st_mtime_ns);self.assertGreater(len(quests['Name']),3000);print('Quest names:',len(quests['Name']));self.assertTrue(any(x['kind']=='quest' for name in list(names)[:200] for x in lookup(source,name)))
