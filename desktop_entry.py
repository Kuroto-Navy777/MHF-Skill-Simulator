"""EXE entry point: desktop UI, headless search worker, and build smoke test."""
import argparse
import contextlib
import json
import multiprocessing
import os
import subprocess
from pathlib import Path
import sys
import time
import traceback
import urllib.request

from runtime_paths import app_root


def worker(argv):
    # A windowed EXE has no console streams. The parent reads this private job log.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--worker-log', type=Path, required=True)
    options, remaining = parser.parse_known_args(argv)
    with options.worker_log.open('w', encoding='utf-8', buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                from search_engine import main
                main(remaining)
                return 0
            except BaseException:
                traceback.print_exc()
                return 1


def smoke_test(argv):
    # Report to a file because the Windows EXE is intentionally console-free.
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--precompute-check', action='store_true')
    args = parser.parse_args(argv)
    result = {'ok': False, 'frozen': bool(getattr(sys, 'frozen', False)), 'checks': {}}
    try:
        import scipy.optimize
        import numpy as np
        import fastapi, uvicorn, lxml.etree, PIL.Image
        if os.name == 'nt':
            import webview, pystray
            import clr
        result['checks']['imports'] = True
        sol = scipy.optimize.milp(np.array([1.]), integrality=np.array([1]),
                                 bounds=scipy.optimize.Bounds([2.], [4.]))
        if not sol.success or abs(sol.x[0] - 2.) > 1e-8:
            raise RuntimeError('MILP smoke test failed')
        result['checks']['milp'] = True
        root = app_root()
        for filename in ('VERSION', 'web/index.html', 'web/app.js', 'web/style.css', 'web/favicon.ico'):
            if not (root / filename).is_file():
                raise FileNotFoundError(filename)
        result['checks']['assets'] = True
        if args.db:
            from windows_setup import check_db
            from desktop import local_server
            check_db(args.db, master=True, deep=True)
            result['checks']['database'] = True
            # Exercise the full API -> separate solver process -> result path.
            payload = json.loads((root / 'example_auto_search.json').read_text(encoding='utf-8'))
            with local_server(args.db, 0) as url:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url + 'api/health', timeout=5) as response:
                    health = json.load(response)
                if not health.get('ready') or not health.get('master'):
                    raise RuntimeError('Master database health check failed')
                with opener.open(urllib.request.Request(url+'api/search', data=json.dumps(payload).encode(),
                                 headers={'Content-Type':'application/json'}), timeout=10) as response:
                    key = json.load(response)['id']
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline:
                    with opener.open(url+'api/search/'+key, timeout=5) as response:
                        state = json.load(response)
                    if state['status'] != 'running':
                        break
                    time.sleep(.2)
                if state['status'] != 'done' or not state['result'].get('results'):
                    raise RuntimeError(f'Search smoke test failed: {state}')
                result['checks']['api_search'] = True
                result['checks']['counts'] = health['counts']
            if args.precompute_check:
                import tempfile,sqlite3
                from candidate_service import CandidateService
                from search_engine import Searcher
                from unittest.mock import patch
                with tempfile.TemporaryDirectory(prefix='mhf-frozen-index-') as folder:
                    cache=Path(folder)/'cache.json';service=CandidateService(args.db,cache)
                    try:
                        service.prepare_index();service.index_thread.join(60)
                        if service.index_status()['state']!='ready':raise RuntimeError('Frozen facts generation failed')
                        service.ingest(payload,state['result']);environment=service.archive.worker_environment()
                        with patch.dict(os.environ,environment),contextlib.closing(sqlite3.connect(args.db)) as db:
                            import search_data
                            search_data._CACHE.clear()
                            compiled=Searcher(db)
                            if not compiled.compiled_vectors_used:raise RuntimeError('Frozen compiled vectors not loaded')
                        service.close();service=CandidateService(args.db,cache)
                        with patch('skill_engine.Engine.evaluate',side_effect=AssertionError('Cached report recalculated')):
                            cached=service.query(payload)
                        if not cached['results']:raise RuntimeError('Frozen restart lost confirmed witnesses')
                        result['checks']['precompute_restart']={'confirmed':cached['confirmed_builds'],'compiled_vectors':True}
                    finally:service.close()
        result['ok'] = True
    except BaseException:
        result['error'] = traceback.format_exc()
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


def pinned_launcher_command(argv, executable=None, frozen=None):
    # Windows may pin the visible desktop payload rather than the stable launcher.
    is_frozen = getattr(sys, 'frozen', False) if frozen is None else frozen
    if not is_frozen or list(argv) not in ([], ['--background']):
        return None
    exe = Path(executable or sys.executable).resolve()
    if exe.name.casefold() != 'mhfdesktop.exe' or exe.parent.name.casefold() != 'app':
        return None
    launcher = exe.parent.parent / 'MHFSimulator.exe'
    if not launcher.is_file():
        raise FileNotFoundError('MHFSimulator.exe not found. Extract the complete portable ZIP and start MHFSimulator.exe.')
    return [str(launcher), *argv]


def redirect_pinned_launch(argv):
    # Re-enter the normal updater, database and single-instance path. Do not
    # inherit PyInstaller's DLL directory or frozen parent state across EXEs.
    command = pinned_launcher_command(argv)
    if command is None:
        return False
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    env = os.environ.copy()
    env['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    subprocess.Popen(command, cwd=str(Path(command[0]).parent), env=env)
    return True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Never enter the desktop mutex, tray or GUI for a solver child process.
    if argv[:1] == ['--search-worker']:
        return worker(argv[1:])
    if argv[:1] == ['--self-test']:
        with open(os.devnull, 'w', encoding='utf-8') as sink:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                return smoke_test(argv[1:])
    from desktop import main as desktop_main
    from desktop_lifecycle import report_error
    try:
        if redirect_pinned_launch(argv):
            return 0
        desktop_main(argv)
        return 0
    except Exception as exc:
        report_error(f'ERROR: {exc}')
        return 1


if __name__ == '__main__':
    multiprocessing.freeze_support()
    from installer_guard import installer_guard
    with installer_guard():
        raise SystemExit(main())
