"""Actual loopback API uses the same witness pool without launching a solver on queries."""
import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from search_engine import Searcher
from web_api import create_app

F=json.loads((Path(__file__).parent/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))


@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Api120Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=sqlite3.connect(os.environ['MHF_TEST_DB']);cls.s=Searcher(cls.db)

    @classmethod
    def tearDownClass(cls):cls.db.close()

    def request(self):
        q=copy.deepcopy(F['road15']['build']);q.pop('cuffs')
        for a in q['armor'].values():a['jewels']=[]
        q.update(required=F['road15']['required'],optional=[],forbidden=[],seconds=8,limit=1,live_preview=True)
        return q

    def test_probe_witness_query_is_immediate_and_does_not_spawn_solver(self):
        q=self.request();build=F['road-earplug']['build'];report=self.s.e.evaluate(build)
        with tempfile.TemporaryDirectory() as d,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(d)/'cache.json')) as c:
            c.app.state.candidates.ingest(q,{'results':[{'status':'found','witness':{'build':build,'evaluation':report,'new_jewels':15}}]})
            q['required']=q['required']+[{'skill':'耳栓強化+1'}]
            with patch('web_api.subprocess.Popen',side_effect=AssertionError('Indexed query must not launch solver')):
                response=c.post('/api/candidates/query',json={'request':q,'targets':[{'skill':'耳栓強化+1'}],'display_limit':1})
            self.assertEqual(response.status_code,200,response.text)
            result=response.json();self.assertEqual(result['status'],'confirmed');self.assertTrue(result['results'])
            self.assertEqual(result['results'][0]['evaluation'],c.post('/api/evaluate',json=build).json()['evaluation'])

    def test_internal_counts_and_lazy_variants_are_separate_from_display_limit(self):
        q=self.request();q.pop('live_preview');q['limit']=12;q['required']=q['required'][:4]
        result=self.s.search(q);self.assertEqual(len(result['results']),12)
        with tempfile.TemporaryDirectory() as d,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(d)/'cache.json')) as c:
            c.app.state.candidates.ingest(q,result)
            cached=c.post('/api/candidates/query',json={'request':q,'display_limit':1}).json()
            self.assertEqual(len(cached['results']),1)
            self.assertGreaterEqual(cached['confirmed_builds'],12)
            self.assertEqual(cached['distinct_armor'],1)
            h=cached['results'][0];self.assertGreaterEqual(h['variant_count'],12)
            variants=c.post('/api/candidates/variants',json={'request':q,'armor':{p:a['item'] for p,a in h['build']['armor'].items()},'exclude':h['build']}).json()
            self.assertTrue(variants['results']);self.assertLessEqual(len(variants['results']),8)
            for variant in variants['results']:self.assertTrue(self.s.e.evaluate(variant['build'])['valid'])

    def test_db_change_invalidates_reservoir_and_inflight_job(self):
        with tempfile.TemporaryDirectory() as d:
            db_path=Path(d)/'private.sqlite';shutil.copy2(os.environ['MHF_TEST_DB'],db_path)
            q=self.request();proc=Mock();proc.poll.return_value=None
            with TestClient(create_app(db_path,candidate_cache_path=Path(d)/'cache.json')) as c:
                b=F['road15']['build'];r=self.s.e.evaluate(b)
                c.app.state.candidates.ingest(q,{'results':[{'build':b,'evaluation':r,'new_jewels':15}]})
                first=c.post('/api/candidates/query',json={'request':q}).json()
                self.assertTrue(first['results'])
                with patch('web_api.subprocess.Popen',return_value=proc),patch('web_api.attach_worker',return_value=None):
                    key=c.post('/api/search',json=q).json()['id']
                    with sqlite3.connect(db_path) as changed:changed.execute('PRAGMA user_version=120')
                    changed.close()
                    stamp=db_path.stat().st_mtime_ns;os.utime(db_path,ns=(stamp+10000000,stamp+10000000))
                    status=c.get('/api/search/'+key).json()
                    self.assertEqual(status['status'],'error');self.assertIn('Database changed',status['detail'])
                    second=c.post('/api/candidates/query',json={'request':q}).json()
                    self.assertNotEqual(first['database_identity'],second['database_identity'])
                    self.assertFalse(second['results'])
                    proc.terminate.assert_called()


if __name__=='__main__':unittest.main()
