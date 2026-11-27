"""Signed portable app updates. The launcher, database and user profile are never replaced."""
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import time
import urllib.request
from urllib.parse import urlsplit
import zipfile

from release_check import version_key

REPOSITORY = 'Kuroto-Navy777/MHF-Skill-Simulator'
PROTOCOL = 1
MAX_ARCHIVE = 2 * 1024**3
MAX_MANIFEST = 8 * 1024**2
OUTER = 'MHF_SkillSimulator/'
HEX = re.compile(r'[a-f0-9]{64}')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_path(name):
    # Use a strict portable subset; refuse Windows aliases, alternate streams and traversal.
    if not isinstance(name, str) or not name or len(name) > 240 or '\\' in name:
        raise ValueError('Invalid update path')
    parts = name.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part[-1] in '. ' or
                re.search(r'[\x00-\x1f<>:"|?*]', part) or
                re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', part)):
            raise ValueError('Unsafe update path: ' + name)
    if any(p.lower().endswith(('.sqlite', '.sqlite3', '.db', '.key')) for p in parts):
        raise ValueError('Protected data path: ' + name)
    return PurePosixPath(name)


def validate_files(files):
    if not isinstance(files, dict) or not 0 < len(files) <= 40000:
        raise ValueError('Invalid file manifest')
    seen = set()
    for name, info in files.items():
        safe_path(name)
        folded = name.casefold()
        if folded in seen or not isinstance(info, dict) or set(info) != {'size', 'sha256'}:
            raise ValueError('Duplicate path or invalid file metadata')
        seen.add(folded)
        validate_blob(info, allow_empty=True)
    if any(any('/'.join(p.split('/')[:i]) in seen for i in range(1, len(p.split('/')))) for p in seen):
        raise ValueError('File/directory conflict')
    if sum(i['size'] for i in files.values()) > MAX_ARCHIVE:
        raise ValueError('Expanded app too large')
    for required in ('VERSION', 'MHFDesktop.exe', 'web/index.html', 'web/app.js', 'web/favicon.ico'):
        if required not in files:
            raise ValueError('Missing app file: ' + required)


def validate_blob(info, allow_empty=False):
    if (type(info.get('size')) is not int or not (0 if allow_empty else 1) <= info['size'] <= MAX_ARCHIVE
            or not isinstance(info.get('sha256'), str) or not HEX.fullmatch(info['sha256'])):
        raise ValueError('Invalid size or SHA-256')


def verify_manifest(raw, signature, public_key, candidate, current):
    # The trusted Ed25519 public key is embedded in the launcher, not fetched from GitHub.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if len(raw) > MAX_MANIFEST or len(signature) != 64 or len(public_key) != 32:
        raise ValueError('Invalid signature material')
    Ed25519PublicKey.from_public_bytes(public_key).verify(signature, raw)
    data = json.loads(raw)
    if (data['repository'] != REPOSITORY or data['protocol'] != PROTOCOL or
            data['version'] != candidate['version'] or version_key(data['version']) <= version_key(current)):
        raise ValueError('Wrong repository, protocol or version')
    if data['full'] != {k: candidate[k] for k in ('asset', 'size', 'sha256')}:
        raise ValueError('Signed archive differs from GitHub metadata')
    validate_blob(data['full'])
    validate_files(data['files'])
    delta = data.get('delta')
    if delta is not None:
        validate_blob(delta)
        version_key(delta['from'])
        expected = f"MHF_delta_{delta['from']}_to_{data['version']}_win_x64.zip"
        if delta['asset'] != expected or version_key(delta['from']) >= version_key(data['version']):
            raise ValueError('Invalid delta metadata')
    return data


class AssetRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urlsplit(newurl)
        if u.scheme != 'https' or u.netloc not in ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'):
            raise ValueError('Untrusted release redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_asset(version, name, destination, limit, expected=None):
    # Only fixed repository release assets may be requested; limit bytes even if headers lie.
    version_key(version)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
        raise ValueError('Invalid asset name')
    url = f'https://github.com/{REPOSITORY}/releases/download/v{version}/{name}'
    request = urllib.request.Request(url, headers={'User-Agent': 'MHFSkillSimulator-Updater'})
    size = 0
    deadline = time.monotonic() + 180
    last_report = 0.0
    log = logging.getLogger('launcher')
    if expected:
        log.info('Update bytes: %s / %s', 0, expected['size'])
    with urllib.request.build_opener(AssetRedirect()).open(request, timeout=8) as response, destination.open('wb') as out:
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > limit or time.monotonic() > deadline:
                raise ValueError('Release download exceeds size limit')
            out.write(chunk)
            # Report only signed archive sizes, throttled to avoid flooding the UI.
            now = time.monotonic()
            if expected and (now - last_report >= .25 or size == expected['size']):
                log.info('Update bytes: %s / %s', size, expected['size'])
                last_report = now
    if expected:
        log.info('Update: verifying download')
    if expected and (size != expected['size'] or digest(destination) != expected['sha256']):
        raise ValueError('Release download integrity failure')


def inspect_archive(archive, full):
    # Validate every entry before extracting anything. The full package may contain the stable launcher.
    entries = {}
    seen = set()
    total = 0
    for entry in archive.infolist():
        name = entry.filename
        if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
            raise ValueError('Unexpected ZIP entry')
        if full:
            if not name.startswith(OUTER):
                raise ValueError('Invalid portable archive')
            name = name[len(OUTER):]
        safe_path(name)
        if name.casefold() in seen:
            raise ValueError('Duplicate ZIP entry')
        seen.add(name.casefold())
        total += entry.file_size
        if total > MAX_ARCHIVE or len(seen) > 40010:
            raise ValueError('ZIP expansion limit exceeded')
        if full:
            if not name.startswith('app/'):
                if name not in ('MHFSimulator.exe', 'README.txt', 'release_source.json'):
                    raise ValueError('Unexpected outer package file')
                continue
            name = name[4:]
            safe_path(name)
        entries[name] = entry
    return entries


def copy_verified(source, target, info):
    if source.is_symlink() or not source.is_file() or source.stat().st_size != info['size'] or digest(source) != info['sha256']:
        raise ValueError('Delta base file mismatch')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if target.stat().st_size != info['size'] or digest(target) != info['sha256']:
        raise ValueError('Copied file integrity failure')


def stage_payload(archive_path, destination, installed, files, full):
    validate_files(files)
    with zipfile.ZipFile(archive_path) as archive:
        entries = inspect_archive(archive, full)
        if not set(entries) <= set(files) or (full and set(entries) != set(files)):
            raise ValueError('Archive and signed file list differ')
        for name, info in files.items():
            target = destination / safe_path(name)
            if name not in entries:
                # A delta is usable only when every unchanged installed file matches the signed target.
                copy_verified(installed / safe_path(name), target, info)
                continue
            entry = entries[name]
            if entry.file_size != info['size']:
                raise ValueError('Unexpected expanded file size')
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, target.open('xb') as out:
                shutil.copyfileobj(source, out, 1024 * 1024)
            if target.stat().st_size != info['size'] or digest(target) != info['sha256']:
                raise ValueError('Extracted file hash mismatch')


def recover(root):
    # If power was lost during the directory swap, restore the previous app when necessary.
    app, backup = root / 'app', root / '.app_previous'
    if app.is_symlink() or backup.is_symlink():
        raise ValueError('Unexpected application symlink')
    if backup.exists() and not app.exists():
        os.replace(backup, app)
    # An uncommitted swap is rolled back on the next start, even if the new app directory exists.
    elif backup.exists() and (root / '.update_pending').exists():
        # Retain the displaced payload if restoring either directory fails.
        folder = Path(tempfile.mkdtemp(dir=root, prefix='.recover-'))
        failed = folder / 'failed'
        os.replace(app, failed)
        try:
            os.replace(backup, app)
        except BaseException:
            os.replace(failed, app)
            folder.rmdir()
            raise
        shutil.rmtree(folder, ignore_errors=True)
    (root / '.update_pending').unlink(missing_ok=True)


def install(root, staged, smoke, defer_commit=False):
    app, backup = root / 'app', root / '.app_previous'
    if not app.is_dir() or app.is_symlink() or backup.is_symlink():
        raise ValueError('Invalid application directory')
    # Verify the staged executable before touching the existing installation.
    smoke(staged)
    if backup.exists():
        shutil.rmtree(backup)
    marker = root / '.update_pending'
    with marker.open('w', encoding='ascii') as stream:
        stream.write('pending\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(app, backup)
        os.replace(staged, app)
        smoke(app)
        if not defer_commit:
            marker.unlink()
    except BaseException:
        recover(root)
        raise


def update(root, candidate, public_key, smoke, fetch=fetch_asset, defer_commit=False):
    current = (root / 'app' / 'VERSION').read_text().strip()
    if not public_key:
        raise ValueError('No trusted release signing key configured')
    with tempfile.TemporaryDirectory(dir=root, prefix='.update-') as folder:
        work = Path(folder)
        raw, sig = work / 'manifest', work / 'signature'
        name = candidate['asset'] + '.update.json'
        logging.getLogger('launcher').info('Update: checking signed manifest')
        fetch(candidate['version'], name, raw, MAX_MANIFEST)
        fetch(candidate['version'], name + '.sig', sig, 64)
        data = verify_manifest(raw.read_bytes(), sig.read_bytes(), public_key, candidate, current)
        payload = work / 'payload'
        archive = work / 'archive.zip'
        delta = data.get('delta')
        used = 'full'
        if delta and delta['from'] == current and delta['size'] < data['full']['size']:
            try:
                logging.getLogger('launcher').info('Update: downloading delta')
                fetch(data['version'], delta['asset'], archive, delta['size'], delta)
                logging.getLogger('launcher').info('Update: staging payload')
                stage_payload(archive, payload, root / 'app', data['files'], False)
                used = 'delta'
            except Exception:
                logging.getLogger('launcher').warning('Delta failed; trying full payload', exc_info=True)
                shutil.rmtree(payload, ignore_errors=True)
        if used == 'full':
            logging.getLogger('launcher').info('Update: downloading full payload')
            fetch(data['version'], data['full']['asset'], archive, data['full']['size'], data['full'])
            logging.getLogger('launcher').info('Update: staging payload')
            stage_payload(archive, payload, root / 'app', data['files'], True)
        if (payload / 'VERSION').read_text().strip() != data['version']:
            raise ValueError('Payload version mismatch')
        logging.getLogger('launcher').info('Update: validating and replacing payload')
        install(root, payload, smoke, defer_commit=defer_commit)
        return used
