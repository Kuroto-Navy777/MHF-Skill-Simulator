"""Live-preview integration: actual database and independently evaluated candidates."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from contextlib import closing
from search_engine import Searcher, main
from fastapi.testclient import TestClient
from web_api import create_app


@unittest.skipUnless(os.getenv('MHF_TEST_DB'), 'MHF_TEST_DB required')
class LiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(os.environ['MHF_TEST_DB'])
        self.req = json.loads(Path('example_search.json').read_text())

    def test_empty_requirements_only_allowed_for_live_preview(self):
        with closing(sqlite3.connect(self.db)) as db:
            searcher = Searcher(db)
            req = {**self.req, 'required': [], 'limit': 2, 'seconds': 5}
            with self.assertRaisesRegex(ValueError, 'required must not be empty'):
                searcher.search(req)
            hits = searcher.search({**req, 'live_preview': True})['results']
            self.assertTrue(hits)
            self.assertTrue(all(h['evaluation']['valid'] for h in hits))

    def test_progress_published_after_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = Path(tmp)/'request.json'
            out = Path(tmp)/'job.out'
            req.write_text(json.dumps({**self.req, 'live_preview': True, 'limit': 2}))
            main(['--db', str(self.db), '--request', str(req), '--out', str(out)])
            partial = json.loads(out.with_suffix('.progress').read_text())
            final = json.loads(out.read_text())
            self.assertEqual(partial['status'], 'live_partial')
            self.assertFalse(partial['complete_game_search'])
            self.assertTrue(partial['results'])
            self.assertTrue(all(h['evaluation']['valid'] for h in partial['results']))
            self.assertEqual(len(final['results']), 2)
            self.assertFalse(out.with_suffix('.progress.tmp').exists())

    def test_worker_status_and_cancel_with_live_preview(self):
        with TestClient(create_app(self.db)) as client:
            req = {**self.req, 'live_preview': True, 'seconds': 10, 'limit': 2}
            r = client.post('/api/search', json=req)
            self.assertEqual(r.status_code, 200)
            key = r.json()['id']
            self.assertEqual(client.delete('/api/search/'+key).status_code, 200)
            self.assertIn(client.get('/api/search/'+key).json()['status'], ('cancelled','done'))
            self.assertEqual(client.post('/api/search', json=req).status_code, 200)
