"""Startup feedback and readiness regression tests (no live GitHub access)."""
import io
import logging
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

from build_windows import launcher_command
from launcher import start_payload, prepare
from update_core import fetch_asset, REPOSITORY
from update_progress import StartupProgress, StageHandler, download_display


class StartupTests(unittest.TestCase):
    def test_byte_display(self):
        self.assertEqual(download_display(0, 1024)[0], 0)
        self.assertEqual(download_display(1048576, 2097152), (50, '1.0 / 2.0 MiB  (50%)'))
        self.assertEqual(download_display(1024, 1024)[0], 100)
        for a, b in ((-1, 1), (1, 0), (2, 1), ('1', 2)):
            self.assertIsNone(download_display(a, b))

    def test_logging_messages(self):
        messages = queue.SimpleQueue()
        handler = StageHandler(messages)
        handler.emit(logging.LogRecord('launcher', 20, '', 0, 'Startup: checking releases', (), None))
        self.assertIn('最新版', messages.get_nowait())
        handler.emit(logging.LogRecord('launcher', 20, '', 0, 'Update bytes: %s / %s', (10, 20), None))
        self.assertEqual(messages.get_nowait(), (10, 20))

    def test_headless_fallback_runs_once(self):
        with patch.dict('sys.modules', {'tkinter': None}):
            with StartupProgress() as p:
                fn = Mock(return_value='unavailable')
                self.assertEqual(p.run(fn), 'unavailable')
                fn.assert_called_once()
                self.assertFalse(p.active)

    def test_background_no_ui(self):
        with StartupProgress(enabled=False) as p:
            self.assertFalse(p.active)
            self.assertEqual(p.run(lambda: 7), 7)

    def test_worker_exception_not_retried(self):
        p = StartupProgress(enabled=False)
        p.root = Mock()
        p.pump = Mock()
        fn = Mock(side_effect=ValueError('failure'))
        with self.assertRaisesRegex(ValueError, 'failure'):
            p.run(fn)
        fn.assert_called_once()
        p.close()

    def test_normal_startup_observes_ui_and_closes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'app').mkdir()
            (root/'app'/'VERSION').write_text('1.1.0-rc.3')
            progress = Mock(active=True)
            child = Mock(returncode=0); child.poll.return_value = 0
            with patch('launcher.subprocess.Popen', return_value=child) as spawn, patch('launcher.wait_for_ready', return_value=True) as ready:
                self.assertEqual(start_payload(root, root/'db', [], Mock(), root/'profile', False, progress), 0)
                self.assertIn('--startup-report', spawn.call_args.args[0])
                ready.assert_called_once()
                progress.close.assert_called_once()
                child.terminate.assert_not_called()

    def test_normal_failure_does_not_rollback(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'app').mkdir()
            (root/'app'/'VERSION').write_text('1.1.0-rc.3')
            child = Mock(returncode=1); child.poll.return_value = 1
            with patch('launcher.subprocess.Popen', return_value=child), patch('launcher.wait_for_ready', return_value=False), patch('launcher.rollback_pending') as rollback:
                self.assertEqual(start_payload(root, root/'db', [], Mock(), root/'profile', False, Mock(active=True)), 1)
                rollback.assert_not_called()
                child.terminate.assert_not_called()

    def test_fetch_reports_bytes_and_preserves_hash_validation(self):
        import hashlib
        data = b'x' * (1048576 + 200)
        expected = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as d, patch('update_core.urllib.request.build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(data)
            with self.assertLogs('launcher', 'INFO') as logs:
                fetch_asset('1.1.0-rc.3', 'file.zip', Path(d)/'file', len(data), expected)
            self.assertIn(f'INFO:launcher:Update bytes: {len(data)} / {len(data)}', logs.output)
            opener.return_value.open.return_value = io.BytesIO(data)
            with self.assertRaisesRegex(ValueError, 'integrity'):
                fetch_asset('1.1.0-rc.3', 'file.zip', Path(d)/'file', len(data), dict(expected, sha256='0'*64))

    def test_offline_no_install(self):
        from desktop_safety import atomic_json
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            atomic_json(root/'release_source.json', {'repository':REPOSITORY,'channel':'preview','check_on_startup':True})
            updater = Mock()
            self.assertEqual(prepare(root, b'key', check_fn=Mock(return_value={'status':'unavailable'}), update_fn=updater), 'unavailable')
            updater.assert_not_called()

    def test_build_bundles_tk(self):
        args = launcher_command(Path('.'), Path('stage'))
        self.assertIn('tkinter', args)
        self.assertIn('tkinter.ttk', args)

    def test_real_gui_if_display_available(self):
        import os
        if os.name != 'nt' and not os.getenv('DISPLAY'):
            self.skipTest('GUI display required')
        with StartupProgress() as p:
            self.assertTrue(p.active)
            p.show('最新版を確認しています…')
            p.messages.put((1024, 2048))
            p.pump()
            self.assertEqual(str(p.bar['mode']), 'determinate')
            self.assertEqual(float(p.bar['value']), 50)
            p.show('画面を読み込んでいます…')
            self.assertEqual(str(p.bar['mode']), 'indeterminate')
            self.assertEqual(p.run(lambda: 'ok'), 'ok')
        self.assertFalse(p.active)


if __name__ == '__main__':
    unittest.main()
