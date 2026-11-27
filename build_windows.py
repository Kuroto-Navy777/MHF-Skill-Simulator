"""Build a Windows x64 portable archive in an isolated, non-destructive staging area."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent


# Fail before PyInstaller if an incremental source update was skipped.
REQUIRED_BUILD_FILES = (
    'launcher.py', 'launcher_update.py', 'desktop_safety.py', 'desktop_info.py', 'desktop_entry.py', 'desktop.py',
    'desktop_lifecycle.py', 'worker_control.py', 'update_progress.py',
    'update_core.py', 'release_check.py', 'runtime_paths.py', 'windows_setup.py',
    'installer_guard.py', 'web_api.py', 'search_engine.py', 'release_sign.py', 'release_preflight.py',
    'web/app.js', 'web/favicon.ico', 'VERSION', 'release_source.json',
)


def validate_build_sources(root):
    # Check actual source files, not the existing build environment or old EXEs.
    missing = [name for name in REQUIRED_BUILD_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError('Incomplete source update. Restore the complete source before building. Missing: '
                         + ', '.join(missing))



def build_command(root, staging, executable=sys.executable):
    # Onedir keeps the launch path stable and makes UI-only updates possible.
    return [executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
            '--windowed', '--noupx', '--name', 'MHFDesktop',
            '--distpath', str(staging / 'dist'), '--workpath', str(staging / 'work'),
            '--specpath', str(staging), '--paths', str(root),
            '--icon', str(root / 'web' / 'favicon.ico'),
            '--collect-all', 'webview', '--collect-all', 'pythonnet',
            '--collect-submodules', 'uvicorn', '--hidden-import', 'clr',
            '--hidden-import', 'pystray._win32', '--hidden-import', 'desktop_safety',
            '--hidden-import', 'worker_control', '--hidden-import', 'desktop_info', str(root / 'desktop_entry.py')]


def launcher_command(root, staging, public_key=None, executable=sys.executable):
    # A separate single-file launcher stays fixed while the desktop payload is updated.
    args = [executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile',
            '--windowed', '--noupx', '--name', 'MHFSimulator',
            '--distpath', str(staging / 'launcher'), '--workpath', str(staging / 'launcher-work'),
            '--specpath', str(staging), '--paths', str(root), '--icon', str(root / 'web' / 'favicon.ico'),
            '--hidden-import', 'tkinter', '--hidden-import', 'tkinter.ttk',
            '--hidden-import', 'desktop_safety', '--hidden-import', 'update_progress',
            '--hidden-import', 'launcher_update', '--add-data', str(root / 'VERSION') + os.pathsep + '.']
    if public_key is not None:
        args += ['--add-data', str(public_key) + os.pathsep + '.']
    return args + [str(root / 'launcher.py')]


def stage_files(root, target, db=None):
    # Do not copy source ZIPs, private browser profiles, or the developer's other files.
    for name in ('VERSION', 'example_auto_search.json', 'THIRD_PARTY_NOTICES.txt', 'release_source.json'):
        shutil.copy2(root / name, target / name)
    shutil.copytree(root / 'web', target / 'web')
    shutil.copy2(root / 'PORTABLE_README.txt', target / 'README.txt')
    if db is not None:
        from windows_setup import check_db
        check_db(db, master=True, deep=True)
        shutil.copy2(db, target / 'mhf_master.sqlite')


def package(target, archive):
    # A single outer directory prevents accidental extraction into an existing install.
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(target.rglob('*')):
            if path.is_file():
                z.write(path, 'MHF_SkillSimulator/' + path.relative_to(target).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:
            raise RuntimeError('Archive integrity check failed')



def release_metadata(archive, version, includes_db):
    # Hash the actual portable archive, not the source tree or a checksum supplied by a caller.
    from release_check import version_key
    version_key(version)
    expected = f'MHF_SkillSimulator_{version}_win_x64' + ('_with_DB.zip' if includes_db else '_no_DB.zip')
    if archive.name != expected:
        raise ValueError('Release archive name does not match version')
    with archive.open('rb') as stream:
        sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'version': version, 'tag': 'v'+version, 'asset': archive.name,
            'size': archive.stat().st_size, 'sha256': sha, 'includes_db': includes_db}


def release_stem(version, includes_db):
    return f'MHF_SkillSimulator_{version}_win_x64' + ('_with_DB' if includes_db else '_no_DB')


def write_release(portable, stage, out, version, includes_db, smoke):
    # Validate the public variant before publishing any output. A DB must never leak into it.
    stem = release_stem(version, includes_db)
    if (portable / 'mhf_master.sqlite').exists() != includes_db:
        raise ValueError('Unexpected DB inclusion')
    tmpzip = stage / (stem + '.zip')
    package(portable, tmpzip)
    if not includes_db:
        from release_sign import inventory
        inventory(tmpzip)
    info = release_metadata(tmpzip, version, includes_db)
    shutil.copy2(smoke, out / (stem + '.smoke.json'))
    (out / (stem + '.sha256')).write_text(f"{info['sha256']}  {tmpzip.name}\n", encoding='ascii')
    (out / (stem + '.release.json')).write_text(json.dumps(info, indent=2)+'\n', encoding='utf-8')
    archive = out / tmpzip.name
    os.replace(tmpzip, archive)
    return archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, help='Explicitly include a locally generated master DB (check redistribution rights first)')
    parser.add_argument('--pair', action='store_true', help='Build matching no-DB and private with-DB archives in one run; requires --db')
    parser.add_argument('--out', type=Path, default=ROOT / 'release')
    parser.add_argument('--public-key', type=Path, help='32-byte Ed25519 public key generated by release_sign.py')
    args = parser.parse_args()
    if os.name != 'nt' or struct.calcsize('P') != 8:
        parser.error('Use 64-bit Windows Python on Windows to build this EXE.')
    if sys.version_info[:2] != (3, 12):
        parser.error('Use the Windows build environment with Python 3.12 x64.')
    try:
        validate_build_sources(ROOT)
    except ValueError as exc:
        parser.error(str(exc))
    # Verify launcher and desktop imports before starting either PyInstaller build.
    subprocess.run([sys.executable, '-c', 'import launcher, desktop, web_api, update_progress'],
                   check=True, cwd=ROOT)
    out = args.out.resolve()
    db = args.db.resolve() if args.db else None
    if args.pair and db is None:
        parser.error('--pair requires --db')
    if db is not None:
        from windows_setup import check_db
        check_db(db, master=True, deep=True)
    version = (ROOT / 'VERSION').read_text().strip()
    out.mkdir(parents=True, exist_ok=True)
    variants = [False, True] if args.pair else [db is not None]
    # Reserve both output names before spending time on a build.
    for includes_db in variants:
        stem = release_stem(version, includes_db)
        if any((out / (stem + suffix)).exists() for suffix in ('.zip', '.smoke.json', '.sha256', '.release.json')):
            parser.error('Release already exists; use a new output folder.')
    with tempfile.TemporaryDirectory(prefix='mhf-build-', dir=out) as temp:
        stage = Path(temp)
        subprocess.run(build_command(ROOT, stage), check=True, cwd=ROOT)
        target = stage / 'dist' / 'MHFDesktop'
        exe = target / 'MHFDesktop.exe'
        if not exe.is_file():
            raise RuntimeError('Windows executable missing')
        with exe.open('rb') as binary:
            if binary.read(2) != b'MZ':
                raise RuntimeError('Invalid Windows executable')
        stage_files(ROOT, target)
        # Record actual build dependency versions for reproducibility and diagnosis.
        (target / 'BUILD_DEPENDENCIES.txt').write_bytes(subprocess.check_output([sys.executable, '-m', 'pip', 'freeze']))
        smoke = stage / 'smoke.json'
        command = [str(exe), '--self-test', '--report', str(smoke)]
        if db is not None:
            command += ['--db', str(db)]
        try:
            subprocess.run(command, check=True, timeout=180, cwd=stage)
            result = json.loads(smoke.read_text(encoding='utf-8'))
            if not result.get('ok') or not result.get('frozen'):
                raise RuntimeError(f'Frozen smoke test failed: {result}')
        except BaseException:
            if smoke.is_file():
                print(smoke.read_text(encoding='utf-8'))
            raise
        # Build the pinned launcher separately. A missing key disables automatic application.
        key = None
        if args.public_key:
            data = args.public_key.read_bytes()
            if len(data) != 32:
                raise ValueError('Public key must be 32 raw bytes')
            key = stage / 'update_public_key.bin'
            key.write_bytes(data)
        subprocess.run(launcher_command(ROOT, stage, key), check=True, cwd=ROOT)
        portable = stage / 'portable'
        portable.mkdir()
        shutil.move(str(target), portable / 'app')
        launcher = stage / 'launcher' / 'MHFSimulator.exe'
        with launcher.open('rb') as binary:
            if binary.read(2) != b'MZ':
                raise RuntimeError('Invalid launcher executable')
        # Confirm that the independent frozen launcher loads its crypto library and trusted key.
        launcher_report = stage / 'launcher-smoke.json'
        subprocess.run([str(launcher), '--launcher-self-test', str(launcher_report)],
                       check=True, timeout=90, cwd=stage)
        launcher_result = json.loads(launcher_report.read_text(encoding='utf-8'))
        expected_key = hashlib.sha256(key.read_bytes()).hexdigest() if key else None
        if (launcher_result.get('ok') is not True or launcher_result.get('startup_gui') is not True
                or launcher_result.get('version') != version
                or launcher_result.get('public_key_sha256') != expected_key):
            raise RuntimeError('Frozen launcher smoke test failed')
        result['launcher'] = launcher_result
        smoke.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copy2(launcher, portable / launcher.name)
        shutil.copy2(ROOT / 'release_source.json', portable / 'release_source.json')
        shutil.copy2(ROOT / 'PORTABLE_README.txt', portable / 'README.txt')
        # Package both variants from exactly the same frozen binaries.
        for includes_db in variants:
            if includes_db:
                shutil.copy2(db, portable / 'mhf_master.sqlite')
            archive = write_release(portable, stage, out, version, includes_db, smoke)
            print(archive)


if __name__ == '__main__':
    main()
