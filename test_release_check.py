"""Offline tests for release discovery and tray integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from release_check import check, select_release, version_key, read_config, NoRedirect

REPO = 'example/mhf-simulator'


def release(version, **overrides):
    name = f'MHF_SkillSimulator_{version}_win_x64_no_DB.zip'
    row = {'tag_name': 'v'+version, 'draft': False, 'prerelease': '-' in version,
           'assets': [{'name': name, 'state': 'uploaded', 'size': 100,
                       'digest': 'sha256:'+'a'*64,
                       'browser_download_url': f'https://github.com/{REPO}/releases/download/v{version}/{name}'}]}
    row.update(overrides)
    return row


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'VERSION').write_text('1.1.0-alpha.4')

    def config(self, **kwargs):
        data = {'repository': REPO, 'channel': 'stable', **kwargs}
        (self.root / 'release_source.json').write_text(json.dumps(data))

    def test_numeric_version_order(self):
        versions = ['1.1.0-alpha.4', '1.1.0-alpha.10', '1.1.0-beta.1', '1.1.0-rc.1', '1.1.0', '1.1.1']
        self.assertEqual(sorted(versions, key=version_key), versions)
        for invalid in ('01.1.0', '1.0', '1.1.0-rc.01', 'v1.1.0', '1.1.0+build'):
            with self.assertRaises(ValueError):
                version_key(invalid)

    def test_unconfigured_no_network(self):
        fetch = Mock()
        self.assertEqual(check(self.root, fetch)['status'], 'unconfigured')
        self.config(repository=None)
        self.assertEqual(check(self.root, fetch)['status'], 'unconfigured')
        fetch.assert_not_called()

    def test_stable_endpoint(self):
        self.config()
        fetch = Mock(return_value=release('1.1.0'))
        result = check(self.root, fetch)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['sha256'], 'a'*64)
        fetch.assert_called_once_with(f'https://api.github.com/repos/{REPO}/releases/latest')

    def test_preview_endpoint(self):
        self.config(channel='preview')
        fetch = Mock(return_value=[release('1.1.0-alpha.5'), release('1.1.0-alpha.12'), release('1.1.0-alpha.3')])
        self.assertEqual(check(self.root, fetch)['version'], '1.1.0-alpha.12')
        fetch.assert_called_once_with(f'https://api.github.com/repos/{REPO}/releases?per_page=100')

    def test_stable_rejects_preview_draft_downgrade(self):
        rows = [release('1.1.0-alpha.9'), release('2.0.0', draft=True), release('1.0.0'), release('1.1.0-alpha.4')]
        self.assertEqual(select_release(REPO,'stable','1.1.0-alpha.4',rows)['status'], 'no_compatible_release')

    def test_bad_assets_rejected(self):
        for key, value in [('digest',None),('size',0),('size',True),('state','new'),('browser_download_url','https://evil.example/a.zip'),('name','random.zip')]:
            row = release('1.2.0')
            row['assets'][0][key] = value
            self.assertEqual(select_release(REPO,'stable','1.1.0',[row])['status'],'no_compatible_release')
        row = release('1.2.0')
        row['assets'] *= 2
        self.assertEqual(select_release(REPO,'stable','1.1.0',[row])['status'],'no_compatible_release')

    def test_offline_and_rate_limit(self):
        self.config()
        for err in (TimeoutError('offline'), urllib.error.HTTPError('https://api.github.com', 403, 'rate limit', {}, None), urllib.error.HTTPError('https://api.github.com', 404, 'not found', {}, None)):
            self.assertEqual(check(self.root, Mock(side_effect=err))['status'],'unavailable')

    def test_invalid_repo_no_network(self):
        fetch = Mock()
        for repo in ('https://evil.example/foo','foo/..','foo/bar?x=1','foo/bar/baz'):
            self.config(repository=repo)
            self.assertEqual(check(self.root,fetch)['status'],'unavailable')
        fetch.assert_not_called()

    def test_build_metadata(self):
        import hashlib
        from build_windows import release_metadata
        archive = self.root / 'MHF_SkillSimulator_1.1.0-alpha.4_win_x64_no_DB.zip'
        archive.write_bytes(b'test archive')
        info = release_metadata(archive, '1.1.0-alpha.4', False)
        self.assertEqual(info['sha256'], hashlib.sha256(b'test archive').hexdigest())
        self.assertEqual(info['size'], 12)
        self.assertEqual(info['tag'], 'v1.1.0-alpha.4')
        with self.assertRaises(ValueError):
            release_metadata(archive, '1.1.0', False)

    def test_no_redirect(self):
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None,None,302,'',{},'https://evil.example')

    def test_config_strict(self):
        self.config(check_on_startup='true')
        with self.assertRaises(ValueError):
            read_config(self.root)

    def test_startup_notification_and_optout(self):
        from desktop_lifecycle import TrayController, Preferences
        ctrl = TrayController(Mock(), Preferences(self.root/'prefs.json'), Mock(), Mock(), 'http://localhost/', self.root)
        ctrl.ready.set()
        ctrl.icon = Mock()
        self.config(check_on_startup=False)
        # Run thread target synchronously to assert observable behavior without native UI.
        def run_thread(*args, **kw):
            return Mock(start=kw['target'])
        with patch('desktop_lifecycle.threading.Thread', side_effect=run_thread), patch('release_check.check',return_value={'status':'available','version':'1.2.0'}) as call:
            ctrl.check_release(automatic=True)
            call.assert_not_called()
            self.config()
            ctrl.check_release(automatic=True)
            call.assert_called_once()
            ctrl.icon.notify.assert_called_once()
            self.assertFalse(ctrl.release_lock.locked())


if __name__ == '__main__':
    unittest.main()
