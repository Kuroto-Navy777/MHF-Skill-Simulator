"""Regression tests for startup diagnostics and recoverable search submission."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import windows_setup as w
from web_api import create_app


class DiagnosticsTests(unittest.TestCase):
    def test_read_only_missing_db(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'VERSION').write_text('1.0.0-rc.3')
            before=set(root.iterdir())
            with patch.object(w,'dependencies_ok',return_value=True):
                result=w.doctor(root)
            self.assertFalse(result['ok'])
            self.assertFalse(result['checks']['database']['ok'])
            self.assertFalse(result['checks']['application_files']['ok'])
            self.assertEqual(set(root.iterdir()),before)

    def test_invalid_manifest_rejected(self):
        import zipfile
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'VERSION').write_text('old'); p=root/'update.zip'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('VERSION','new'); z.writestr('release_manifest.json','[]')
            with patch.object(w,'require_stopped'),self.assertRaisesRegex(ValueError,'Invalid release manifest'):
                w.apply_update(root,p)
            self.assertEqual((root/'VERSION').read_text(),'old')


class SubmissionTests(unittest.TestCase):
    # Submission validation and deduplication do not require a game database.
    def test_recover_submission(self):
        from unittest.mock import Mock
        proc=Mock();proc.poll.return_value=None
        key='a'*32
        with tempfile.TemporaryDirectory() as d, patch('web_api.subprocess.Popen',return_value=proc) as launch:
            with TestClient(create_app(Path(d)/'unused.sqlite')) as c:
                payload={'_job_id':key,'required':[]}
                self.assertEqual(c.post('/api/search',json=payload).json()['id'],key)
                self.assertEqual(c.get('/api/search/'+key).json()['status'],'running')
                self.assertEqual(c.post('/api/search',json=payload).json()['id'],key)
                self.assertEqual(launch.call_count,1)
                self.assertEqual(c.post('/api/search',json={**payload,'required':[1]}).status_code,409)
                self.assertEqual(c.post('/api/search',json={'_job_id':'../escape'}).status_code,400)
                self.assertEqual(c.post('/api/search',json={'_job_id':None}).status_code,409)
                args=launch.call_args.args[0]
                self.assertNotIn('_job_id',json.loads(Path(args[args.index('--request')+1]).read_text()))

    @unittest.skipUnless(os.getenv('MHF_TEST_DB'),'local data required')
    def test_actual_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); (root/'VERSION').write_text('1.0.0-rc.3')
            # A hard link is safe here because the diagnostics opens the DB read-only.
            os.link(os.environ['MHF_TEST_DB'],root/w.MASTER)
            for name in ('web_api.py','search_engine.py','web/index.html','web/app.js','web/style.css'):
                p=root/name;p.parent.mkdir(exist_ok=True);p.touch()
            with patch.object(w,'dependencies_ok',return_value=True):
                result=w.doctor(root)
            self.assertTrue(result['checks']['database']['ok'],result)
            self.assertEqual(result['checks']['database']['detail']['counts']['equipment'],48387)

if __name__=='__main__':unittest.main()
