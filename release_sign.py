"""Developer-only Ed25519 key generation and signed portable release metadata."""
import argparse
import json
from pathlib import Path
import zipfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from update_core import digest, inspect_archive, validate_files, REPOSITORY, PROTOCOL
from release_check import version_key
import hashlib
import getpass
import shutil
from launcher_update import MIN_VERSION, launcher_asset_name


def generate(private, public):
    # Store an encrypted private key; never place it in the repository or release archive.
    password = getpass.getpass('Signing key password: ')
    if len(password) < 12 or password != getpass.getpass('Confirm password: '):
        raise ValueError('Use a matching password of at least 12 characters')
    if private.exists() or public.exists():
        raise FileExistsError('Key already exists')
    key = Ed25519PrivateKey.generate()
    with private.open('xb') as stream:
        stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.BestAvailableEncryption(password.encode())))
    with public.open('xb') as stream:
        stream.write(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def inventory(path):
    with zipfile.ZipFile(path) as archive:
        entries = inspect_archive(archive, True)
        files = {}
        for name, entry in entries.items():
            with archive.open(entry) as stream:
                files[name] = {'size': entry.file_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
        validate_files(files)
        version = archive.read(entries['VERSION']).decode().strip()
    version_key(version)
    if path.name != f'MHF_SkillSimulator_{version}_win_x64_no_DB.zip':
        raise ValueError('Expected no-DB portable archive with matching version')
    return version, files


def blob(path):
    return {'asset': path.name, 'size': path.stat().st_size, 'sha256': digest(path)}


def sign_release(full, key, previous=None):
    version, files = inventory(full)
    data = {'protocol': PROTOCOL, 'repository': REPOSITORY, 'version': version,
            'full': blob(full), 'files': files}
    if version_key(version) >= version_key(MIN_VERSION):
        # Publish a small independent launcher asset from the same signed portable build.
        launcher = full.with_name(launcher_asset_name(version))
        with zipfile.ZipFile(full) as source, source.open('MHF_SkillSimulator/MHFSimulator.exe') as inp, launcher.open('xb') as out:
            shutil.copyfileobj(inp, out)
        data['launcher'] = blob(launcher)
    if previous:
        old_version, old_files = inventory(previous)
        if version_key(old_version) >= version_key(version):
            raise ValueError('Previous version must be older')
        delta = full.with_name(f'MHF_delta_{old_version}_to_{version}_win_x64.zip')
        with zipfile.ZipFile(full) as source, zipfile.ZipFile(delta, 'x', zipfile.ZIP_DEFLATED) as out:
            entries = inspect_archive(source, True)
            for name, info in files.items():
                if old_files.get(name) != info:
                    with source.open(entries[name]) as inp, out.open(name, 'w') as target:
                        shutil.copyfileobj(inp, target)
        data['delta'] = {'from': old_version, **blob(delta)}
    raw = json.dumps(data, sort_keys=True, separators=(',', ':')).encode()
    manifest = full.with_name(full.name + '.update.json')
    signature = manifest.with_name(manifest.name + '.sig')
    with manifest.open('xb') as stream:
        stream.write(raw)
    with signature.open('xb') as stream:
        stream.write(key.sign(raw))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    gen = sub.add_parser('keygen')
    gen.add_argument('--private', type=Path, required=True)
    gen.add_argument('--public', type=Path, required=True)
    sign = sub.add_parser('sign')
    sign.add_argument('--private', type=Path, required=True)
    sign.add_argument('--archive', type=Path, required=True)
    sign.add_argument('--previous', type=Path)
    args = parser.parse_args()
    if args.command == 'keygen':
        generate(args.private, args.public)
    else:
        key = serialization.load_pem_private_key(args.private.read_bytes(), password=getpass.getpass('Signing key password: ').encode())
        sign_release(args.archive, key, args.previous)


if __name__ == '__main__':
    main()
