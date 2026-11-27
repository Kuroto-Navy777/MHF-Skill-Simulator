"""Offline signed launcher update and user confirmation tests."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from launcher_update import (launcher_asset_name, launcher_metadata, replace_launcher,
                             read_signed_candidate, stage_handoff, run_handoff, HANDOFF)
from launcher import interactive_update
from release_sign import sign_release, blob
from release_preflight import prepare_upload
from release_check import check
from update_core import REPOSITORY, OUTER


class LauncherUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'install'; self.root.mkdir()
        self.profile = self.base/'profile'; self.profile.mkdir()
        (self.root/'app').mkdir()
        (self.root/'app'/'VERSION').write_text('1.1.0-rc.4')
        (self.root/'MHFSimulator.exe').write_bytes(b'MZold')
        (self.root/'mhf_master.sqlite').write_bytes(b'db')
        (self.root/'release_source.json').write_text(json.dumps({'repository':REPOSITORY,'channel':'preview','check_on_startup':True}))
        self.version = '1.1.0-rc.5'
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.archive = self.base/f'MHF_SkillSimulator_{self.version}_win_x64_no_DB.zip'
        with zipfile.ZipFile(self.archive,'w') as z:
            z.writestr(OUTER+'MHFSimulator.exe',b'MZnew')
            for name in ('MHFDesktop.exe','web/index.html','web/app.js','web/favicon.ico'):
                z.writestr(OUTER+'app/'+name,b'MZfile')
            z.writestr(OUTER+'app/VERSION',self.version)
        self.data = sign_release(self.archive,self.key)
        self.candidate = {'status':'available','version':self.version,**blob(self.archive)}
        self.progress = Mock(active=True)
        self.progress.run.side_effect = lambda fn,*args,**kwargs: fn(*args,**kwargs)
        self.progress.confirm_update.return_value = True

    def fetch(self, version, name, destination, limit, expected=None):
        destination.write_bytes((self.base/name).read_bytes())
        if destination.stat().st_size > limit:
            raise ValueError('size')

    def run_update(self, current='1.1.0-rc.4', accepted=None):
        self.stage = Mock(); self.app_update = Mock(return_value='delta')
        return interactive_update(self.root,self.profile,self.progress,self.public,current,accepted,
                                  check_fn=Mock(return_value=self.candidate),
                                  manifest_fn=lambda c,k,v,f:read_signed_candidate(c,k,v,f,self.fetch),
                                  stage_fn=self.stage,update_fn=self.app_update)

    def test_signed_asset_matches_archive(self):
        self.assertEqual((self.base/launcher_asset_name(self.version)).read_bytes(),b'MZnew')
        self.assertEqual(launcher_metadata(self.data),blob(self.base/launcher_asset_name(self.version)))

    def test_decline_no_install(self):
        self.progress.confirm_update.return_value = False
        self.assertEqual(self.run_update(),'deferred')
        self.stage.assert_not_called(); self.app_update.assert_not_called()

    def test_accept_both_launcher_first(self):
        self.assertEqual(self.run_update(),'launcher_handoff')
        self.progress.confirm_update.assert_called_once_with(self.version,True,True)
        self.stage.assert_called_once(); self.app_update.assert_not_called()

    def test_restart_only_app_no_second_prompt(self):
        self.assertEqual(self.run_update(self.version,self.version),'delta')
        self.progress.confirm_update.assert_not_called(); self.stage.assert_not_called()
        self.app_update.assert_called_once()

    def test_launcher_only_when_app_already_current(self):
        (self.root/'app'/'VERSION').write_text(self.version)
        self.assertEqual(self.run_update(),'launcher_handoff')
        self.progress.confirm_update.assert_called_once_with(self.version,True,False)
        self.app_update.assert_not_called()

    def test_bad_signed_metadata_does_not_prompt(self):
        p = Path(str(self.archive)+'.update.json'); p.write_bytes(p.read_bytes()+b' ')
        with self.assertRaises(Exception): self.run_update()
        self.progress.confirm_update.assert_not_called(); self.stage.assert_not_called()

    def test_stage_checks_smoke_and_copies_helper(self):
        folder = self.base/'metadata'; folder.mkdir()
        data = read_signed_candidate(self.candidate,self.public,'1.1.0-rc.4',folder,self.fetch)
        smoke,spawn=Mock(),Mock()
        stage_handoff(self.root,folder,self.candidate,data,self.public,smoke,spawn,self.fetch)
        work=self.root/HANDOFF
        smoke.assert_called_once(); spawn.assert_called_once_with(work/'helper.exe')
        self.assertEqual((work/'helper.exe').read_bytes(),b'MZold')
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZold')
        replace_launcher(self.root,work,launcher_metadata(data))
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZnew')
        self.assertEqual((self.root/'.launcher_previous.exe').read_bytes(),b'MZold')
        self.assertEqual((self.root/'mhf_master.sqlite').read_bytes(),b'db')

    def test_tampered_launcher_not_executed(self):
        folder=self.base/'metadata'; folder.mkdir()
        data=read_signed_candidate(self.candidate,self.public,'1.1.0-rc.4',folder,self.fetch)
        (self.base/launcher_asset_name(self.version)).write_bytes(b'MZbad')
        smoke,spawn=Mock(),Mock()
        with self.assertRaisesRegex(ValueError,'integrity'):
            stage_handoff(self.root,folder,self.candidate,data,self.public,smoke,spawn,self.fetch)
        smoke.assert_not_called(); spawn.assert_not_called()
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZold')

    def test_locked_launcher_retains_original(self):
        work=self.root/HANDOFF; work.mkdir(); (work/'next.exe').write_bytes(b'MZnew')
        import os
        def locked(src,dst):
            if dst.name=='MHFSimulator.exe': raise PermissionError('locked')
            os.replace(src,dst)
        with self.assertRaises(PermissionError):
            replace_launcher(self.root,work,launcher_metadata(self.data),replace=locked,timeout=0)
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZold')
        self.assertEqual((self.root/'.launcher_previous.exe').read_bytes(),b'MZold')

    def test_release_gate_includes_launcher(self):
        keyfile=self.base/'key.bin'; keyfile.write_bytes(self.public)
        report={'ok':True,'frozen':True,'launcher':{'ok':True,'version':self.version,'public_key_sha256':hashlib.sha256(self.public).hexdigest()},'checks':{k:True for k in ('imports','milp','assets','database','api_search')}}
        Path(str(self.archive.with_suffix(''))+'.smoke.json').write_text(json.dumps(report))
        out=self.base/'upload'
        result=prepare_upload(self.archive,keyfile,out)
        self.assertIn(launcher_asset_name(self.version),result['assets'])
        self.assertEqual(len(result['assets']),4)

    def test_discovery_considers_launcher_version(self):
        (self.root/'app'/'VERSION').write_text(self.version)
        row={'tag_name':'v'+self.version,'draft':False,'prerelease':True,'assets':[{'name':self.archive.name,'state':'uploaded','size':self.candidate['size'],'digest':'sha256:'+self.candidate['sha256'],'browser_download_url':f'https://github.com/{REPOSITORY}/releases/download/v{self.version}/{self.archive.name}'}]}
        self.assertEqual(check(self.root,fetch=Mock(return_value=[row]))['status'],'no_compatible_release')
        self.assertEqual(check(self.root,fetch=Mock(return_value=[row]),launcher_current='1.1.0-rc.4')['status'],'available')

    def test_helper_restores_old_launcher_if_new_exits_before_ack(self):
        folder = self.base/'metadata'; folder.mkdir()
        data = read_signed_candidate(self.candidate,self.public,'1.1.0-rc.4',folder,self.fetch)
        stage_handoff(self.root,folder,self.candidate,data,self.public,Mock(),Mock(),self.fetch)
        lock = MagicMock(); lock.__enter__.return_value.primary = True
        progress = MagicMock(); progress.__enter__.return_value = self.progress
        child = Mock(); child.poll.return_value = 1
        with patch('desktop_lifecycle.SingleInstance',return_value=lock), patch('update_progress.StartupProgress',return_value=progress), patch('launcher_update.subprocess.Popen',return_value=child) as spawn:
            run_handoff(self.root,self.root/HANDOFF,self.public,'1.1.0-rc.4',self.profile/'WebView2',Mock(),dict)
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZold')
        self.assertEqual(spawn.call_count,2)
        self.assertIn('--skip-update-once',spawn.call_args.args[0])
        self.assertEqual(json.loads((self.profile/'update_history.json').read_text())[0]['status'],'rollback')

    def test_helper_preserves_new_launcher_after_startup_ack(self):
        folder = self.base/'metadata'; folder.mkdir()
        data = read_signed_candidate(self.candidate,self.public,'1.1.0-rc.4',folder,self.fetch)
        stage_handoff(self.root,folder,self.candidate,data,self.public,Mock(),Mock(),self.fetch)
        lock = MagicMock(); lock.__enter__.return_value.primary = True
        progress = MagicMock(); progress.__enter__.return_value = self.progress
        def launch(*args,**kwargs):
            (self.root/HANDOFF/'ready.json').write_text('ready')
            return Mock(poll=Mock(return_value=None))
        with patch('desktop_lifecycle.SingleInstance',return_value=lock), patch('update_progress.StartupProgress',return_value=progress), patch('launcher_update.subprocess.Popen',side_effect=launch) as spawn:
            run_handoff(self.root,self.root/HANDOFF,self.public,'1.1.0-rc.4',self.profile/'WebView2',Mock(),dict)
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZnew')
        spawn.assert_called_once()
        self.assertIn('--accepted-update='+self.version,spawn.call_args.args[0])

    def test_helper_restores_old_launcher_if_spawn_raises(self):
        folder = self.base/'metadata'; folder.mkdir()
        data = read_signed_candidate(self.candidate,self.public,'1.1.0-rc.4',folder,self.fetch)
        stage_handoff(self.root,folder,self.candidate,data,self.public,Mock(),Mock(),self.fetch)
        lock = MagicMock(); lock.__enter__.return_value.primary = True
        progress = MagicMock(); progress.__enter__.return_value = self.progress
        with patch('desktop_lifecycle.SingleInstance',return_value=lock), patch('update_progress.StartupProgress',return_value=progress), patch('launcher_update.subprocess.Popen',side_effect=[OSError('cannot start'),Mock()]) as spawn:
            run_handoff(self.root,self.root/HANDOFF,self.public,'1.1.0-rc.4',self.profile/'WebView2',Mock(),dict)
        self.assertEqual((self.root/'MHFSimulator.exe').read_bytes(),b'MZold')
        self.assertEqual(spawn.call_count,2)
        self.assertIn('--skip-update-once',spawn.call_args.args[0])


if __name__=='__main__': unittest.main()
