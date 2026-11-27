"""Exercise source and frozen dispatch without requiring a Windows bootloader."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from build_windows import build_command, stage_files, package
from runtime_paths import app_root, search_command
from web_api import create_app

ROOT = Path(__file__).resolve().parent


class PackagingTests(unittest.TestCase):
    def test_source_paths(self):
        self.assertEqual(app_root(), ROOT)
        args = search_command(ROOT, 'db', 'req', 'out', 'log')
        self.assertEqual(args[:2], [sys.executable, str(ROOT / 'search_engine.py')])

    def test_frozen_paths(self):
        with tempfile.TemporaryDirectory(prefix='MHF Test ') as folder:
            exe = str(Path(folder) / 'MHFSimulator.exe')
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', exe):
                self.assertEqual(app_root(), Path(folder).resolve())
                args = search_command(ROOT, 'db', 'req', 'out', 'log')
                self.assertEqual(args, [exe, '--search-worker', '--worker-log', 'log', '--db', 'db', '--request', 'req', '--out', 'out'])

    def test_build_flags(self):
        args = build_command(ROOT, ROOT / 'stage')
        for flag in ('--onedir', '--windowed', '--noupx', '--icon', 'pystray._win32', 'webview', 'pythonnet'):
            self.assertIn(flag, args)
        self.assertEqual(Path(args[args.index('--icon') + 1]).read_bytes()[:4], b'\x00\x00\x01\x00')

    def test_package_only_explicit_files(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'dist'
            target.mkdir()
            (target / 'MHFSimulator.exe').write_bytes(b'MZtest')
            stage_files(ROOT, target)
            archive = Path(folder) / 'portable.zip'
            package(target, archive)
            with zipfile.ZipFile(archive) as z:
                names = z.namelist()
                self.assertTrue(all(n.startswith('MHF_SkillSimulator/') for n in names))
                self.assertIn('MHF_SkillSimulator/web/favicon.ico', names)
                self.assertFalse(any(n.endswith('.sqlite') or n.endswith('.py') for n in names))
                self.assertIsNone(z.testzip())

    def test_worker_errors_are_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            log = base / 'worker.log'
            proc = subprocess.run([sys.executable, str(ROOT / 'desktop_entry.py'), '--search-worker',
                                  '--worker-log', str(log), '--db', str(base / 'missing.sqlite'),
                                  '--request', str(base / 'request.json'), '--out', str(base / 'out.json')],
                                  timeout=15, capture_output=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn('Traceback', log.read_text())
            self.assertFalse((base / 'out.json').exists())

    @unittest.skipUnless(os.getenv('MHF_TEST_DB') and os.name != 'nt', 'Linux executable-dispatch emulation with real DB')
    def test_frozen_dispatch_api(self):
        # Use a POSIX executable shim, not a real Windows EXE; exercise actual child search.
        with tempfile.TemporaryDirectory(prefix='MHF Test ') as folder:
            shim = Path(folder) / 'MHFSimulator.exe'
            shim.write_text(f'#!{sys.executable}\nimport sys\nsys.path.insert(0, {str(ROOT)!r})\nfrom desktop_entry import main\nraise SystemExit(main())\n')
            shim.chmod(0o755)
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(shim)):
                with TestClient(create_app(Path(os.environ['MHF_TEST_DB']))) as client:
                    payload = json.loads((ROOT / 'example_auto_search.json').read_text())
                    key = client.post('/api/search', json=payload).json()['id']
                    deadline = time.monotonic() + 45
                    while time.monotonic() < deadline:
                        status = client.get('/api/search/'+key).json()
                        if status['status'] != 'running':
                            break
                        time.sleep(.2)
                    self.assertEqual(status['status'], 'done', status)
                    self.assertTrue(status['result']['results'])
                    bad = client.post('/api/search', json={'weapon_type': 'INVALID'}).json()['id']
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        status = client.get('/api/search/'+bad).json()
                        if status['status'] != 'running':
                            break
                        time.sleep(.1)
                    self.assertEqual(status['status'], 'error', status)
                    self.assertIn('Traceback', status['detail'])


if __name__ == '__main__':
    unittest.main()
