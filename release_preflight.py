"""Validate a signed release locally and prepare an explicit public upload folder."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from release_sign import inventory, blob
from update_core import verify_manifest, stage_payload, digest, inspect_archive
from launcher_update import launcher_metadata, verify_executable, MIN_VERSION
from release_check import version_key


def verify_release(archive, public_key, previous=None):
    # Validate against the actual packaged binaries and frozen build report.
    version, files = inventory(archive)
    key = public_key.read_bytes()
    stem = archive.with_suffix('')
    smoke = json.loads(Path(str(stem)+'.smoke.json').read_text(encoding='utf-8'))
    if (smoke.get('ok') is not True or smoke.get('frozen') is not True or
            smoke.get('launcher', {}).get('ok') is not True or
            smoke['launcher'].get('public_key_sha256') != hashlib.sha256(key).hexdigest() or
            not all(smoke.get('checks', {}).get(c) is True for c in ('imports','milp','assets','database','api_search'))):
        raise ValueError('Missing successful DB/API frozen build report or embedded key mismatch; build with --pair and --public-key')
    manifest = Path(str(archive)+'.update.json')
    signature = Path(str(manifest)+'.sig')
    old = inventory(previous)[0] if previous else '0.0.0'
    data = verify_manifest(manifest.read_bytes(), signature.read_bytes(), key,
                           {'version':version, **blob(archive)}, old)
    if data['files'] != files:
        raise ValueError('Signed manifest differs from archive inventory')
    assets = [archive, manifest, signature]
    info = launcher_metadata(data)
    if version_key(version) >= version_key(MIN_VERSION):
        if info is None or smoke['launcher'].get('version') != version:
            raise ValueError('Missing versioned launcher build report or signed asset')
    if info is not None:
        launcher = archive.parent / info['asset']
        verify_executable(launcher, info)
        with zipfile.ZipFile(archive) as z, z.open('MHF_SkillSimulator/MHFSimulator.exe') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != info['sha256']:
                raise ValueError('Separate launcher differs from portable archive')
        assets.append(launcher)
    # Rehearse extraction without ever executing untrusted binaries or touching a live installation.
    with tempfile.TemporaryDirectory(prefix='mhf-release-check-') as temp:
        root = Path(temp)
        stage_payload(archive, root/'full', root/'unused', files, True)
        delta = data.get('delta')
        if delta:
            if previous is None or old != delta['from']:
                raise ValueError('Previous public archive required to verify delta')
            patch = archive.parent / delta['asset']
            if blob(patch) != {k:delta[k] for k in ('asset','size','sha256')}:
                raise ValueError('Delta archive hash mismatch')
            _, old_files = inventory(previous)
            stage_payload(previous, root/'old', root/'unused', old_files, True)
            stage_payload(patch, root/'delta', root/'old', files, False)
            assets.append(patch)
        elif previous:
            raise ValueError('Previous archive specified but no signed delta exists')
    return {'version':version, 'tag':'v'+version, 'prerelease':'-' in version,
            'files':len(files), 'delta_verified':bool(data.get('delta')), 'assets':assets}


def prepare_upload(archive, key, out, previous=None):
    result = verify_release(archive, key, previous)
    # An empty newly created directory prevents unrelated local artifacts being uploaded.
    out.mkdir(parents=False, exist_ok=False)
    try:
        for path in result['assets']:
            shutil.copy2(path, out/path.name)
            if digest(path) != digest(out/path.name):
                raise ValueError('Copy verification failed')
    except BaseException:
        shutil.rmtree(out)
        raise
    return {**result, 'assets':[p.name for p in result['assets']], 'upload_folder':str(out)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',type=Path,required=True)
    p.add_argument('--public-key',type=Path,required=True)
    p.add_argument('--previous',type=Path)
    p.add_argument('--out',type=Path,required=True)
    a = p.parse_args()
    print(json.dumps(prepare_upload(a.archive,a.public_key,a.out,a.previous),indent=2))


if __name__ == '__main__':
    main()
