"""Compile a fresh-install Windows setup from an existing signed portable release."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from release_preflight import verify_release
from release_check import version_key
from release_sign import blob
from update_core import OUTER, digest, inspect_archive, safe_path
from windows_setup import check_db

ROOT = Path(__file__).resolve().parent


def stage_installer(archive, key, previous, target, db=None):
    # Require the same validated, signed release used by the auto-updater.
    info = verify_release(archive, key, previous)
    version = info['version']
    manifest = json.loads(Path(str(archive)+'.update.json').read_bytes())
    target.mkdir(exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        inspect_archive(z, True)
        for entry in z.infolist():
            name = entry.filename[len(OUTER):]
            safe_path(name)
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(entry) as source, dest.open('xb') as out:
                shutil.copyfileobj(source, out, 1024*1024)
            if name.startswith('app/'):
                expected = manifest['files'][name[4:]]
                if dest.stat().st_size != expected['size'] or digest(dest) != expected['sha256']:
                    raise ValueError('Installer payload differs from signed app')
    # The separate launcher is also signed; the installer's initial configuration must be stable.
    if digest(target/'MHFSimulator.exe') != manifest['launcher']['sha256']:
        raise ValueError('Installer launcher differs from signed release')
    config = json.loads((target/'release_source.json').read_text(encoding='utf-8-sig'))
    if config != {'repository': manifest['repository'], 'channel': 'stable', 'check_on_startup': True}:
        raise ValueError('Unexpected installer release configuration')
    if db is not None:
        check_db(db, master=True, deep=True)
        shutil.copy2(db, target/'mhf_master.sqlite')
        if digest(db) != digest(target/'mhf_master.sqlite'):
            raise ValueError('DB copy verification failed')
    return version


def installer_name(version, db):
    version_key(version)
    return f'MHF_SkillSimulator_{version}_Setup_win_x64_{"with_DB" if db else "no_DB"}.exe'


def render_script(template, version, db):
    version_key(version)
    # Fixed relative paths avoid quoting or preprocessor injection through developer paths.
    return (f'#define AppVersion "{version}"\n#define IncludeDB {int(bool(db))}\n'
            '#define PayloadDir "payload"\n#define OutputFolder "out"\n' + template)


def locate_iscc(explicit=None):
    if explicit:
        candidates = [Path(explicit)]
    else:
        candidates = []
        found = shutil.which('ISCC.exe')
        if found:
            candidates.append(Path(found))
        for var in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
            if os.environ.get(var):
                root = Path(os.environ[var])
                for edition in ('Inno Setup 7', 'Inno Setup 6'):
                    candidates += [root/edition/'ISCC.exe', root/'Programs'/edition/'ISCC.exe']
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError('ISCC.exe not found. Install Inno Setup 6.3+ or 7, or pass --iscc PATH.')


def build(archive, key, previous, out, iscc, db=None):
    if os.name != 'nt':
        raise RuntimeError('The installer compiler requires Windows.')
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mhf-setup-', dir=out) as temp:
        stage = Path(temp)
        version = stage_installer(archive, key, previous, stage/'payload', db)
        name = installer_name(version, db)
        dest = out/name
        checksum = out/(name+'.sha256')
        if dest.exists() or checksum.exists():
            raise FileExistsError('Installer already exists. Use a new output folder.')
        script = stage/'setup.iss'
        template = (ROOT/'installer'/'MHFSkillSimulator.iss').read_text(encoding='utf-8-sig')
        script.write_text(render_script(template, version, db), encoding='utf-8-sig')
        subprocess.run([str(iscc), str(script)], cwd=stage, check=True)
        exe = stage/'out'/name
        with exe.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise ValueError('Invalid generated installer')
        # Never place DB installers into the automatic update upload directory implicitly.
        os.replace(exe, dest)
        checksum.write_text(f'{digest(dest)}  {name}\n', encoding='ascii')
        return dest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--previous', type=Path)
    p.add_argument('--public-key', type=Path, required=True)
    p.add_argument('--out', type=Path, default=ROOT/'release'/'installers')
    p.add_argument('--iscc', type=Path)
    p.add_argument('--db', type=Path, help='Explicit DB inclusion for local testing or authorized distribution')
    a = p.parse_args()
    if os.name != 'nt':
        p.error('Run on the Windows build PC.')
    print(build(a.archive.resolve(), a.public_key.resolve(), a.previous.resolve() if a.previous else None,
                a.out.resolve(), locate_iscc(a.iscc), a.db.resolve() if a.db else None))


if __name__ == '__main__':
    main()
