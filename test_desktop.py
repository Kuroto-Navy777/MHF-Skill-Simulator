"""Desktop shell lifecycle and compatibility tests (native UI requires Windows)."""
import os
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.request
import json

import desktop
from windows_setup import allowed_file


class DesktopTests(unittest.TestCase):
    def test_profile_persistent_and_separate(self):
        with patch.dict(os.environ, {'LOCALAPPDATA': 'example'}):
            self.assertEqual(desktop.profile_directory(), Path('example/MHFSkillSimulator/WebView2'))

    def test_window_config(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / 'profile'
            view = Mock()
            view.settings = {}
            desktop.open_window('http://127.0.0.1:8765/', desktop.ROOT, profile, view)
            self.assertTrue(profile.is_dir())
            self.assertTrue(view.settings['ALLOW_DOWNLOADS'])
            self.assertFalse(view.settings['ALLOW_FILE_URLS'])
            self.assertFalse(view.start.call_args.kwargs['private_mode'])
            self.assertEqual(view.start.call_args.kwargs['storage_path'], str(profile))
            self.assertEqual(view.start.call_args.kwargs['gui'], 'edgechromium')

    def test_busy_port_not_reused(self):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            with self.assertRaisesRegex(RuntimeError, 'busy'):
                with desktop.local_server(Path('unused.sqlite'), sock.getsockname()[1]):
                    self.fail('Must not attach to a different service')

    def test_missing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(FileNotFoundError):
                desktop.select_database(Path(temp))

    def test_update_allowlist(self):
        for name in ('desktop.py', 'setup_desktop.bat', 'web/favicon.ico', 'DESKTOP_GUIDE.md', 'requirements_desktop.txt'):
            self.assertTrue(allowed_file(name), name)
        for name in ('mhf_master.sqlite', 'web/evil.exe', '../desktop.py'):
            self.assertFalse(allowed_file(name), name)

    @unittest.skipUnless(os.environ.get('MHF_TEST_DB'), 'local data required')
    def test_live_server_and_shutdown(self):
        path = Path(os.environ['MHF_TEST_DB'])
        with desktop.local_server(path, 0) as url:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(url + 'api/health', timeout=3) as response:
                health = json.load(response)
                self.assertTrue(health['ready'])
                self.assertTrue(health['master'])
                self.assertEqual(health['counts']['equipment'], 48387)
            with opener.open(url, timeout=3) as response:
                self.assertIn(b'/static/favicon.ico', response.read())
            with opener.open(url + 'static/favicon.ico', timeout=3) as response:
                self.assertEqual(response.read(4), b'\x00\x00\x01\x00')
        with self.assertRaises(OSError):
            opener.open(url + 'api/health', timeout=1)


if __name__ == '__main__':
    unittest.main()
