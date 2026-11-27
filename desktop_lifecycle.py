"""Windows single-instance, startup and tray lifecycle. No game interaction."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading

LOG = logging.getLogger(__name__)
APP_ID = 'MHFSkillSimulator.Desktop'
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def set_app_id():
    # Keep a consistent taskbar identity; the dedicated EXE is a later step.
    if os.name == 'nt':
        set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [wintypes.LPCWSTR]
        set_id.restype = ctypes.c_long
        set_id(APP_ID)


class SingleInstance:
    """Session-local kernel objects disappear when the last handle closes."""
    def __init__(self, profile):
        # Scope to the stable profile, not the installation directory.
        key = hashlib.sha256(str(profile.resolve()).casefold().encode()).hexdigest()[:24]
        self.name = 'Local\\MHFSimulator-' + key
        self.event = self.mutex = None
        self.primary = False

    def __enter__(self):
        k = self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, types, result in (
            ('CreateEventW', [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('CreateMutexW', [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('SetEvent', [wintypes.HANDLE], wintypes.BOOL),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
        ):
            f = getattr(k, name)
            f.argtypes, f.restype = types, result
        try:
            # Create the auto-reset event first, so activation cannot be lost during startup.
            self.event = k.CreateEventW(None, False, False, self.name + '-show')
            if not self.event:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.set_last_error(0)
            self.mutex = k.CreateMutexW(None, False, self.name + '-lock')
            error = ctypes.get_last_error()
            if not self.mutex:
                raise ctypes.WinError(error)
            self.primary = error != 183
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def activate(self):
        if not self.k.SetEvent(self.event):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait(self, timeout_ms=1000):
        result = self.k.WaitForSingleObject(self.event, timeout_ms)
        if result == 0:
            return True
        if result == 258:
            return False
        raise ctypes.WinError(ctypes.get_last_error())

    def __exit__(self, *_):
        for handle in (self.mutex, self.event):
            if handle:
                self.k.CloseHandle(handle)
        self.mutex = self.event = None


class Preferences:
    def __init__(self, path):
        self.path = path
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            self.resident = isinstance(data, dict) and data.get('resident') is True
            self.game_priority = not isinstance(data, dict) or data.get('game_priority') is not False
        except (OSError, ValueError):
            self.resident = False
            self.game_priority = True

    def set_resident(self, enabled):
        self._save(bool(enabled), self.game_priority)

    def set_game_priority(self, enabled):
        self._save(self.resident, bool(enabled))

    def _save(self, resident, game_priority):
        # Write both settings atomically; preserve the other preference.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'resident': resident, 'game_priority': game_priority}), encoding='utf-8')
        os.replace(temp, self.path)
        self.resident = resident
        self.game_priority = game_priority


def startup_command(root, executable=None, frozen=None):
    executable = Path(executable or sys.executable).resolve()
    is_frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if is_frozen:
        # The stable launcher remains the login target after payload updates.
        launcher = executable.parent.parent / 'MHFSimulator.exe'
        if executable.name.lower() == 'mhfdesktop.exe' and executable.parent.name == 'app' and launcher.is_file():
            executable = launcher
        return subprocess.list2cmdline([str(executable), '--background'])
    # Use pythonw to avoid a console at sign-in, with the same environment.
    quiet = executable.with_name('pythonw.exe')
    if not quiet.is_file():
        raise FileNotFoundError('pythonw.exe not found. Run setup_desktop.bat first.')
    return subprocess.list2cmdline([str(quiet), str((root / 'desktop.py').resolve()), '--background'])


class Startup:
    def __init__(self, root):
        self.root = root

    def enabled(self):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                value, kind = winreg.QueryValueEx(key, APP_ID)
            return kind == winreg.REG_SZ and value == startup_command(self.root)
        except OSError:
            return False

    def set_enabled(self, enabled):
        import winreg
        if enabled:
            command = startup_command(self.root)
            # Windows Run entries are documented as limited to 260 characters.
            if len(command) > 260:
                raise ValueError('Install path is too long for Windows startup. Move to a shorter path.')
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, APP_ID, 0, winreg.REG_SZ, command)
        else:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                    winreg.DeleteValue(key, APP_ID)
            except FileNotFoundError:
                pass


def report_error(message):
    LOG.error('%s', message)
    if os.name == 'nt':
        ctypes.windll.user32.MessageBoxW(None, str(message), 'MHF Skill Simulator', 0x10)


class TrayController:
    def __init__(self, window, preferences, startup, instance, url, root, background=False):
        self.window, self.preferences, self.startup = window, preferences, startup
        self.instance, self.url, self.root = instance, url, root
        self.background = background
        self.ready, self.stopping = threading.Event(), threading.Event()
        self.icon = self.tray_thread = self.listener = None
        self.exiting = False
        self.minimized = False
        self.release_lock = threading.Lock()

    def closing(self):
        # Never trap the user in an invisible app if the tray failed to start.
        if not self.exiting and self.preferences.resident and self.ready.is_set():
            self.window.hide()
            if not self.ready.is_set():
                self.window.show()
            return False
        self.stopping.set()
        return True

    def show(self, *_):
        if self.stopping.is_set():
            return
        self.window.show()
        if self.minimized:
            self.window.restore()
        # Best-effort foreground activation; Windows can deny foreground changes.
        try:
            native = self.window.native
            if native is not None:
                from System import Action
                native.BeginInvoke(Action(lambda: native.Activate()))
        except Exception:
            LOG.debug('Native focus unavailable', exc_info=True)

    def on_minimized(self):
        self.minimized = True

    def on_restored(self):
        self.minimized = False

    def quit(self, *_):
        self.exiting = True
        self.stopping.set()
        self.window.destroy()

    def toggle_resident(self, *_):
        try:
            self.preferences.set_resident(not self.preferences.resident)
        except (OSError, ValueError) as exc:
            report_error(exc)

    def toggle_game_priority(self, *_):
        try:
            self.preferences.set_game_priority(not self.preferences.game_priority)
        except (OSError, ValueError) as exc:
            report_error(exc)

    def toggle_startup(self, *_):
        try:
            self.startup.set_enabled(not self.startup.enabled())
        except (OSError, ValueError) as exc:
            report_error(exc)

    def browser(self, *_):
        import webbrowser
        webbrowser.open(self.url)

    def check_release(self, *_ , automatic=False):
        # Do network I/O outside the GUI and tray callback threads.
        if self.stopping.is_set() or not self.release_lock.acquire(blocking=False):
            return

        def run():
            try:
                from release_check import check, read_config
                if automatic and not read_config(self.release_root())['check_on_startup']:
                    return
                result = check(self.release_root())
                if self.stopping.is_set():
                    return
                status = result['status']
                if automatic:
                    if status == 'available' and self.ready.is_set() and self.icon:
                        self.icon.notify('Version ' + result['version'] + ' が利用可能です。トレイの更新確認から開けます。',
                                         'MHF Skill Simulator')
                    return
                if status == 'available':
                    # The portable launcher performs signed updates on the next foreground launch.
                    if getattr(sys, 'frozen', False) and self.root.name == 'app' and (self.root.parent / 'MHFSimulator.exe').is_file():
                        ctypes.windll.user32.MessageBoxW(None, '最新版: ' + result['version'] + '\n完全終了して再起動すると更新できます。', 'MHF Skill Simulator', 0x40)
                        return
                    # Source edition still opens the validated release page, with consent.
                    message = ('最新版: ' + result['version'] + '\n現在: ' + result['current']
                               + '\nGitHubの配布ページを開きますか？')
                    if ctypes.windll.user32.MessageBoxW(None, message, 'MHF Skill Simulator', 0x24) == 6:
                        import webbrowser
                        webbrowser.open(result['release_url'])
                else:
                    messages = {'unconfigured': '配布先が未設定です。release_source.json を確認してください。',
                                'no_compatible_release': '現在より新しい対応済み配布ファイルは見つかりませんでした。',
                                'unavailable': '更新情報を取得できません。現在のバージョンを利用できます。'}
                    ctypes.windll.user32.MessageBoxW(None, messages[status], 'MHF Skill Simulator', 0x40)
            except Exception:
                LOG.exception('Release check failed')
            finally:
                self.release_lock.release()

        try:
            threading.Thread(target=run, daemon=True).start()
        except BaseException:
            self.release_lock.release()
            raise

    def release_root(self):
        # A portable install has its authoritative settings beside the stable launcher.
        return self.root.parent if self.root.name == 'app' and (self.root.parent / 'MHFSimulator.exe').is_file() else self.root

    def auto_update_enabled(self):
        from release_check import read_config
        try:
            return read_config(self.release_root())['check_on_startup']
        except (OSError, ValueError):
            return False

    def toggle_auto_update(self, *_):
        from release_check import read_config
        from desktop_safety import atomic_json
        try:
            root = self.release_root()
            config = read_config(root)
            config['check_on_startup'] = not config['check_on_startup']
            atomic_json(root / 'release_source.json', config)
        except (OSError, ValueError) as exc:
            report_error(exc)

    def open_backups(self, *_):
        folder = self.preferences.path.parent / 'backups'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def request_rollback(self, *_):
        # Only the stable launcher can swap the closed payload. Apply on the next launch.
        root = self.release_root()
        previous = root / '.app_previous' / 'VERSION'
        if not previous.is_file() or (root / '.update_pending').exists():
            return
        try:
            version = previous.read_text(encoding='utf-8').strip()
            prompt = f'旧版 {version} に戻しますか？ 完全終了後、次の起動時に適用されます。保存データは自動で巻き戻しません。'
            if ctypes.windll.user32.MessageBoxW(None, prompt, 'MHF Skill Simulator', 0x24) == 6:
                from desktop_safety import atomic_json
                atomic_json(root / '.rollback_requested', {'requested': True})
        except (OSError, ValueError) as exc:
            report_error(exc)

    def show_update_history(self, *_):
        from desktop_safety import read_json
        rows = read_json(self.preferences.path.parent / 'update_history.json', [])
        rows = rows if isinstance(rows, list) else []
        labels = {'installed': '更新成功', 'rollback': '旧版へ復元'}
        lines = [f"{row.get('at', '')[:19]} UTC  {row.get('version', '')}  {labels.get(row.get('status'), row.get('status', ''))}" for row in rows[:15] if isinstance(row, dict)]
        ctypes.windll.user32.MessageBoxW(None, '\n'.join(lines) or '更新履歴はまだありません。', 'MHF Skill Simulator', 0x40)

    def _listen(self):
        while not self.stopping.is_set():
            try:
                if self.instance.wait() and not self.stopping.is_set():
                    self.show()
            except Exception:
                LOG.exception('Activation listener stopped')
                break

    def _tray_loop(self):
        try:
            import pystray
            from PIL import Image
            with Image.open(self.root / 'web' / 'favicon.ico') as source:
                image = source.convert('RGBA')
            item = pystray.MenuItem
            menu = pystray.Menu(
                item('シミュレーターを開く / Open', self.show, default=True),
                item('ブラウザで開く / Browser', self.browser),
                item('更新を確認 / Check for updates', self.check_release),
                item('起動時に更新を確認 / Check on startup', self.toggle_auto_update, checked=lambda _: self.auto_update_enabled()),
                item('更新履歴 / Update history', self.show_update_history),
                item('旧版に戻す（次回起動） / Roll back on next launch', self.request_rollback,
                     enabled=lambda _: (self.release_root() / '.app_previous' / 'VERSION').is_file() and not (self.release_root() / '.update_pending').exists()),
                item('バックアップフォルダ / Backups', self.open_backups),
                pystray.Menu.SEPARATOR,
                item('ゲーム優先（次の検索から） / Game priority', self.toggle_game_priority,
                     checked=lambda _: self.preferences.game_priority),
                item('閉じると常駐 / Keep in tray', self.toggle_resident,
                     checked=lambda _: self.preferences.resident),
                item('Windowsログイン時に起動 / Start at login', self.toggle_startup,
                     checked=lambda _: self.startup.enabled()),
                pystray.Menu.SEPARATOR,
                item('完全終了 / Exit', self.quit),
            )
            self.icon = pystray.Icon(APP_ID, image, 'MHF-ZZ Skill Simulator', menu)

            def setup(icon):
                if self.stopping.is_set():
                    icon.stop()
                    return
                icon.visible = True
                self.ready.set()
                # The portable launcher already checks before starting the desktop.
                if not (getattr(sys, 'frozen', False) and self.root.name == 'app' and (self.root.parent / 'MHFSimulator.exe').is_file()):
                    self.check_release(automatic=True)

            self.icon.run(setup=setup)
        except Exception:
            LOG.exception('Tray unavailable; close will exit normally')
        finally:
            self.ready.clear()
            if not self.stopping.is_set():
                # If the tray disappears after hiding, recover the window.
                self.show()

    def start(self):
        # pywebview invokes this on a worker after GUI initialization.
        self.tray_thread = threading.Thread(target=self._tray_loop, daemon=True)
        self.tray_thread.start()
        if self.background and self.ready.wait(5) and not self.stopping.is_set():
            self.window.hide()
            if not self.ready.is_set():
                self.window.show()
        if not self.stopping.is_set():
            self.listener = threading.Thread(target=self._listen, daemon=True)
            self.listener.start()

    def stop(self):
        self.stopping.set()
        if self.icon is not None:
            self.icon.stop()
        if self.listener is not None:
            self.listener.join(timeout=2)
        if self.tray_thread is not None:
            self.tray_thread.join(timeout=3)
