import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from desktop_safety import DesktopBridge, checkpoint, read_json, save_snapshot, snapshots, atomic_json, record_history
from launcher import prepare, wait_for_ready, start_payload, manual_rollback
from update_core import install, recover, REPOSITORY


def sample(n=1):
    return json.dumps({'format':'mhf-skill-backup','version':1,'data':{
        'favorites': [], 'profiles': [], 'inventory': {}, 'collection': {'weapons': [], 'sigils': []},
        'materials': {'stock': {'ja:素材': n}, 'plans': {}}, 'lang':'ja','theme':'dark'}})


class SafetyTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.profile = self.root / 'profile' / 'WebView2'
        self.folder = self.profile.parent / 'backups'

    def test_snapshot_rotation_and_checkpoint(self):
        first = save_snapshot(self.folder, sample())
        self.assertEqual(first, save_snapshot(self.folder, sample()))
        self.assertTrue(checkpoint(self.folder))
        for i in range(2, 9):
            save_snapshot(self.folder, sample(i))
        self.assertEqual(len(snapshots(self.folder)), 5)
        self.assertEqual(read_json(self.folder/'before-update.json')['data']['materials']['stock']['ja:素材'], 1)
        self.assertTrue(checkpoint(self.folder))
        self.assertEqual(read_json(self.folder/'before-update.json')['data']['materials']['stock']['ja:素材'], 8)

    def test_corrupt_newest_checkpoint_falls_back(self):
        save_snapshot(self.folder, sample(1))
        newest = save_snapshot(self.folder, sample(2))
        newest.write_text('bad')
        self.assertTrue(checkpoint(self.folder))
        self.assertEqual(read_json(self.folder/'before-update.json')['data']['materials']['stock']['ja:素材'], 1)

    def test_invalid_snapshot_does_not_replace_previous(self):
        target = save_snapshot(self.folder, sample())
        with self.assertRaises(ValueError):
            save_snapshot(self.folder, '{}')
        self.assertEqual(len(snapshots(self.folder)), 1)
        self.assertTrue(target.is_file())

    def test_bridge_origin_and_ready(self):
        report = self.root / 'ready.json'
        bridge = DesktopBridge(self.folder, 'http://127.0.0.1:8765/', report)
        bridge._window = Mock()
        bridge._window.get_current_url.return_value = 'https://example.org/'
        with self.assertRaises(ValueError):
            bridge.save_backup(sample())
        with self.assertRaises(ValueError):
            bridge.startup_ready()
        self.assertFalse(report.exists())
        bridge._window.get_current_url.return_value = 'http://127.0.0.1:8765/'
        self.assertTrue(bridge.save_backup(sample()))
        self.assertTrue(bridge.startup_ready())
        self.assertEqual(read_json(report), {'ready': True})

    def make_payloads(self):
        app = self.root/'app'; app.mkdir()
        (app/'VERSION').write_text('1.1.0-alpha.6')
        staged = self.root/'staged'; staged.mkdir()
        (staged/'VERSION').write_text('1.1.0-alpha.7')
        (self.root/'mhf_master.sqlite').write_bytes(b'database')
        install(self.root, staged, Mock(), defer_commit=True)
        return app

    def test_interrupted_deferred_commit(self):
        app = self.make_payloads()
        self.assertTrue((self.root/'.update_pending').exists())
        recover(self.root)
        self.assertEqual((app/'VERSION').read_text(), '1.1.0-alpha.6')
        self.assertEqual((self.root/'mhf_master.sqlite').read_bytes(), b'database')

    def test_ready_commit(self):
        app = self.make_payloads()
        child = Mock(returncode=0); child.poll.return_value = 0
        with patch('launcher.subprocess.Popen', return_value=child), patch('launcher.wait_for_ready', return_value=True):
            start_payload(self.root, self.root/'mhf_master.sqlite', [], Mock(), self.profile, True)
        self.assertFalse((self.root/'.update_pending').exists())
        self.assertEqual((app/'VERSION').read_text(), '1.1.0-alpha.7')
        self.assertEqual(read_json(self.profile.parent/'update_history.json')[0]['status'], 'installed')

    def test_startup_failure_rolls_back_and_relaunches(self):
        app = self.make_payloads()
        child = Mock(returncode=1); child.poll.return_value = 1
        old = Mock(returncode=0); old.poll.return_value = 0
        with patch('launcher.subprocess.Popen', side_effect=[child, old]) as spawn, patch('launcher.wait_for_ready', return_value=False):
            self.assertEqual(start_payload(self.root, self.root/'mhf_master.sqlite', [], Mock(), self.profile, True), 0)
        self.assertIn('--startup-report', spawn.call_args_list[0].args[0])
        self.assertNotIn('--startup-report', spawn.call_args_list[1].args[0])
        self.assertEqual((app/'VERSION').read_text(), '1.1.0-alpha.6')
        self.assertEqual(read_json(self.profile.parent/'update_history.json')[0]['status'], 'rollback')

    def test_spawn_error_rolls_back(self):
        app = self.make_payloads()
        old = Mock(returncode=0); old.poll.return_value = 0
        with patch('launcher.subprocess.Popen', side_effect=[OSError('cannot start'), old]):
            self.assertEqual(start_payload(self.root, self.root/'mhf_master.sqlite', [], Mock(), self.profile, True), 0)
        self.assertEqual((app/'VERSION').read_text(), '1.1.0-alpha.6')

    def test_manual_rollback(self):
        app = self.make_payloads()
        (self.root/'.update_pending').unlink()
        atomic_json(self.root/'.rollback_requested', {'requested':True})
        self.assertTrue(manual_rollback(self.root, self.profile.parent))
        self.assertEqual((app/'VERSION').read_text(), '1.1.0-alpha.6')
        self.assertFalse((self.root/'.rollback_requested').exists())

    def test_block_bad_release(self):
        atomic_json(self.root/'release_source.json', {'repository':REPOSITORY, 'channel':'stable','check_on_startup':True})
        record_history(self.profile.parent, 'rollback', '1.1.0')
        update = Mock()
        self.assertEqual(prepare(self.root, b'key', check_fn=Mock(return_value={'status':'available','version':'1.1.0'}), update_fn=update, profile_root=self.profile.parent), 'blocked_after_rollback')
        update.assert_not_called()

    def test_ready_poll(self):
        report = self.root/'ready.json'
        child = Mock(); child.poll.return_value = None
        self.assertTrue(wait_for_ready(child, report, lambda:atomic_json(report, {'ready':True}), timeout=1))
        report.unlink()
        child.poll.return_value = 1
        self.assertFalse(wait_for_ready(child, report, Mock(), timeout=1))


if __name__ == '__main__':
    unittest.main()
