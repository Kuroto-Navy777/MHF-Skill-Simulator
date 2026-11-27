"""Offline release gate tests with synthetic archives and real Ed25519 signatures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from build_windows import write_release
from release_sign import sign_release
from release_preflight import prepare_upload, verify_release

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.stage = self.root/'stage'; self.stage.mkdir()
        self.out = self.root/'release'; self.out.mkdir()
        self.portable = self.root/'portable'; self.portable.mkdir()
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.root/'public.bin'
        self.pub.write_bytes(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.smoke = self.root/'smoke.json'
        self.smoke.write_text(json.dumps({'ok':True,'frozen':True,'launcher':{'ok':True,'public_key_sha256':hashlib.sha256(self.pub.read_bytes()).hexdigest()},'checks':{k:True for k in ('imports','milp','assets','database','api_search')}}))
        for path in ('MHFSimulator.exe','app/MHFDesktop.exe','app/web/index.html','app/web/app.js','app/web/favicon.ico','app/_internal/data.bin'):
            p = self.portable/path
            p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(b'test' * 100)
        (self.portable/'app/VERSION').write_text('1.1.0-alpha.8')
        self.previous = write_release(self.portable,self.stage,self.out,'1.1.0-alpha.8',False,self.smoke)
        (self.portable/'app/VERSION').write_text('1.1.0-rc.1')
        (self.portable/'app/web/app.js').write_bytes(b'new')
        self.full = write_release(self.portable,self.stage,self.out,'1.1.0-rc.1',False,self.smoke)
        sign_release(self.full,self.key,self.previous)

    def test_upload_allowlist_and_delta(self):
        out = self.root/'upload'
        info = prepare_upload(self.full,self.pub,out,self.previous)
        self.assertTrue(info['delta_verified'])
        self.assertTrue(info['prerelease'])
        self.assertEqual(len(list(out.iterdir())),4)

    def test_pair_identical_payload(self):
        (self.portable/'mhf_master.sqlite').write_bytes(b'private db')
        private = write_release(self.portable,self.stage,self.out,'1.1.0-rc.1',True,self.smoke)
        with zipfile.ZipFile(private) as a, zipfile.ZipFile(self.full) as b:
            self.assertEqual(set(a.namelist())-set(b.namelist()),{'MHF_SkillSimulator/mhf_master.sqlite'})
            for name in b.namelist():
                self.assertEqual(a.read(name),b.read(name))
        with self.assertRaises(ValueError):
            verify_release(private,self.pub)

    def test_missing_previous(self):
        with self.assertRaises(ValueError):
            verify_release(self.full,self.pub)

    def test_wrong_key(self):
        self.pub.write_bytes(b'0'*32)
        with self.assertRaises(ValueError):
            verify_release(self.full,self.pub,self.previous)

    def test_tampered_delta(self):
        patch = next(self.out.glob('MHF_delta_*.zip'))
        with patch.open('ab') as f:
            f.write(b'tampered')
        with self.assertRaises(ValueError):
            verify_release(self.full,self.pub,self.previous)

    def test_missing_db_test(self):
        path = self.full.with_name(self.full.stem+'.smoke.json')
        report = json.loads(path.read_text())
        report['checks']['api_search'] = False
        path.write_text(json.dumps(report))
        with self.assertRaises(ValueError):
            verify_release(self.full,self.pub,self.previous)

    def test_existing_upload_directory(self):
        out = self.root/'upload'; out.mkdir()
        (out/'private.pem').write_bytes(b'private')
        with self.assertRaises(FileExistsError):
            prepare_upload(self.full,self.pub,out,self.previous)
        self.assertEqual((out/'private.pem').read_bytes(),b'private')

    def test_no_db_leak(self):
        (self.portable/'mhf_master.sqlite').write_bytes(b'private db')
        with self.assertRaises(ValueError):
            write_release(self.portable,self.stage,self.out,'1.1.0-rc.2',False,self.smoke)

if __name__ == '__main__':
    unittest.main()
