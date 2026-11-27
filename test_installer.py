"""Installer staging tests, using actual Ed25519 signatures and fake Windows executables."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from build_installer import stage_installer, render_script, installer_name
from installer_guard import MUTEX_NAME, installer_guard
from release_sign import sign_release
from update_core import OUTER, REPOSITORY


class InstallerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        key = Ed25519PrivateKey.generate()
        self.pub = self.root/'public.bin'
        self.pub.write_bytes(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.archive = self.root/'MHF_SkillSimulator_1.1.0_win_x64_no_DB.zip'
        self.old = self.root/'MHF_SkillSimulator_1.1.0-rc.6_win_x64_no_DB.zip'
        self.config = {'repository':REPOSITORY,'channel':'stable','check_on_startup':True}
        for version, path in [('1.1.0-rc.6',self.old),('1.1.0',self.archive)]:
            with zipfile.ZipFile(path,'w') as z:
                for name in ('app/MHFDesktop.exe','app/web/index.html','app/web/app.js','app/web/favicon.ico','MHFSimulator.exe','README.txt'):
                    z.writestr(OUTER+name,b'MZtest')
                z.writestr(OUTER+'app/VERSION',version)
                z.writestr(OUTER+'release_source.json',json.dumps(self.config))
        report = {'ok':True,'frozen':True,'launcher':{'ok':True,'version':'1.1.0','public_key_sha256':hashlib.sha256(self.pub.read_bytes()).hexdigest()},'checks':{k:True for k in ('imports','milp','assets','database','api_search')}}
        self.archive.with_suffix('.smoke.json').write_text(json.dumps(report))
        sign_release(self.archive,key,self.old)
        self.stage = self.root/'payload'

    def test_signed_payload_without_db(self):
        self.assertEqual(stage_installer(self.archive,self.pub,self.old,self.stage),'1.1.0')
        self.assertFalse((self.stage/'mhf_master.sqlite').exists())
        self.assertEqual((self.stage/'app'/'VERSION').read_text(),'1.1.0')
        self.assertEqual(json.loads((self.stage/'release_source.json').read_text()),self.config)

    def test_db_only_by_explicit_choice(self):
        db = self.root/'private.sqlite'; db.write_bytes(b'local database')
        with patch('build_installer.check_db') as validate:
            stage_installer(self.archive,self.pub,self.old,self.stage,db)
        validate.assert_called_once_with(db,master=True,deep=True)
        self.assertEqual((self.stage/'mhf_master.sqlite').read_bytes(),db.read_bytes())
        with zipfile.ZipFile(self.archive) as z:
            self.assertNotIn(OUTER+'mhf_master.sqlite',z.namelist())

    def test_invalid_database_refused(self):
        db=self.root/'broken.sqlite'; db.write_bytes(b'not sqlite')
        with self.assertRaises(Exception):
            stage_installer(self.archive,self.pub,self.old,self.stage,db)
        self.assertFalse((self.stage/'mhf_master.sqlite').exists())

    def test_tampering_refused_before_staging(self):
        with self.archive.open('ab') as f: f.write(b'tampered')
        with self.assertRaises(ValueError):
            stage_installer(self.archive,self.pub,self.old,self.stage)
        self.assertFalse(self.stage.exists())

    def test_wrong_key_refused(self):
        self.pub.write_bytes(b'0'*32)
        with self.assertRaises(ValueError):
            stage_installer(self.archive,self.pub,self.old,self.stage)
        self.assertFalse(self.stage.exists())

    def test_previous_required_for_delta(self):
        with self.assertRaises(ValueError):
            stage_installer(self.archive,self.pub,None,self.stage)

    def test_install_names_and_script(self):
        template = (Path(__file__).parent/'installer/MHFSkillSimulator.iss').read_text(encoding='utf-8-sig')
        self.assertIn('AppMutex='+MUTEX_NAME,template)
        self.assertIn('PrivilegesRequired=lowest',template)
        self.assertIn('DefaultDirName={localappdata}\\Programs\\MHFSkillSimulator',template)
        self.assertNotIn('Name: "{app}"',template.split('[UninstallDelete]')[1])
        self.assertIn('onlyifdoesntexist uninsneveruninstall',template)
        self.assertIn('#define IncludeDB 1',render_script(template,'1.1.0',True))
        self.assertIn('#define IncludeDB 0',render_script(template,'1.1.0',False))
        self.assertEqual(installer_name('1.1.0',True),'MHF_SkillSimulator_1.1.0_Setup_win_x64_with_DB.exe')
        with self.assertRaises(ValueError): render_script(template,'evil"',True)

    @unittest.skipUnless(__import__('os').name=='nt','Windows mutex test')
    def test_guard_windows(self):
        import ctypes
        from ctypes import wintypes
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        k.OpenMutexW.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR]
        k.OpenMutexW.restype=wintypes.HANDLE
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        with installer_guard():
            h=k.OpenMutexW(0x00100000,False,MUTEX_NAME)
            self.assertTrue(h)
            k.CloseHandle(h)


if __name__=='__main__': unittest.main()
