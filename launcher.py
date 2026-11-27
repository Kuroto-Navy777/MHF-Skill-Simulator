"""Stable Windows launch target. Update the closed application payload before starting it."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from desktop_lifecycle import SingleInstance, report_error
from release_check import check, read_config, version_key
from update_core import REPOSITORY, recover, update
from desktop_safety import checkpoint, read_json, record_history
from functools import partial
from launcher_update import read_signed_candidate, stage_handoff, helper_main, launcher_metadata, HANDOFF

LOG = logging.getLogger('launcher')


def public_key():
    # The optional build-time key is bundled in the launcher executable.
    if not getattr(sys, 'frozen', False):
        return None
    path = Path(sys._MEIPASS) / 'update_public_key.bin'
    if not path.is_file():
        return None
    value = path.read_bytes()
    if len(value) != 32:
        raise ValueError('Invalid embedded signing key')
    return value


def launcher_version():
    # Embedded separately from the application VERSION so a newer app cannot hide an old launcher.
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
    value = (base / 'VERSION').read_text(encoding='utf-8').strip()
    version_key(value)
    return value


def launcher_smoke(executable, version, key):
    with tempfile.TemporaryDirectory(prefix='mhf-launcher-smoke-') as temp:
        report = Path(temp) / 'report.json'
        reset_dll_path()
        subprocess.run([str(executable), '--launcher-self-test', str(report)],
                       check=True, timeout=90, cwd=executable.parent, env=child_env())
        result = read_json(report)
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('frozen') is not True or result.get('startup_gui') is not True
                or result.get('version') != version
                or result.get('public_key_sha256') != hashlib.sha256(key).hexdigest()):
            raise ValueError('New launcher self-test failed')


def spawn_helper(executable):
    reset_dll_path()
    child = subprocess.Popen([str(executable), '--launcher-handoff'], cwd=executable.parent, env=child_env())
    # Wait for the helper to acquire its handoff guard before releasing the launcher mutex.
    deadline = time.monotonic()+45
    while time.monotonic() < deadline:
        if (executable.parent / 'helper-ready').is_file():
            return
        if child.poll() is not None:
            raise RuntimeError('Launcher helper exited before handoff')
        time.sleep(.1)
    raise TimeoutError('Launcher helper did not initialize')


def child_env():
    # Independent frozen child processes must not inherit the launcher's extraction directory.
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    return env


def reset_dll_path():
    if os.name == 'nt':
        ctypes.windll.kernel32.SetDllDirectoryW(None)


def smoke(payload):
    # Run the new binary before and after committing; no user profile or DB mutation.
    with tempfile.TemporaryDirectory(prefix='mhf-smoke-') as temp:
        report = Path(temp) / 'smoke.json'
        reset_dll_path()
        subprocess.run([str(payload / 'MHFDesktop.exe'), '--self-test', '--report', str(report)],
                       check=True, timeout=90, cwd=payload, env=child_env())
        result = json.loads(report.read_text(encoding='utf-8'))
        if result.get('ok') is not True or result.get('frozen') is not True:
            raise RuntimeError('Updated application self-test failed')


def signal_desktop(profile):
    # Open the existing activation event without creating the application's mutex.
    key = hashlib.sha256(str(profile.resolve()).casefold().encode()).hexdigest()[:24]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenEventW.restype = wintypes.HANDLE
    kernel.SetEvent.argtypes = [wintypes.HANDLE]
    kernel.SetEvent.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenEventW(2, False, 'Local\\MHFSimulator-' + key + '-show')
    if not handle:
        return False
    try:
        return bool(kernel.SetEvent(handle))
    finally:
        kernel.CloseHandle(handle)


def prepare(root, key, smoke_fn=smoke, check_fn=check, update_fn=update, profile_root=None):
    recover(root)
    config = read_config(root)
    if not key or not config['check_on_startup'] or config['repository'] != REPOSITORY:
        return 'disabled'
    LOG.info('Startup: checking releases')
    candidate = check_fn(root)
    if candidate['status'] != 'available':
        return candidate['status']
    try:
        if profile_root is not None:
            rows = read_json(profile_root / 'update_history.json', [])
            if isinstance(rows, list) and any(isinstance(row, dict) and row.get('version') == candidate['version'] and row.get('status') == 'rollback' for row in rows):
                return 'blocked_after_rollback'
            checkpoint(profile_root / 'backups')
        return update_fn(root, candidate, key, smoke_fn)
    except Exception:
        LOG.exception('Update failed; continuing with installed version')
        recover(root)
        return 'failed'


def wait_for_ready(child, report, tick, timeout=90):
    # A successful import-only smoke test is not proof that the actual UI can open.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if read_json(report) == {'ready': True}:
            return True
        if child.poll() is not None:
            return False
        tick()
    return False


def rollback_pending(root, profile_root):
    # Preserve the old installation even if writing the optional history fails.
    version = (root / 'app' / 'VERSION').read_text().strip()
    recover(root)
    try:
        record_history(profile_root, 'rollback', version)
    except OSError:
        LOG.exception('Could not write rollback history')
    LOG.warning('Rolled back %s', version)


def manual_rollback(root, profile_root):
    request = root / '.rollback_requested'
    if not request.is_file():
        return False
    if not (root / '.app_previous' / 'VERSION').is_file():
        request.unlink()
        return False
    # Reuse the same crash-recoverable swap, only while the desktop is closed.
    marker = root / '.update_pending'
    with marker.open('w', encoding='ascii') as stream:
        stream.write('manual rollback\n')
        stream.flush()
        os.fsync(stream.fileno())
    rollback_pending(root, profile_root)
    request.unlink(missing_ok=True)
    return True


def start_payload(root, db, args, instance, profile, pending, progress=None, startup_message=None):
    # The readiness file is private to this launch. Older payloads need no new argument.
    payload = root / 'app'
    with tempfile.TemporaryDirectory(prefix='mhf-start-') as temp:
        report = Path(temp) / 'ready.json'
        command = [str(payload / 'MHFDesktop.exe'), '--db', str(db), *args]
        # RC1+ payloads already support the readiness report. Keep the original pending-only
        # behavior for background launches and callers without a foreground splash.
        observe = pending or (progress is not None and progress.active)
        if observe:
            command += ['--startup-report', str(report)]
        if progress is not None:
            progress.show(startup_message or 'データベースと画面を読み込んでいます…')
        reset_dll_path()
        try:
            # Report the actual running launcher version, not the app's VERSION.
            env = child_env()
            env['MHF_RUNNING_LAUNCHER_VERSION'] = launcher_version()
            child = subprocess.Popen(command, cwd=payload, env=env)
        except OSError:
            if not pending:
                raise
            LOG.exception('Updated executable failed to start')
            if progress is not None:
                progress.show('旧バージョンに復元しています…')
                progress.run(rollback_pending, root, profile.parent)
            else:
                rollback_pending(root, profile.parent)
            return start_payload(root, db, args, instance, profile, False, progress)
        pending_show = False

        def tick():
            nonlocal pending_show
            if progress is not None:
                progress.pump()
            if instance.wait(100 if progress is not None and progress.active else 1000):
                pending_show = True
            if pending_show and signal_desktop(profile):
                pending_show = False

        if observe:
            version = (payload / 'VERSION').read_text().strip()
            try:
                ready = wait_for_ready(child, report, tick)
            except Exception:
                LOG.exception('Startup acknowledgement failed')
                ready = False
            if not ready and pending:
                # Never swap a running executable. If termination fails, retain the pending marker.
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=10)
                if progress is not None:
                    progress.show('旧バージョンに復元しています…')
                    progress.run(rollback_pending, root, profile.parent)
                else:
                    rollback_pending(root, profile.parent)
                return start_payload(root, db, args, instance, profile, False, progress)
            if pending:
                (root / '.update_pending').unlink()
                try:
                    record_history(profile.parent, 'installed', version)
                except OSError:
                    LOG.exception('Could not write update history')
            elif not ready:
                # An ordinary startup timeout is not an update failure; do not kill the app.
                LOG.warning('Normal startup readiness not acknowledged')
        if progress is not None:
            progress.close()
        while child.poll() is None:
            tick()
        return child.returncode


def interactive_update(root, profile_root, progress, key, current_launcher, accepted=None,
                       check_fn=check, manifest_fn=read_signed_candidate, stage_fn=stage_handoff,
                       update_fn=update):
    # Discover once, authenticate the manifest, then ask before downloading/installing anything.
    config = read_config(root)
    if not key or not config['check_on_startup'] or config['repository'] != REPOSITORY:
        return 'disabled'
    current_app = (root / 'app' / 'VERSION').read_text(encoding='utf-8').strip()
    baseline = min((current_app, current_launcher), key=version_key)
    LOG.info('Startup: checking releases')
    candidate = progress.run(check_fn, root, launcher_current=current_launcher)
    if candidate['status'] != 'available':
        return candidate['status']
    version = candidate['version']
    rows = read_json(profile_root / 'update_history.json', [])
    if isinstance(rows, list) and any(isinstance(row, dict) and row.get('version') == version and row.get('status') == 'rollback' for row in rows):
        return 'blocked_after_rollback'
    with tempfile.TemporaryDirectory(prefix='mhf-update-consent-') as temp:
        folder = Path(temp)
        LOG.info('Update: checking signed manifest')
        data = progress.run(manifest_fn, candidate, key, baseline, folder)
        launcher_needed = launcher_metadata(data) is not None and version_key(version) > version_key(current_launcher)
        app_needed = version_key(version) > version_key(current_app)
        if not launcher_needed and not app_needed:
            return 'no_compatible_release'
        if accepted != version and not progress.confirm_update(version, launcher_needed, app_needed):
            return 'deferred'
        progress.run(checkpoint, profile_root / 'backups')
        if launcher_needed:
            # Restart into the signed launcher first; it will apply the app update without a second prompt.
            progress.run(stage_fn, root, folder, candidate, data, key, launcher_smoke, spawn_helper)
            return 'launcher_handoff'
        return progress.run(update_fn, root, candidate, key, smoke, defer_commit=True)


def main():
    if os.name != 'nt' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Build and run the Windows portable launcher')
    args = sys.argv[1:]
    # Test the frozen launcher without opening a window or accessing the network.
    if len(args) == 2 and args[0] == '--launcher-self-test':
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = Ed25519PrivateKey.generate()
        key.public_key().verify(key.sign(b'smoke'), b'smoke')
        # Fail the build if Tcl/Tk was not bundled correctly. No visible window is required.
        import tkinter as tk
        from tkinter import ttk
        probe = tk.Tk()
        try:
            probe.withdraw()
            ttk.Progressbar(probe)
            probe.update_idletasks()
        finally:
            probe.destroy()
        pinned = public_key()
        Path(args[1]).write_text(json.dumps({'ok': True, 'frozen': True,
            'startup_gui': True, 'version': launcher_version(),
            'public_key_sha256': hashlib.sha256(pinned).hexdigest() if pinned else None}), encoding='utf-8')
        return 0
    profile = Path(os.environ['LOCALAPPDATA']) / 'MHFSkillSimulator' / 'WebView2'
    profile.parent.mkdir(parents=True, exist_ok=True)
    if args == ['--launcher-handoff']:
        return helper_main(Path(sys.executable).resolve(), public_key(), launcher_version(), profile, reset_dll_path, child_env)
    accepted = None
    skip_update = args == ['--skip-update-once']
    if len(args) == 1 and args[0].startswith('--accepted-update='):
        accepted = args[0].split('=', 1)[1]
        version_key(accepted)
    elif args not in ([], ['--background'], ['--skip-update-once']):
        raise ValueError('Unknown launcher arguments')
    args = ['--background'] if args == ['--background'] else []
    root = Path(sys.executable).resolve().parent
    logging.basicConfig(filename=str(profile.parent / 'launcher.log'), level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    if not accepted and not skip_update:
        with SingleInstance(profile.parent / 'LauncherHandoff') as handoff:
            if not handoff.primary:
                return 0
    with SingleInstance(profile.parent / 'Launcher') as instance:
        if not instance.primary:
            if '--background' not in args:
                instance.activate()
            return 0
        # Do not replace files when an independently launched desktop is still running.
        with SingleInstance(profile) as desktop:
            if not desktop.primary:
                if '--background' not in args:
                    desktop.activate()
                return 0
        from update_progress import StartupProgress
        with StartupProgress(root, enabled='--background' not in args) as progress:
            # Acknowledge that the new launcher has initialized before the old helper exits.
            if accepted and (root / HANDOFF).is_dir():
                (root / HANDOFF / 'ready.json').write_text('ready', encoding='ascii')
            def recover_startup():
                LOG.info('Startup: recovering')
                if (root / '.update_pending').exists() and (root / '.app_previous' / 'VERSION').is_file() and (root / 'app' / 'VERSION').is_file():
                    LOG.info('Startup: rollback')
                    record_history(profile.parent, 'rollback', (root / 'app' / 'VERSION').read_text().strip())
                recover(root)
                return manual_rollback(root, profile.parent)

            try:
                if progress.run(recover_startup):
                    status = 'manual_rollback'
                elif skip_update or '--background' in args or not progress.active:
                    status = 'deferred'
                else:
                    status = interactive_update(root, profile.parent, progress, public_key(),
                                                launcher_version(), accepted)
            except Exception:
                LOG.exception('Update configuration or recovery failed')
                recover(root)
                status = 'failed'
            if status == 'launcher_handoff':
                # The helper waits for this process and the PyInstaller parent to exit.
                return 0
            LOG.info('Update status: %s', status)
            message = None
            if status in ('delta', 'full'):
                message = '更新を適用しました。データベースと画面を読み込んでいます…'
            elif status in ('failed', 'unavailable', 'blocked_after_rollback'):
                message = '更新を確認できなかったため、保存済みの版を起動します…'
            elif status == 'deferred':
                message = '現在のバージョンを起動しています…'
            elif status == 'manual_rollback':
                message = '旧バージョンを復元しました。画面を読み込んでいます…'
            db = root / 'mhf_master.sqlite'
            if not db.is_file():
                db = root / 'mhf.sqlite'
            if not db.is_file():
                raise FileNotFoundError('mhf_master.sqlite not found next to MHFSimulator.exe')
            return start_payload(root, db, args, instance, profile, (root / '.update_pending').exists(), progress, message)



if __name__ == '__main__':
    try:
        from installer_guard import installer_guard
        with installer_guard():
            raise SystemExit(main())
    except Exception as exc:
        report_error(f'Launcher error: {exc}')
        raise SystemExit(1)
