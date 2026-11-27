"""Regression tests for a taskbar shortcut that points to the desktop payload."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_entry import main, pinned_launcher_command, redirect_pinned_launch


class TaskbarLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='MHF Test ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.exe = self.root / 'app' / 'MHFDesktop.exe'
        self.exe.parent.mkdir()
        self.exe.touch()
        self.launcher = self.root / 'MHFSimulator.exe'
        self.launcher.touch()

    def test_pinned_payload_redirects(self):
        self.assertEqual(pinned_launcher_command([], self.exe, True), [str(self.launcher)])

    def test_background_redirects(self):
        self.assertEqual(pinned_launcher_command(['--background'], self.exe, True),
                         [str(self.launcher), '--background'])

    def test_launcher_supplied_db_does_not_loop(self):
        for args in (['--db', 'db.sqlite'], ['--db', 'db.sqlite', '--background']):
            self.assertIsNone(pinned_launcher_command(args, self.exe, True))

    def test_worker_and_smoke_unchanged(self):
        for args in (['--self-test', '--report', 'test.json'], ['--search-worker']):
            self.assertIsNone(pinned_launcher_command(args, self.exe, True))

    def test_source_and_legacy_executable_unchanged(self):
        self.assertIsNone(pinned_launcher_command([], self.exe, False))
        self.assertIsNone(pinned_launcher_command([], self.launcher, True))

    def test_missing_launcher_has_clear_error(self):
        self.launcher.unlink()
        with self.assertRaisesRegex(FileNotFoundError, 'Extract the complete portable ZIP'):
            pinned_launcher_command([], self.exe, True)

    def test_spawn_uses_absolute_path_and_independent_environment(self):
        with patch('desktop_entry.pinned_launcher_command', return_value=[str(self.launcher)]), \
             patch('desktop_entry.subprocess.Popen') as spawn:
            self.assertTrue(redirect_pinned_launch([]))
            args, kwargs = spawn.call_args
            self.assertEqual(args[0], [str(self.launcher)])
            self.assertEqual(kwargs['cwd'], str(self.root))
            self.assertEqual(kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_main_does_not_start_second_gui(self):
        with patch('desktop_entry.redirect_pinned_launch', return_value=True), \
             patch('desktop.main') as gui:
            self.assertEqual(main([]), 0)
            gui.assert_not_called()


if __name__ == '__main__':
    unittest.main()
