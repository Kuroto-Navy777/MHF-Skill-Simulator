"""Phase 11B controller regression tests; native integration is Windows-only."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_lifecycle import Preferences, TrayController, startup_command, SingleInstance


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pref = Preferences(self.root / 'settings.json')
        self.window = Mock(native=None)
        self.startup = Mock()
        self.instance = Mock()
        self.ctrl = TrayController(self.window, self.pref, self.startup, self.instance,
                                   'http://127.0.0.1:8765/', self.root)

    def test_default_close_exits(self):
        self.ctrl.ready.set()
        self.assertTrue(self.ctrl.closing())
        self.assertTrue(self.ctrl.stopping.is_set())
        self.window.hide.assert_not_called()

    def test_resident_close_hides_and_show_restores(self):
        self.pref.set_resident(True)
        self.ctrl.ready.set()
        self.assertFalse(self.ctrl.closing())
        self.assertFalse(self.ctrl.stopping.is_set())
        self.window.hide.assert_called_once()
        self.ctrl.on_minimized()
        self.ctrl.show()
        self.window.show.assert_called_once()
        self.window.restore.assert_called_once()

    def test_tray_unavailable_close_does_not_hide(self):
        self.pref.set_resident(True)
        self.assertTrue(self.ctrl.closing())
        self.window.hide.assert_not_called()

    def test_quit_bypasses_residence(self):
        self.pref.set_resident(True)
        self.ctrl.ready.set()
        self.ctrl.quit()
        self.window.destroy.assert_called_once()
        self.assertTrue(self.ctrl.closing())
        self.window.hide.assert_not_called()

    def test_preferences_persist_and_corrupt_defaults(self):
        self.ctrl.toggle_resident()
        self.assertTrue(Preferences(self.pref.path).resident)
        self.ctrl.toggle_resident()
        self.assertFalse(Preferences(self.pref.path).resident)
        self.pref.path.write_text('broken', encoding='utf-8')
        self.assertFalse(Preferences(self.pref.path).resident)

    def test_preferences_write_failure_keeps_state(self):
        with patch('desktop_lifecycle.os.replace', side_effect=PermissionError('test')):
            with self.assertRaises(PermissionError):
                self.pref.set_resident(True)
        self.assertFalse(self.pref.resident)

    def test_startup_menu_toggle(self):
        self.startup.enabled.return_value = False
        self.ctrl.toggle_startup()
        self.startup.set_enabled.assert_called_once_with(True)
        self.startup.enabled.return_value = True
        self.ctrl.toggle_startup()
        self.startup.set_enabled.assert_called_with(False)

    def test_startup_command_quotes_spaces(self):
        folder = self.root / 'MHF Test'
        folder.mkdir()
        exe = folder / 'python.exe'
        exe.with_name('pythonw.exe').touch()
        command = startup_command(folder, exe, frozen=False)
        self.assertEqual(command, f'"{folder / "pythonw.exe"}" "{folder / "desktop.py"}" --background')
        self.assertEqual(startup_command(folder, folder / 'MHFSimulator.exe', frozen=True),
                         f'"{folder / "MHFSimulator.exe"}" --background')

    def test_activation_listener_dispatches(self):
        def wait():
            return True
        self.instance.wait.side_effect = wait
        with patch.object(self.ctrl, 'show', side_effect=self.ctrl.stopping.set) as show:
            self.ctrl._listen()
        show.assert_called_once()

    def test_stop_prevents_show(self):
        self.ctrl.stopping.set()
        self.ctrl.show()
        self.window.show.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows kernel integration')
    def test_native_single_instance_signal(self):
        with SingleInstance(self.root) as first:
            self.assertTrue(first.primary)
            with SingleInstance(self.root) as second:
                self.assertFalse(second.primary)
                second.activate()
                self.assertTrue(first.wait(1000))
                self.assertFalse(first.wait(0))
        with SingleInstance(self.root) as again:
            self.assertTrue(again.primary)


if __name__ == '__main__':
    unittest.main()
