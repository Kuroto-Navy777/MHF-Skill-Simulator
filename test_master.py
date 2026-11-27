"""Check master parity, offline operation, and migration safety on user-generated data."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from fastapi.testclient import TestClient
from build_master import migrate
from master_data import manifest, equipment_recipe, recipe_node
from web_api import create_app, connect


class MasterUnit(unittest.TestCase):
    def test_recipe_projection(self):
        from xml.etree import ElementTree as ET
        original=ET.fromstring('<Data Name="A" Type="Ｇ級防具" Class="(GX)"><Source Level="7">B</Source><Sources><Source Type="Body">C</Source></Sources><Level><L1><Cost Type="create"><Item Num="2">D</Item></Cost></L1></Level></Data>')
        data=equipment_recipe(original)
        self.assertEqual(equipment_recipe(recipe_node(data)),data)

    def test_existing_destination_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'master.sqlite';out.write_bytes(b'keep me')
            with self.assertRaises(ValueError):migrate(Path(temp)/'not-there.sqlite',out)
            self.assertEqual(out.read_bytes(),b'keep me')


@unittest.skipUnless(os.getenv('MHF_MASTER_DB') and os.getenv('MHF_LEGACY_DB'),'both local databases required')
class MasterParity(unittest.TestCase):
    def setUp(self):
        self.master=Path(os.environ['MHF_MASTER_DB']);self.legacy=Path(os.environ['MHF_LEGACY_DB'])
        self.build=json.loads(Path('example_build.json').read_text(encoding='utf-8'))

    def test_integrity_and_counts(self):
        with closing(connect(self.master)) as db, closing(connect(self.legacy)) as base:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertIsNone(db.execute('PRAGMA foreign_key_check').fetchone())
            m=manifest(db);self.assertEqual(m['version'],1)
            for name,n in m['counts'].items():
                self.assertEqual(db.execute(f'SELECT count(*) FROM {name}').fetchone()[0],n)
                if not name.startswith('master_'):
                    self.assertEqual(base.execute(f'SELECT count(*) FROM {name}').fetchone()[0],n)

    def test_offline_parity(self):
        # Any unexpected runtime archive access fails the test, even if an archive is present.
        with TestClient(create_app(self.legacy)) as old:
            paths=['/api/skill-reference','/api/sigil-effects','/api/material-source?name=Giaorugu%20Frost%20Gem','/api/catalog?kind=weapon&weapon_type=MS&q=トリド・ウジ','/api/bounties','/api/bounty?group=Silver&number=9']
            expected=[old.get(p).json() for p in paths]
            plan=old.post('/api/material-plan',json=self.build).json()
            evaluate=old.post('/api/evaluate',json=self.build).json()
            self.assertTrue(plan['complete'],plan)
        with patch('materials.archive_path',side_effect=AssertionError('Unexpected ZIP access')),patch('zipfile.ZipFile',side_effect=AssertionError('Unexpected ZIP access')):
            with TestClient(create_app(self.master)) as new:
                self.assertTrue(new.get('/api/health').json()['master'])
                self.assertFalse(new.get('/api/master').json()['legacy'])
                for path,result in zip(paths,expected):self.assertEqual(new.get(path).json(),result,path)
                self.assertEqual(new.post('/api/material-plan',json=self.build).json(),plan)
                self.assertEqual(new.post('/api/evaluate',json=self.build).json(),evaluate)

    def test_missing_archives_no_output(self):
        with tempfile.TemporaryDirectory() as temp:
            out=Path(temp)/'master.sqlite'
            with self.assertRaises(ValueError):migrate(self.legacy,out,temp)
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(temp).iterdir()),[])

if __name__=='__main__':unittest.main()
