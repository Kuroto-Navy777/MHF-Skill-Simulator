"""Read-only GitHub Releases discovery. No downloads, installation or execution."""
import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from runtime_paths import app_root

MAX_RESPONSE = 2 * 1024 * 1024
VERSION_RE = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-(alpha|beta|rc)\.(0|[1-9][0-9]*))?')
REPO_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}')


def version_key(value):
    # Support the project's stable and numbered alpha/beta/rc release tags only.
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError('Invalid release version')
    match = VERSION_RE.fullmatch(value)
    if not match:
        raise ValueError('Invalid release version: ' + value)
    major, minor, patch, stage, number = match.groups()
    return (int(major), int(minor), int(patch), {'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[stage], int(number or 0))


def read_config(root):
    path = root / 'release_source.json'
    if not path.exists():
        return {'repository': None, 'channel': 'stable', 'check_on_startup': False}
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict):
        raise ValueError('Invalid release source configuration')
    repo = data.get('repository')
    if repo is not None and (not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or repo.split('/')[1] in ('.', '..')):
        raise ValueError('Repository must be owner/repository')
    channel = data.get('channel', 'stable')
    startup = data.get('check_on_startup', True)
    if channel not in ('stable', 'preview') or type(startup) is not bool:
        raise ValueError('Invalid release channel or startup setting')
    return {'repository': repo, 'channel': channel, 'check_on_startup': startup}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Metadata requests must stay on the configured GitHub API endpoint.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected GitHub API redirect')


def fetch_json(url):
    request = urllib.request.Request(url, headers={'Accept': 'application/vnd.github+json',
                                     'User-Agent': 'MHFSkillSimulator-ReleaseCheck',
                                     'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=4) as response:
        raw = response.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError('GitHub response too large')
    return json.loads(raw)


def select_release(repo, channel, current, releases):
    # Require an exact portable no-DB asset, uploaded state, matching URL and SHA-256.
    baseline = version_key(current)
    candidates = []
    for release in releases:
        if not isinstance(release, dict) or release.get('draft') is not False:
            continue
        tag = release.get('tag_name')
        if not isinstance(tag, str) or not tag.startswith('v'):
            continue
        version = tag[1:]
        try:
            key = version_key(version)
        except ValueError:
            continue
        preview = key[3] != 3
        if release.get('prerelease') is not preview or (preview and channel == 'stable'):
            continue
        if key <= baseline:
            continue
        name = f'MHF_SkillSimulator_{version}_win_x64_no_DB.zip'
        url = f'https://github.com/{repo}/releases/download/{tag}/{name}'
        assets = release.get('assets')
        if not isinstance(assets, list):
            continue
        matches = [a for a in assets if isinstance(a, dict) and a.get('name') == name]
        if len(matches) != 1:
            continue
        a = matches[0]
        digest, size = a.get('digest'), a.get('size')
        if (a.get('state') != 'uploaded' or a.get('browser_download_url') != url
                or not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', digest)
                or type(size) is not int or not 0 < size <= 2 * 1024**3):
            continue
        candidates.append((key, {'status': 'available', 'current': current, 'version': version,
                                  'asset': name, 'size': size, 'sha256': digest[7:],
                                  'url': url, 'release_url': f'https://github.com/{repo}/releases/tag/{tag}'}))
    if candidates:
        return max(candidates, key=lambda x: x[0])[1]
    return {'status': 'no_compatible_release', 'current': current}


def check(root, fetch=fetch_json, launcher_current=None):
    # Fail closed, but let the caller continue to use the installed simulator offline.
    try:
        config = read_config(root)
        version_file = root / 'app' / 'VERSION' if (root / 'app' / 'VERSION').is_file() else root / 'VERSION'
        current = version_file.read_text(encoding='utf-8').strip()
        version_key(current)
        if launcher_current is not None and version_key(launcher_current) < version_key(current):
            current = launcher_current
        repo = config['repository']
        if not repo:
            return {'status': 'unconfigured', 'current': current}
        prefix = f'https://api.github.com/repos/{repo}/releases'
        if config['channel'] == 'stable':
            try:
                releases = [fetch(prefix + '/latest')]
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return {'status': 'unavailable', 'current': current, 'detail': 'Repository or stable release not found'}
                raise
        else:
            # Preview discovery is bounded to the most recent 100 releases.
            releases = fetch(prefix + '?per_page=100')
            if not isinstance(releases, list):
                raise ValueError('Invalid GitHub release list')
        return select_release(repo, config['channel'], current, releases)
    except (OSError, ValueError, TypeError) as exc:
        return {'status': 'unavailable', 'detail': str(exc)[:300]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=app_root())
    args = parser.parse_args()
    print(json.dumps(check(args.root), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
