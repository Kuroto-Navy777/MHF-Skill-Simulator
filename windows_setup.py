"""Local setup, launcher and trusted release updater."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
import zipfile
from contextlib import closing

from runtime_paths import app_root

ROOT = app_root()
PORT = 8765
URL = f'http://127.0.0.1:{PORT}/'
BASE = 'mhf.sqlite'
MASTER = 'mhf_master.sqlite'
ARCHIVES = {
    'ja': ('20191218+NI.zip',),
    'en': ('MHSX2G Normal Dat_6620221058.zip', 'MHSX2G%20Normal%20Dat_6620221058.zip'),
    'pax': ('Pax-MHFZ-Data-Collection-main.zip',),
    'ferias': ('MHFZ-Ferias-English-Project-main.zip',),
}


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def check_db(path, master=False, deep=False):
    # Read-only checks; never repair or replace an existing database silently.
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        for table in ('equipment','skills','skill_levels','ferias_weapons','ferias_variants','sources'):
            if not db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                raise ValueError(f'Empty table: {table}')
        if master:
            from master_data import has_master
            if not has_master(db):
                raise ValueError('Not a master database')
            for table in ('master_weapon_names','master_skill_reference','master_equipment_recipes','master_weapon_recipes','master_material_sources','master_item_names','master_rule_reference'):
                if not db.execute(f'SELECT 1 FROM {table} LIMIT 1').fetchone():
                    raise ValueError(f'Empty table: {table}')
        if deep and (db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone()):
            raise ValueError('Database integrity check failed')
    return path


def resolve_archives(directory, base=None):
    # Migration must use the filenames and hashes recorded at import time.
    if base is not None:
        with closing(sqlite3.connect(base.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            entries = {k:(name,sha) for k,name,sha in db.execute('SELECT id,filename,sha256 FROM sources')}
        found = {}
        for key in ('ja','en','ferias'):
            name,sha = entries[key]
            path = directory / Path(name).name
            if not path.is_file():
                raise FileNotFoundError(path)
            if digest(path)!=sha:
                raise ValueError(f'Source hash differs: {path.name}')
            found[key]=path
        return found
    found={}
    for key,names in ARCHIVES.items():
        path=next((directory/n for n in names if (directory/n).is_file()),None)
        if path is None:
            raise FileNotFoundError(directory/names[0])
        if not zipfile.is_zipfile(path):
            raise ValueError(f'Not a ZIP file: {path}')
        found[key]=path
    return found


def choose_path(prompt, directory=True):
    # Native file picker if available; console fallback otherwise.
    try:
        import tkinter as tk
        from tkinter import filedialog
        window=tk.Tk();window.withdraw()
        try:
            value=(filedialog.askdirectory(title=prompt,initialdir=str(ROOT)) if directory else filedialog.askopenfilename(title=prompt,initialdir=str(ROOT),filetypes=[('ZIP files','*.zip')]))
        finally:
            window.destroy()
    except Exception:
        value=input(prompt+' (path): ').strip().strip('"')
    if not value:
        raise ValueError('Cancelled')
    return Path(value).expanduser().resolve()


def archive_directory(root, requested, base=None, interactive=True):
    if requested is not None:
        return requested
    for directory in (root,root/'archives'):
        try:
            resolve_archives(directory,base)
            return directory
        except FileNotFoundError:
            pass
    if not interactive:
        raise FileNotFoundError('Original ZIP folder not found. Specify --archives.')
    return choose_path('元データZIPが揃っているフォルダを選択 / Select archive folder')


def publish(source,dest):
    # Atomic publication without replacing another completed database.
    if os.name=='nt':
        os.rename(source,dest)
    else:
        os.link(source,dest)
        source.unlink()


def dependencies_ok(python):
    result=subprocess.run([str(python),'-c','import lxml.etree, scipy.optimize, numpy, fastapi, uvicorn'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return result.returncode==0


def venv_python(root):
    return root/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def prepare_python(root, current=False):
    if current:
        if not dependencies_ok(sys.executable):
            raise ValueError('Current Python is missing dependencies.')
        return Path(sys.executable)
    python=venv_python(root)
    if not python.is_file():
        print('Creating local Python environment...',flush=True)
        subprocess.run([sys.executable,'-m','venv',str(root/'.venv')],check=True)
    if not dependencies_ok(python):
        print('Installing dependencies (internet required)...',flush=True)
        subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(root/'requirements.txt')],check=True)
    if not dependencies_ok(python):
        raise ValueError('Dependency validation failed')
    return python


def require_stopped():
    # Keep the original loopback port so browser storage survives upgrades.
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.settimeout(.3)
        if sock.connect_ex(('127.0.0.1',PORT))==0:
            raise ValueError(f'Port {PORT} is in use. Close the simulator first.')


def setup(root, archives=None, current=False, interactive=True):
    require_stopped()
    master,base=root/MASTER,root/BASE
    if master.exists():
        check_db(master,master=True,deep=True)
        prepare_python(root,current)
        print('Existing master database verified. Nothing was overwritten.')
        return master
    directory=archive_directory(root,archives,base if base.exists() else None,interactive)
    files=resolve_archives(directory,base if base.exists() else None)
    python=prepare_python(root,current)
    # Import into temporary paths before publishing validated databases.
    with tempfile.TemporaryDirectory(prefix='.setup-',dir=root) as temp:
        work=Path(temp)
        if not base.exists():
            print('Importing original data...',flush=True)
            target=work/BASE
            args=[str(python),str(root/'import_data.py'),'--out',str(target)]
            for key,path in files.items():
                args.extend(['--'+key,str(path)])
            subprocess.run(args,cwd=root,check=True)
            check_db(target,deep=True)
            publish(target,base)
        else:
            check_db(base,deep=True)
        print('Building master database...',flush=True)
        target=work/MASTER
        subprocess.run([str(python),str(root/'build_master.py'),'--db',str(base),'--out',str(target),'--archives',str(directory)],cwd=root,check=True)
        check_db(target,master=True,deep=True)
        publish(target,master)
    print('Setup complete. Start with start_web.bat.',flush=True)
    return master


def launch(root, browser=True):
    require_stopped()
    master,base=root/MASTER,root/BASE
    path=master if master.exists() else base
    if not path.is_file():
        raise ValueError('Database missing. Run setup_windows.bat first.')
    check_db(path,master=(path==master))
    python=venv_python(root)
    if not python.is_file() or not dependencies_ok(python):
        python=Path(sys.executable)
    if not dependencies_ok(python):
        raise ValueError('Dependencies missing. Run setup_windows.bat first.')
    print(f'Database: {path.name}\nURL: {URL}\nCtrl+C to stop.',flush=True)
    process=subprocess.Popen([str(python),str(root/'web_api.py'),'--db',str(path),'--port',str(PORT)],cwd=root)
    try:
        # Do not send a localhost request through a configured proxy.
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError(f'Server exited: {process.returncode}')
            try:
                with opener.open(URL+'api/health',timeout=2) as response:
                    health=json.load(response)
                if health.get('ready'):
                    break
            except (OSError,ValueError):
                pass
            time.sleep(.25)
        else:
            raise RuntimeError('Server health check failed. See console output.')
        if browser:
            webbrowser.open(URL)
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill();process.wait()


def doctor(root):
    # Read-only local diagnosis. Do not create, repair, upload or replace user data.
    import platform
    report={'version':(root/'VERSION').read_text(encoding='utf-8').strip(),
            'platform':platform.system(),'python':platform.python_version(),'checks':{}}
    checks=report['checks']
    def check(name,fn):
        try:
            detail=fn()
            checks[name]={'ok':True,'detail':detail}
        except Exception as exc:
            checks[name]={'ok':False,'detail':str(exc)}
    master=root/MASTER
    base=root/BASE
    path=master if master.is_file() else base
    def deps():
        candidates=[venv_python(root),Path(sys.executable)]
        for candidate in candidates:
            if candidate.is_file() and dependencies_ok(candidate):
                return 'local venv' if candidate==candidates[0] else 'current Python'
        raise ValueError('Dependencies missing; run setup_windows.bat')
    def database():
        if not path.is_file():raise ValueError('Database missing; run setup_windows.bat')
        check_db(path,master=(path==master),deep=True)
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            return {'database':path.name,'counts':{t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('equipment','skills','skill_levels','ferias_weapons')}}
    def assets():
        for name in ('web_api.py','search_engine.py','web/index.html','web/app.js','web/style.css'):
            if not (root/name).is_file():raise ValueError(f'Missing application file: {name}')
        return 'Required application files present'
    def port():
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
            sock.settimeout(.3)
            if sock.connect_ex(('127.0.0.1',PORT))!=0:return 'Port available'
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(URL+'api/health',timeout=3) as response:
            health=json.load(response)
        if not health.get('ready') or health.get('version')!=report['version']:
            raise ValueError('Port occupied or running application version differs')
        return 'Matching simulator is running'
    check('dependencies',deps)
    check('database',database)
    check('application_files',assets)
    check('local_port',port)
    report['ok']=all(v['ok'] for v in checks.values())
    return report


def allowed_file(name):
    p=PurePosixPath(name)
    # Restrict the updater to application files; never accept database files or paths outside the app.
    if str(p)!=name or any(x in ('','..','.') for x in p.parts) or '\\' in name or ':' in name or p.is_absolute():
        return False
    # Windows normalizes trailing periods/spaces and reserves device names.
    if any(part.rstrip(' .')!=part or part.split('.')[0].upper() in
           {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
           for part in p.parts):
        return False
    if len(p.parts)==1:
        return p.suffix in ('.py','.bat','.mjs') or name in ('README.md','QUICK_START.md','DESKTOP_GUIDE.md','requirements.txt','requirements_desktop.txt','requirements_build.txt','BUILD_WINDOWS.md','VERSION','release_manifest.json','THIRD_PARTY_NOTICES.txt','.gitignore') or (name.startswith('example_') and p.suffix=='.json')
    return len(p.parts)==2 and p.parts[0]=='web' and p.name in ('index.html','app.js','style.css','backup.mjs','favicon.ico')


def apply_update(root, archive):
    require_stopped()
    # Checksums detect corruption, not authenticity. Only use a trusted distribution.
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(n.casefold() for n in names)) or any(not allowed_file(n) for n in names):
            raise ValueError('Unsupported or unsafe release ZIP')
        if sum(i.file_size for i in z.infolist())>50*1024*1024:
            raise ValueError('Release archive too large')
        manifest=json.loads(z.read('release_manifest.json'))
        if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),dict):
            raise ValueError('Invalid release manifest')
        files=manifest['files']
        if any(not isinstance(n,str) or not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha) for n,sha in files.items()):
            raise ValueError('Invalid release checksums')
        # Delta releases must match the installed base; do not mix app generations.
        installed=(root/'VERSION').read_text(encoding='utf-8').strip() if (root/'VERSION').is_file() else ''
        expected=manifest.get('base_versions')
        if expected is not None:
            if not isinstance(expected,list) or not expected or not all(isinstance(v,str) for v in expected):
                raise ValueError('Invalid base versions in release manifest')
            if installed not in expected:
                raise ValueError(f'Incompatible update: installed {installed or "unknown"}; requires {", ".join(expected)}')
        if 'version' in manifest and z.read('VERSION').decode('utf-8').strip()!=manifest['version']:
            raise ValueError('Release VERSION does not match manifest')
        if set(names)!=set(files)|{'release_manifest.json'} or 'VERSION' not in files:
            raise ValueError('Release manifest does not match archive')
        for n,sha in files.items():
            if hashlib.sha256(z.read(n)).hexdigest()!=sha:
                raise ValueError(f'Checksum mismatch: {n}')
        for name in names:
            path=root/name
            if path.resolve()!=path.absolute() or not path.resolve().is_relative_to(root.resolve()):
                raise ValueError(f'Unsafe destination: {name}')
        backup=root/'update_backups'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        if backup.resolve()!=backup.absolute():
            raise ValueError('Unsafe backup directory')
        backup.mkdir(parents=True)
        written=[]
        try:
            for name in names:
                dest=root/name
                previous=backup/name
                existed=dest.exists()
                if existed:
                    previous.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(dest,previous)
                dest.parent.mkdir(parents=True,exist_ok=True)
                written.append((dest,previous,existed))
                with tempfile.NamedTemporaryFile(dir=dest.parent,delete=False) as f:
                    temp=Path(f.name)
                    f.write(z.read(name))
                try: os.replace(temp,dest)
                finally: temp.unlink(missing_ok=True)
        except BaseException:
            for dest,previous,existed in reversed(written):
                if existed: shutil.copy2(previous,dest)
                else: dest.unlink(missing_ok=True)
            raise
    print(f'Update completed. Previous files: {backup}',flush=True)
    return backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['setup','start','update','doctor','desktop-setup','desktop'])
    parser.add_argument('--archives',type=Path)
    parser.add_argument('--current-python',action='store_true')
    parser.add_argument('--non-interactive',action='store_true')
    parser.add_argument('--no-browser',action='store_true')
    parser.add_argument('--zip',type=Path)
    args=parser.parse_args()
    if sys.version_info<(3,11):
        parser.error('Python 3.11 or newer required')
    try:
        if args.command=='setup':
            setup(ROOT,args.archives.resolve() if args.archives else None,args.current_python,not args.non_interactive)
        elif args.command=='start':
            return launch(ROOT,not args.no_browser)
        elif args.command=='desktop-setup':
            # Optional desktop dependency; the existing browser mode remains unchanged.
            require_stopped()
            python=prepare_python(ROOT,args.current_python)
            subprocess.run([str(python),'-m','pip','install','--disable-pip-version-check','-r',str(ROOT/'requirements_desktop.txt')],check=True)
            subprocess.run([str(python),'-c','import webview, pystray, PIL'],check=True)
            print('Desktop setup complete. Run start_desktop.bat.')
        elif args.command=='desktop':
            python=venv_python(ROOT)
            if not python.is_file():
                python=Path(sys.executable)
            return subprocess.call([str(python),str(ROOT/'desktop.py')],cwd=ROOT)
        elif args.command=='doctor':
            report=doctor(ROOT)
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
            return 0 if report['ok'] else 1
        else:
            archive=args.zip or choose_path('信頼できる更新ZIPを選択 / Select a trusted release ZIP',directory=False)
            if not args.non_interactive and input(f'Apply {archive.name}? Type YES to continue: ').strip()!='YES':
                raise ValueError('Cancelled')
            apply_update(ROOT,archive)
        return 0
    except (OSError,ValueError,KeyError,RuntimeError,sqlite3.Error,subprocess.SubprocessError,zipfile.BadZipFile) as exc:
        print(f'ERROR: {exc}',file=sys.stderr,flush=True)
        return 1


if __name__=='__main__':
    sys.exit(main())
