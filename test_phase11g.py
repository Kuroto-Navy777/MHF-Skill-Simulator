"""Regression checks for desktop resource management."""
import logging
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient
from desktop_lifecycle import Preferences
from worker_control import creation_flags, attach_worker, release_job, stop_worker
from update_progress import StageHandler, with_progress
from web_api import create_app

class PerformanceTests(unittest.TestCase):
    def test_preferences_migration(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'settings.json'
            p.write_text('{"resident":true}')
            pref = Preferences(p)
            self.assertTrue(pref.resident)
            self.assertTrue(pref.game_priority)
            pref.set_game_priority(False)
            pref.set_resident(False)
            self.assertFalse(Preferences(p).game_priority)
            self.assertFalse(Preferences(p).resident)

    def test_priority_flags(self):
        with patch('worker_control.os.name', 'nt'), patch.object(subprocess, 'CREATE_NO_WINDOW', 0x08000000, create=True), patch.object(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0x4000, create=True):
            self.assertEqual(creation_flags(True), 0x08004000)
            self.assertEqual(creation_flags(False), 0x08000000)

    def test_worker_release_idempotent(self):
        guard = Mock()
        job = {'guard': guard}
        release_job(job)
        release_job(job)
        guard.close.assert_called_once()

    def test_stop_worker_timeout_fallback(self):
        proc = Mock()
        proc.poll.return_value = None
        proc.wait.side_effect = [subprocess.TimeoutExpired('solver', 2), 0]
        guard = Mock()
        stop_worker({'process':proc,'guard':guard}, graceful=True)
        proc.terminate.assert_called_once()
        proc.kill.assert_called_once()
        guard.close.assert_called_once()

    def test_worker_cleanup_on_shutdown(self):
        proc = Mock()
        proc.poll.return_value = None
        guard = Mock()
        with patch('web_api.subprocess.Popen', return_value=proc), patch('web_api.attach_worker', return_value=guard), patch('web_api.creation_flags', return_value=0) as flags:
            with TestClient(create_app('unused.sqlite', game_priority=lambda: True)) as c:
                self.assertEqual(c.post('/api/search', json={}).status_code, 200)
                flags.assert_called_once_with(True)
            proc.kill.assert_called_once()
            guard.close.assert_called_once()

    def test_finished_job_releases_guard(self):
        proc = Mock()
        proc.poll.return_value = None
        guard = Mock()
        with patch('web_api.subprocess.Popen', return_value=proc), patch('web_api.attach_worker', return_value=guard):
            with TestClient(create_app('unused.sqlite')) as c:
                key = c.post('/api/search', json={}).json()['id']
                proc.poll.return_value = 1
                self.assertEqual(c.get('/api/search/'+key).json()['status'],'error')
                c.get('/api/search/'+key)
            guard.close.assert_called_once()

    def test_health_invalidates_on_database_removal(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'test.sqlite'
            with sqlite3.connect(p) as db:
                for table in ('equipment','skills','ferias_weapons'):
                    db.execute(f'CREATE TABLE {table}(id INTEGER)')
                    db.execute(f'INSERT INTO {table} VALUES (1)')
            db.close()  # sqlite context commits; explicitly release the Windows file handle.
            with TestClient(create_app(p)) as c:
                self.assertTrue(c.get('/api/health').json()['ready'])
                with patch('web_api.connect', side_effect=AssertionError('should use cached health')):
                    self.assertTrue(c.get('/api/health').json()['ready'])
                p.unlink()
                self.assertFalse(c.get('/api/health').json()['ready'])

    def test_progress_without_gui_executes_once(self):
        fn = Mock(return_value='delta')
        with patch.dict('sys.modules', {'tkinter': None}):
            self.assertEqual(with_progress(fn, 123, x=5), 'delta')
        fn.assert_called_once_with(123, x=5)

    def test_progress_stage_handler(self):
        messages=queue.SimpleQueue()
        handler=StageHandler(messages)
        handler.emit(logging.LogRecord('launcher',20,'',0,'Update: downloading delta',(),None))
        self.assertIn('差分',messages.get_nowait())
        handler.emit(logging.LogRecord('launcher',20,'',0,'unrelated',(),None))
        self.assertTrue(messages.empty())

    @unittest.skipUnless(os.name == 'nt', 'Windows Job Object integration')
    def test_native_job_terminates_child(self):
        import sys
        proc=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
        try:
            guard=attach_worker(proc)
            if guard is None:
                self.skipTest('Host disallows job assignment')
            guard.close()
            proc.wait(timeout=5)
            self.assertIsNotNone(proc.returncode)
        finally:
            if proc.poll() is None:
                proc.kill(); proc.wait()

if __name__ == '__main__':
    unittest.main()
