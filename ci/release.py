"""Local trusted Windows release pipeline; no keys or databases are uploaded to CI.

Run with Python 3.12 after editing sources. Password is read from the terminal,
or MHF_SIGNING_PASSWORD in a secured unattended environment. No key generation.
"""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from release_check import version_key
from release_sign import sign_release
from release_preflight import prepare_upload
from build_installer import build, locate_iscc
from cryptography.hazmat.primitives import serialization

REPO='Kuroto-Navy777/MHF-Skill-Simulator'


def run(*args, **kwargs):
    return subprocess.run(list(map(str,args)),cwd=ROOT,check=True,**kwargs)


def audit_index():
    files=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    for name in filter(None,files):
        p=Path(name)
        if p.suffix.lower() in {'.pem','.key','.pfx','.p12','.db','.sqlite','.sqlite3','.zip'} or '.env' in p.parts:
            raise ValueError(f'Private or unlicensed file in Git index: {name}')
        data=(ROOT/p).read_bytes()
        if b'-----BEGIN PRIVATE KEY-----\n' in data or b'-----BEGIN ENCRYPTED PRIVATE KEY-----\n' in data:
            raise ValueError(f'Private key material in Git index: {name}')


def source_manifest(version):
    names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    files={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(filter(None,names))
           if name!='release_manifest.json'}
    (ROOT/'release_manifest.json').write_text(json.dumps({'version':version,'kind':'source','files':files},indent=2)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',required=True)
    p.add_argument('--db',type=Path,required=True)
    p.add_argument('--public-key',type=Path,required=True)
    p.add_argument('--private-key',type=Path,required=True)
    p.add_argument('--previous',type=Path,required=True)
    p.add_argument('--push',action='store_true',help='Commit and push current branch after validation')
    p.add_argument('--publish',action='store_true',help='Publish verified assets instead of creating a draft')
    a=p.parse_args(); version_key(a.version)
    if a.publish and not a.push: p.error('--publish requires --push')
    if os.name!='nt' or sys.version_info[:2]!=(3,12): p.error('Windows Python 3.12 required')
    for path in (a.db,a.public_key,a.private_key,a.previous):
        if not path.is_file(): p.error(f'Missing required local file: {path.name}')
    a.db=a.db.resolve(); a.public_key=a.public_key.resolve(); a.private_key=a.private_key.resolve(); a.previous=a.previous.resolve()
    public=a.public_key.read_bytes()
    if len(public)!=32: p.error('Expected existing 32-byte Ed25519 public key')
    password=os.environ.pop('MHF_SIGNING_PASSWORD',None) or getpass.getpass('Existing release key password: ')
    key=serialization.load_pem_private_key(a.private_key.read_bytes(),password=password.encode())
    del password
    actual=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    if actual!=public: raise ValueError('Existing signing key does not match pinned public key')
    # Verify continuity with the previous signed public release before building.
    from release_sign import inventory
    from update_core import verify_manifest
    previous_version,_=inventory(a.previous)
    verify_manifest(Path(str(a.previous)+'.update.json').read_bytes(),Path(str(a.previous)+'.update.json.sig').read_bytes(),
                    public,{'version':previous_version,**__import__('release_sign').blob(a.previous)},'0.0.0')
    if version_key(a.version)<=version_key(previous_version): p.error('Version must increase')
    (ROOT/'VERSION').write_text(a.version+'\n',encoding='utf-8')
    env={**os.environ,'MHF_TEST_DB':str(a.db.resolve()),'PYTHONUTF8':'1'}
    run(sys.executable,'-m','unittest','discover','-v',env=env)
    run('node','--test',*[path.name for path in ROOT.glob('test_*.mjs')])
    run(sys.executable,'verify_v112_browser.py',env=env)
    out=ROOT/'release'/a.version
    run(sys.executable,'build_windows.py','--db',a.db,'--pair','--public-key',a.public_key,'--out',out)
    archive=out/f'MHF_SkillSimulator_{a.version}_win_x64_no_DB.zip'
    sign_release(archive,key,a.previous)
    upload=out/'upload'
    prepare_upload(archive,a.public_key,upload,a.previous)
    installer=build(archive,a.public_key,a.previous,out/'installers',locate_iscc())
    installer_signature=Path(str(installer)+'.sig')
    installer_signature.write_bytes(key.sign(installer.read_bytes()))
    key.public_key().verify(installer_signature.read_bytes(),installer.read_bytes())
    shutil.copy2(installer,upload/installer.name)
    shutil.copy2(installer_signature,upload/installer_signature.name)
    shutil.copy2(Path(str(installer)+'.sha256'),upload/(installer.name+'.sha256'))
    # All tests and signed full/delta replay pass before any source push or release.
    run('git','add','--all'); audit_index(); source_manifest(a.version); run('git','add','release_manifest.json')
    run('git','commit','-m',f'Release {a.version}')
    if a.push:
        run('git','push','-u','origin','HEAD')
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip()
        args=['gh','release','create','v'+a.version,'--repo',REPO,'--target',commit,'--title','MHF Skill Simulator v'+a.version,
              '--notes-file',str(ROOT/'V112_REPORT.md')]
        if not a.publish: args+=['--draft']
        run(*args,*sorted(upload.iterdir()))
    else:
        print('Verified local assets ready. Push/release omitted; use --push (draft) or --push --publish.')


if __name__=='__main__': main()
