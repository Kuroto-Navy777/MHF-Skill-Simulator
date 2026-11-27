"""Version information and settings regression tests (no network or user profile changes)."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_info import information, configure, discover
from desktop_safety import DesktopBridge, atomic_json, record_history, save_snapshot, checkpoint
from release_check import read_config
from test_desktop_safety import sample
from launcher import start_payload


class VersionInfoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.app = self.root / 'app'
        self.app.mkdir()
        (self.app/'VERSION').write_text('1.1.0-rc.6')
        (self.root/'MHFSimulator.exe').write_bytes(b'MZ')
        self.profile = self.root/'profile'
        atomic_json(self.root/'release_source.json', {'repository':'Kuroto-Navy777/MHF-Skill-Simulator','channel':'preview','check_on_startup':True})

    def test_versions_independent(self):
        with patch.dict(os.environ, {'MHF_RUNNING_LAUNCHER_VERSION':'1.1.0-rc.5'}):
            info = information(self.app,self.profile)
        self.assertEqual(info['app'],'1.1.0-rc.6')
        self.assertEqual(info['launcher'],'1.1.0-rc.5')
        self.assertTrue(info['portable'])

    def test_unknown_launcher_not_inferred(self):
        with patch.dict(os.environ, {'MHF_RUNNING_LAUNCHER_VERSION':'invalid'}):
            self.assertIsNone(information(self.app,self.profile)['launcher'])

    def test_config_and_repository_preservation(self):
        self.assertTrue(configure(self.app,False,'stable'))
        config=read_config(self.root)
        self.assertFalse(config['check_on_startup'])
        self.assertEqual(config['channel'],'stable')
        self.assertEqual(config['repository'],'Kuroto-Navy777/MHF-Skill-Simulator')
        with self.assertRaises(ValueError):
            configure(self.app,'false','preview')
        with self.assertRaises(ValueError):
            configure(self.app,True,'other')
        self.assertEqual(read_config(self.root),config)

    def test_history_and_checkpoint(self):
        record_history(self.profile,'launcher_installed','1.1.0-rc.6')
        record_history(self.profile,'installed','1.1.0-rc.6')
        folder=self.profile/'backups'
        save_snapshot(folder,sample())
        checkpoint(folder)
        (self.root/'.app_previous').mkdir()
        (self.root/'.app_previous'/'VERSION').write_text('1.1.0-rc.5')
        (self.root/'.launcher_previous.exe').write_bytes(b'MZ')
        info=information(self.app,self.profile)
        self.assertEqual([r['status'] for r in info['history']],['installed','launcher_installed'])
        self.assertEqual(info['backups'],1)
        for key in ('checkpoint','previous_app','previous_launcher'):
            self.assertTrue(info[key])

    def test_invalid_config_is_reported(self):
        (self.root/'release_source.json').write_text('bad')
        self.assertTrue(information(self.app,self.profile)['config_error'])

    def test_discovery_uses_actual_launcher_and_no_download(self):
        fetch=Mock(return_value={'status':'available','version':'1.1.0-rc.6','url':'https://example.invalid'})
        with patch.dict(os.environ, {'MHF_RUNNING_LAUNCHER_VERSION':'1.1.0-rc.5'}):
            result=discover(self.app,fetch)
        fetch.assert_called_once_with(self.root,launcher_current='1.1.0-rc.5')
        self.assertEqual(result,{'status':'available','version':'1.1.0-rc.6'})

    def test_bridge_origin(self):
        bridge=DesktopBridge(self.profile/'backups','http://127.0.0.1:8765/',root=self.app)
        bridge._window=Mock()
        bridge._window.get_current_url.return_value='https://example.invalid/'
        for call in (bridge.version_information,bridge.discover_updates,lambda:bridge.configure_updates(False,'stable')):
            with self.assertRaises(ValueError):call()
        bridge._window.get_current_url.return_value='http://127.0.0.1:8765/'
        self.assertEqual(bridge.version_information()['app'],'1.1.0-rc.6')
        self.assertTrue(bridge.configure_updates(False,'stable'))

    def test_running_version_passed_to_payload(self):
        child=Mock(returncode=0);child.poll.return_value=0
        with patch('launcher.subprocess.Popen',return_value=child) as spawn, patch('launcher.launcher_version',return_value='1.1.0-rc.6'):
            start_payload(self.root,self.root/'db',[],Mock(),self.profile/'WebView2',False)
        self.assertEqual(spawn.call_args.kwargs['env']['MHF_RUNNING_LAUNCHER_VERSION'],'1.1.0-rc.6')
