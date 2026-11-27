"""Publishing remains draft-only until CI passes; private material is rejected."""
from pathlib import Path
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from ci import release


class Release120Tests(unittest.TestCase):
    def test_source_manifest_hashes_staged_bytes_after_git_line_end_normalization(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'a.py').write_bytes(b'line\r\n')
            with patch.object(release,'ROOT',root),patch.object(release.subprocess,'check_output',side_effect=[b'a.py\0release_manifest.json\0',b'line\n']):
                release.source_manifest('1.2.0')
            manifest=json.loads((root/'release_manifest.json').read_text())
            self.assertEqual(manifest['files'],{'a.py':hashlib.sha256(b'line\n').hexdigest()})

    def test_draft_is_created_before_ci_and_main_promotion_and_publish_are_last(self):
        calls=[]
        with patch.object(release,'run',side_effect=lambda *a,**k:calls.append(a)),patch.object(release,'wait_ci',side_effect=lambda c:calls.append(('CI',c))):
            release.register_release('1.2.0','a'*40,[Path('safe.zip')],publish=True,promote_main=True)
        self.assertIn('--draft',calls[0]);self.assertEqual(calls[1],('CI','a'*40))
        self.assertEqual(calls[-2],('git','push','origin','HEAD:main'))
        self.assertIn('--draft=false',calls[-1]);self.assertIn('--latest',calls[-1])

    def test_ci_failure_does_not_publish_or_promote_main(self):
        calls=[]
        with patch.object(release,'run',side_effect=lambda *a,**k:calls.append(a)),patch.object(release,'wait_ci',side_effect=subprocess.CalledProcessError(1,'CI')):
            with self.assertRaises(subprocess.CalledProcessError):
                release.register_release('1.2.0','a'*40,[Path('safe.zip')],publish=True,promote_main=True)
        self.assertEqual(len(calls),1);self.assertIn('--draft',calls[0]);self.assertNotIn('--draft=false',calls[0])

    def test_default_registration_is_draft_only_and_never_waits_for_secrets_or_ci(self):
        with patch.object(release,'run') as run,patch.object(release,'wait_ci') as ci:
            release.register_release('1.2.0','a'*40,[Path('safe.zip')])
        run.assert_called_once();ci.assert_not_called();self.assertIn('--draft',run.call_args.args)

    def test_private_files_and_tokens_are_rejected_without_echoing_secret(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name,data in [('private.pem',b'anything'),('data.sqlite-wal',b'database'),('.env.production',b'anything'),
                              ('oops.txt',b'ghp_'+b'x'*36),('private.txt',b'-----BEGIN RSA PRIVATE KEY-----\nencoded')]:
                (root/name).write_bytes(data)
                with patch.object(release,'ROOT',root),patch.object(release.subprocess,'check_output',return_value=(name+'\0').encode()):
                    with self.assertRaises(ValueError) as exc:release.audit_index()
                self.assertNotIn('x'*36,str(exc.exception))

    def test_existing_public_key_is_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'update_public_key.bin').write_bytes(b'p'*32)
            with patch.object(release,'ROOT',root),patch.object(release.subprocess,'check_output',return_value=b'update_public_key.bin\0'):
                release.audit_index()


if __name__=='__main__':unittest.main()
