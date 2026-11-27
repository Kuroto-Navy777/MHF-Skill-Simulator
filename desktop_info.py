"""Local version/settings information. Discovery only; installation remains in the launcher."""
import os
from pathlib import Path

from desktop_safety import atomic_json, read_json, snapshots
from release_check import check, read_config, version_key


def valid_version(value):
    try:
        version_key(value)
        return value
    except ValueError:
        return None


def release_root(root):
    return root.parent if root.name == 'app' and (root.parent / 'MHFSimulator.exe').is_file() else root


def launcher_version(root):
    # Only report the launcher's version when supplied by the process that started this app.
    if release_root(root) == root:
        return None
    return valid_version(os.environ.get('MHF_RUNNING_LAUNCHER_VERSION'))


def information(root, profile):
    source = release_root(root)
    app = valid_version((root / 'VERSION').read_text(encoding='utf-8').strip())
    try:
        config = read_config(source)
        config_error = False
    except (OSError, ValueError):
        config, config_error = {}, True
    rows = read_json(profile / 'update_history.json', [])
    history = []
    if isinstance(rows, list):
        for row in rows[:30]:
            if isinstance(row, dict):
                history.append({k: str(row.get(k, ''))[:100] for k in ('at', 'version', 'status')})
    folder = profile / 'backups'
    return {'app': app, 'launcher': launcher_version(root), 'portable': source != root,
            'channel': config.get('channel'), 'startup': config.get('check_on_startup'),
            'config_error': config_error, 'history': history, 'backups': len(snapshots(folder)),
            'checkpoint': (folder / 'before-update.json').is_file(),
            'previous_app': (source / '.app_previous' / 'VERSION').is_file(),
            'previous_launcher': (source / '.launcher_previous.exe').is_file()}


def configure(root, startup, channel):
    # Preserve the existing repository; do not expose arbitrary paths or update URLs to the UI.
    if type(startup) is not bool or channel not in ('stable', 'preview'):
        raise ValueError('Invalid update settings')
    source = release_root(root)
    config = read_config(source)
    config.update(check_on_startup=startup, channel=channel)
    atomic_json(source / 'release_source.json', config)
    return True


def discover(root, fetch_check=check):
    # Discovery is not a signature verification or permission to install. The launcher does both.
    result = fetch_check(release_root(root), launcher_current=launcher_version(root))
    return {k: result[k] for k in ('status', 'current', 'version', 'detail') if k in result}
