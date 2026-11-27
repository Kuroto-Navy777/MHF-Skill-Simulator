"""Signed launcher handoff. The current launcher never overwrites its own running EXE."""
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

from release_check import version_key
from update_core import (MAX_MANIFEST, digest, fetch_asset, verify_manifest,
                         validate_blob, REPOSITORY)

LOG = logging.getLogger('launcher')
MIN_VERSION = '1.1.0-rc.4'
HANDOFF = '.launcher-handoff'


def launcher_asset_name(version):
    version_key(version)
    return f'MHF_Launcher_{version}_win_x64.exe'


def launcher_metadata(data):
    # Legacy releases have no separately signed launcher asset.
    info = data.get('launcher')
    if info is None:
        return None
    if not isinstance(info, dict) or set(info) != {'asset', 'size', 'sha256'}:
        raise ValueError('Invalid launcher metadata')
    validate_blob(info)
    if info['asset'] != launcher_asset_name(data['version']) or info['size'] > 128 * 1024**2:
        raise ValueError('Invalid launcher asset')
    return info


def read_signed_candidate(candidate, key, current, folder, fetch=fetch_asset):
    name = candidate['asset'] + '.update.json'
    raw, sig = folder/'manifest.json', folder/'manifest.sig'
    fetch(candidate['version'], name, raw, MAX_MANIFEST)
    fetch(candidate['version'], name+'.sig', sig, 64)
    data = verify_manifest(raw.read_bytes(), sig.read_bytes(), key, candidate, current)
    launcher_metadata(data)
    return data


def verify_executable(path, info):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != info['size'] or digest(path) != info['sha256']:
        raise ValueError('Launcher integrity failure')
    with path.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Not a Windows launcher executable')


def stage_handoff(root, folder, candidate, data, key, smoke, spawn, fetch=fetch_asset):
    # Verify the new executable and its embedded key/version before starting the trusted helper.
    info = launcher_metadata(data)
    if info is None:
        raise ValueError('No signed launcher asset')
    work = root/HANDOFF
    if work.is_symlink():
        raise ValueError('Invalid handoff path')
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    try:
        for name in ('manifest.json', 'manifest.sig'):
            shutil.copyfile(folder/name, work/name)
        (work/'candidate.json').write_text(json.dumps(candidate), encoding='utf-8')
        LOG.info('Update: downloading launcher')
        next_exe = work/'next.exe'
        fetch(data['version'], info['asset'], next_exe, info['size'], info)
        verify_executable(next_exe, info)
        smoke(next_exe, data['version'], key)
        # The helper is a copy of the already running, trusted launcher, not downloaded code.
        helper = work/'helper.exe'
        shutil.copyfile(root/'MHFSimulator.exe', helper)
        spawn(helper)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def replace_launcher(root, work, info, replace=os.replace, sleep=time.sleep, timeout=40):
    # Keep a complete copy before atomic replacement; never rename the active EXE away first.
    live, incoming = root/'MHFSimulator.exe', work/'next.exe'
    backup, tmp = root/'.launcher_previous.exe', work/'backup.tmp'
    verify_executable(incoming, info)
    if any(p.is_symlink() for p in (live, backup, tmp)) or not live.is_file():
        raise ValueError('Unexpected launcher path')
    shutil.copyfile(live, tmp)
    replace(tmp, backup)
    deadline = time.monotonic()+timeout
    while True:
        try:
            replace(incoming, live)
            break
        except PermissionError:
            # PyInstaller's outer process may still hold the original executable open.
            if time.monotonic() >= deadline:
                raise
            sleep(.25)
    verify_executable(live, info)


def helper_main(executable, key, current, profile, reset_dll_path, child_env):
    from desktop_lifecycle import SingleInstance
    work = executable.parent
    if work.name != HANDOFF or executable.name.lower() != 'helper.exe' or not key:
        raise ValueError('Invalid launcher handoff invocation')
    root = work.parent
    # A separate kernel object spans the gap between launcher processes.
    with SingleInstance(profile.parent/'LauncherHandoff') as handoff:
        if not handoff.primary:
            return 0
        (work/'helper-ready').write_text('ready', encoding='ascii')
        return run_handoff(root, work, key, current, profile, reset_dll_path, child_env)


def run_handoff(root, work, key, current, profile, reset_dll_path, child_env):
    from desktop_lifecycle import SingleInstance
    logging.basicConfig(filename=str(profile.parent/'launcher.log'), level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    from update_progress import StartupProgress
    accepted = None

    def exchange():
        # Revalidate signed metadata and bytes with the old launcher's embedded trust root.
        candidate = json.loads((work/'candidate.json').read_text(encoding='utf-8'))
        data = verify_manifest((work/'manifest.json').read_bytes(), (work/'manifest.sig').read_bytes(), key, candidate, current)
        info = launcher_metadata(data)
        if info is None:
            raise ValueError('Missing signed launcher')
        deadline = time.monotonic()+60
        while True:
            with SingleInstance(profile.parent/'Launcher') as lock:
                if lock.primary:
                    with SingleInstance(profile) as desktop:
                        if not desktop.primary:
                            raise RuntimeError('Desktop is still running')
                        # If another launch already installed the exact signed bytes, do not replace again.
                        live = root/'MHFSimulator.exe'
                        if digest(live) != info['sha256']:
                            replace_launcher(root, work, info)
                        (work/'ready.json').unlink(missing_ok=True)
                        return data['version']
            if time.monotonic() >= deadline:
                raise TimeoutError('Launcher did not exit')
            time.sleep(.2)

    with StartupProgress(root) as progress:
        progress.show('ランチャーを更新しています…')
        try:
            accepted = progress.run(exchange)
            LOG.info('Launcher updated to %s', accepted)
        except Exception:
            LOG.exception('Launcher handoff failed; starting installed launcher')
        # Preserve the original path and taskbar target. Never loop on failed handoff.
        reset_dll_path()
        arg = '--accepted-update='+accepted if accepted else '--skip-update-once'
        def restore_previous():
            # The caller has observed an exit or a spawn failure; never replace a running process.
            with SingleInstance(profile.parent/'Launcher') as lock:
                if lock.primary:
                    with SingleInstance(profile) as desktop:
                        if desktop.primary:
                            backup = root/'.launcher_previous.exe'
                            if backup.is_file():
                                shutil.copyfile(backup, work/'restore.exe')
                                os.replace(work/'restore.exe', root/'MHFSimulator.exe')
                                LOG.warning('New launcher did not start; restored old launcher')
                                from desktop_safety import record_history
                                try:
                                    record_history(profile.parent, 'rollback', accepted)
                                except OSError:
                                    LOG.exception('Could not record launcher rollback history')
                                return True
            return False

        try:
            child = subprocess.Popen([str(root/'MHFSimulator.exe'), arg], cwd=root, env=child_env())
        except OSError:
            if accepted and restore_previous():
                subprocess.Popen([str(root/'MHFSimulator.exe'), '--skip-update-once'], cwd=root, env=child_env())
                return 0
            raise
        if accepted:
            from desktop_safety import record_history
            try:
                record_history(profile.parent, 'launcher_installed', accepted)
            except OSError:
                LOG.exception('Could not record launcher update history')
            progress.show('新しいランチャーを起動しています…')
            # If it exits before acknowledging startup, restore the verified previous executable.
            deadline = time.monotonic()+90
            ready = work/'ready.json'
            while time.monotonic() < deadline:
                if ready.is_file():
                    break
                if child.poll() is not None:
                    if restore_previous():
                        subprocess.Popen([str(root/'MHFSimulator.exe'), '--skip-update-once'], cwd=root, env=child_env())
                    break
                progress.pump()
                time.sleep(.1)
    return 0
