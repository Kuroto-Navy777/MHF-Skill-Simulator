"""Unit tests for setup boundaries and offline update safety."""
import hashlib
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import windows_setup as w


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def release(self, files, bad=False, **meta):
        p=self.root/'release.zip'
        manifest={'files':{k:hashlib.sha256(v).hexdigest() for k,v in files.items()},**meta}
        if bad:
            manifest['files']['VERSION']='0'*64
        with zipfile.ZipFile(p,'w') as z:
            for k,v in files.items():z.writestr(k,v)
            z.writestr('release_manifest.json',json.dumps(manifest))
        return p

    def test_update_preserves_database_and_backups(self):
        (self.root/w.MASTER).write_bytes(b'database')
        (self.root/'VERSION').write_text('old')
        p=self.release({'VERSION':b'new','web/app.js':b'updated'})
        with patch.object(w,'require_stopped'):
            backup=w.apply_update(self.root,p)
        self.assertEqual((self.root/w.MASTER).read_bytes(),b'database')
        self.assertEqual((backup/'VERSION').read_text(),'old')
        self.assertEqual((self.root/'web/app.js').read_bytes(),b'updated')

    def test_update_rejects_traversal_and_data(self):
        for name in ('../bad.py','web/../../bad.py','C:/bad.py','mhf_master.sqlite','data/test.py'):
            p=self.release({'VERSION':b'new',name:b'bad'})
            with patch.object(w,'require_stopped'), self.assertRaises(ValueError):
                w.apply_update(self.root,p)
        self.assertFalse((self.root/'VERSION').exists())

    def test_checksum_failure_no_changes(self):
        (self.root/'VERSION').write_text('old')
        p=self.release({'VERSION':b'new'},bad=True)
        with patch.object(w,'require_stopped'), self.assertRaises(ValueError):
            w.apply_update(self.root,p)
        self.assertEqual((self.root/'VERSION').read_text(),'old')

    def test_update_rollback(self):
        (self.root/'VERSION').write_text('old')
        p=self.release({'VERSION':b'new','web/app.js':b'updated'})
        replace=w.os.replace
        def fail_second(src,dst):
            if dst.name=='app.js':raise OSError('test error')
            replace(src,dst)
        with patch.object(w,'require_stopped'),patch.object(w.os,'replace',side_effect=fail_second),self.assertRaises(OSError):
            w.apply_update(self.root,p)
        self.assertEqual((self.root/'VERSION').read_text(),'old')
        self.assertFalse((self.root/'web/app.js').exists())

    def test_delta_checks_installed_version(self):
        (self.root/'VERSION').write_text('1.0.0-rc.1')
        p=self.release({'VERSION':b'1.0.0-rc.2'},version='1.0.0-rc.2',base_versions=['1.0.0-rc.1'])
        with patch.object(w,'require_stopped'):
            w.apply_update(self.root,p)
            with self.assertRaisesRegex(ValueError,'Incompatible update'):
                w.apply_update(self.root,p)
        self.assertEqual((self.root/'VERSION').read_text(),'1.0.0-rc.2')

    def test_version_mismatch_rejected(self):
        p=self.release({'VERSION':b'wrong'},version='1.0.0-rc.2')
        with patch.object(w,'require_stopped'),self.assertRaisesRegex(ValueError,'VERSION'):
            w.apply_update(self.root,p)
        self.assertFalse((self.root/'VERSION').exists())

    def test_windows_device_names_rejected(self):
        for name in ('NUL.py','CON.bat','COM1.mjs','LPT9.py','bad.py.'):
            self.assertFalse(w.allowed_file(name),name)

    def test_publish_does_not_overwrite(self):
        a,b=self.root/'source',self.root/'dest'
        a.write_bytes(b'a');b.write_bytes(b'b')
        with self.assertRaises(OSError):w.publish(a,b)
        self.assertEqual(b.read_bytes(),b'b')

    def test_archive_resolution(self):
        for key,names in w.ARCHIVES.items():
            with zipfile.ZipFile(self.root/names[-1],'w') as z:z.writestr('data','x')
        self.assertEqual(set(w.resolve_archives(self.root)),set(w.ARCHIVES))
        (self.root/w.ARCHIVES['ja'][0]).unlink()
        with self.assertRaises(FileNotFoundError):w.resolve_archives(self.root)

    def test_migration_source_hash(self):
        base=self.root/w.BASE
        with closing(sqlite3.connect(base)) as db, db:
            db.execute('CREATE TABLE sources(id,filename,sha256)')
            for key in ('ja','en','ferias'):
                p=self.root/f'{key}.zip';p.write_bytes(b'original')
                db.execute('INSERT INTO sources VALUES(?,?,?)',(key,p.name,w.digest(p)))
        self.assertEqual(len(w.resolve_archives(self.root,base)),3)
        (self.root/'ja.zip').write_bytes(b'changed')
        with self.assertRaises(ValueError):w.resolve_archives(self.root,base)

    def test_existing_master_skips_import(self):
        p=self.root/w.MASTER;p.write_bytes(b'original')
        with patch.object(w,'require_stopped'),patch.object(w,'check_db') as check,patch.object(w,'prepare_python'),patch.object(w,'archive_directory') as archives:
            self.assertEqual(w.setup(self.root),p)
        check.assert_called_once_with(p,master=True,deep=True)
        archives.assert_not_called()
        self.assertEqual(p.read_bytes(),b'original')

    def test_invalid_db_rejected(self):
        p=self.root/w.MASTER
        with closing(sqlite3.connect(p)):pass
        with self.assertRaises(sqlite3.Error):w.check_db(p,master=True)


if __name__=='__main__':unittest.main()
