"""Offline tests with real Ed25519 signatures and temporary portable installations."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from release_sign import sign_release, blob
from update_core import update, safe_path, recover, digest, OUTER, REPOSITORY, AssetRedirect
from launcher import prepare


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'install'
        self.root.mkdir()
        self.app = self.root / 'app'
        self.app.mkdir()
        self.old = '1.1.0-alpha.5'
        self.new = '1.1.0'
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.old_files = {'VERSION': self.old.encode(), 'MHFDesktop.exe': b'MZold',
                          'web/index.html': b'old', 'web/app.js': b'old', 'web/favicon.ico': b'ico',
                          '_internal/data.bin': b'large' * 50000, 'obsolete.txt': b'obsolete'}
        self.new_files = {**self.old_files, 'VERSION': self.new.encode(), 'MHFDesktop.exe': b'MZnew', 'web/app.js': b'new'}
        del self.new_files['obsolete.txt']
        for name, data in self.old_files.items():
            path = self.app / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.root / 'MHFSimulator.exe').write_bytes(b'launcher')
        (self.root / 'mhf_master.sqlite').write_bytes(b'private db')
        (self.root / 'release_source.json').write_text(json.dumps({'repository': REPOSITORY, 'channel': 'stable', 'check_on_startup': True}))
        self.previous = self.archive(self.old, self.old_files)
        self.full = self.archive(self.new, self.new_files)
        self.info = sign_release(self.full, self.key, self.previous)
        self.candidate = {'status': 'available', 'version': self.new, **blob(self.full)}
        self.downloads = []

    def archive(self, version, files):
        path = self.base / f'MHF_SkillSimulator_{version}_win_x64_no_DB.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
            z.writestr(OUTER+'MHFSimulator.exe', b'launcher')
            z.writestr(OUTER+'release_source.json', b'{}')
            for name, data in files.items():
                z.writestr(OUTER+'app/'+name, data)
        return path

    def fetch(self, version, name, dest, limit, expected=None):
        self.downloads.append(name)
        src = self.base / name
        dest.write_bytes(src.read_bytes())
        if dest.stat().st_size > limit or (expected and (digest(dest) != expected['sha256'] or dest.stat().st_size != expected['size'])):
            raise ValueError('Integrity failure')

    def assert_preserved(self):
        self.assertEqual((self.root/'mhf_master.sqlite').read_bytes(), b'private db')
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(), b'launcher')
        self.assertEqual(json.loads((self.root/'release_source.json').read_text())['repository'], REPOSITORY)

    def apply(self, public=None, smoke=None):
        return update(self.root, self.candidate, self.public if public is None else public,
                      smoke or Mock(), self.fetch)

    def test_delta_update(self):
        self.assertEqual(self.apply(), 'delta')
        self.assertNotIn(self.full.name, self.downloads)
        self.assertEqual((self.app/'web/app.js').read_bytes(), b'new')
        self.assertFalse((self.app/'obsolete.txt').exists())
        self.assertEqual((self.root/'.app_previous'/'VERSION').read_text(), self.old)
        self.assert_preserved()

    def test_modified_base_falls_back_to_full(self):
        (self.app/'_internal/data.bin').write_bytes(b'broken')
        self.assertEqual(self.apply(), 'full')
        self.assertIn(self.full.name, self.downloads)
        self.assertEqual((self.app/'_internal/data.bin').read_bytes(), self.new_files['_internal/data.bin'])
        self.assert_preserved()

    def test_skipped_version_falls_back_to_full(self):
        (self.app/'VERSION').write_text('1.0.0')
        self.assertEqual(self.apply(), 'full')
        self.assertNotIn(self.info['delta']['asset'], self.downloads)

    def test_wrong_key_rejected(self):
        other = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        with self.assertRaises(Exception):
            self.apply(public=other)
        self.assertEqual((self.app/'VERSION').read_text(), self.old)
        self.assert_preserved()

    def test_manifest_tamper_rejected(self):
        p = self.full.with_name(self.full.name+'.update.json')
        p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(Exception):
            self.apply()
        self.assertEqual((self.app/'VERSION').read_text(), self.old)

    def test_full_tamper_rejected(self):
        (self.app/'VERSION').write_text('1.0.0')
        with self.full.open('ab') as out:
            out.write(b'tamper')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual((self.app/'VERSION').read_text(), '1.0.0')

    def test_smoke_failure_before_swap(self):
        with self.assertRaises(RuntimeError):
            self.apply(smoke=Mock(side_effect=RuntimeError('failed')))
        self.assertEqual((self.app/'VERSION').read_text(), self.old)
        self.assert_preserved()

    def test_smoke_failure_after_swap(self):
        with self.assertRaises(RuntimeError):
            self.apply(smoke=Mock(side_effect=[None, RuntimeError('failed')]))
        self.assertEqual((self.app/'VERSION').read_text(), self.old)
        self.assertFalse((self.root/'.update_pending').exists())
        self.assert_preserved()

    def test_interrupted_swap_recovered(self):
        self.app.rename(self.root/'.app_previous')
        (self.root/'.update_pending').write_text('pending')
        recover(self.root)
        self.assertEqual((self.app/'VERSION').read_text(), self.old)

    def test_interrupted_after_swap_recovered(self):
        self.app.rename(self.root/'.app_previous')
        self.app.mkdir()
        (self.app/'VERSION').write_text(self.new)
        (self.root/'.update_pending').write_text('pending')
        recover(self.root)
        self.assertEqual((self.app/'VERSION').read_text(), self.old)

    def test_unsafe_paths(self):
        for name in ('../evil', '/absolute', 'C:/evil', 'a\\b', 'CON.txt', 'a/..', 'a.', 'a/b ', 'mhf_master.sqlite', 'a:ads', 'a//b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                safe_path(name)

    def test_offline_or_no_key(self):
        check = Mock(return_value={'status':'unavailable'})
        self.assertEqual(prepare(self.root, None, check_fn=check), 'disabled')
        check.assert_not_called()
        self.assertEqual(prepare(self.root, self.public, check_fn=check), 'unavailable')
        self.assertEqual((self.app/'VERSION').read_text(), self.old)

    def test_update_failure_continues(self):
        self.assertEqual(prepare(self.root, self.public, check_fn=Mock(return_value=self.candidate),
                                 update_fn=Mock(side_effect=OSError('offline'))), 'failed')
        self.assert_preserved()

    def test_redirect_to_untrusted_host(self):
        with self.assertRaises(ValueError):
            AssetRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example/asset')


if __name__ == '__main__':
    unittest.main()
