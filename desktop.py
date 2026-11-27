"""Windows desktop shell, with the existing local FastAPI application."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import socket
import sys
import threading
import time
import urllib.request
import json

from desktop_lifecycle import (SingleInstance, Preferences, Startup, TrayController,
                               set_app_id, report_error)

from windows_setup import ROOT, PORT, MASTER, BASE, check_db


def profile_directory():
    # A stable per-user profile survives changes to the install directory.
    base = os.environ.get('LOCALAPPDATA')
    if not base:
        raise RuntimeError('LOCALAPPDATA is not set')
    return Path(base) / 'MHFSkillSimulator' / 'WebView2'


def select_database(root):
    # Prefer the integrated database; do not build or overwrite it during launch.
    path = root / MASTER
    if not path.is_file():
        path = root / BASE
    if not path.is_file():
        raise FileNotFoundError('DB not found. Place mhf_master.sqlite next to the executable, or run setup_windows.bat in the source edition.')
    return check_db(path, master=(path.name == MASTER))


@contextmanager
def local_server(db_path, port=PORT, game_priority=None):
    # Reserve the port before starting the server; never connect to an unrelated service.
    import uvicorn
    from web_api import create_app
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server = None
    worker = None
    try:
        if os.name == 'nt':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is busy. Close the other simulator or local service first.') from exc
        url = f'http://127.0.0.1:{sock.getsockname()[1]}/'
        server = uvicorn.Server(uvicorn.Config(create_app(db_path, game_priority=game_priority), host='127.0.0.1',
                                              port=port, access_log=False,
                                              timeout_graceful_shutdown=3))
        worker = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        worker.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if not worker.is_alive():
                raise RuntimeError('Local server stopped during startup.')
            if server.started:
                try:
                    with opener.open(url + 'api/health', timeout=2) as response:
                        if json.load(response).get('ready'):
                            break
                except (OSError, ValueError):
                    pass
            time.sleep(.1)
        else:
            raise RuntimeError('Local server health check timed out.')
        yield url
    finally:
        # Trigger the FastAPI lifespan cleanup, including any active search process.
        if server is not None:
            server.should_exit = True
        if worker is not None and worker.is_alive():
            worker.join(timeout=10)
            if worker.is_alive():
                server.force_exit = True
                worker.join(timeout=3)
                if worker.is_alive():
                    sock.close()
                    raise RuntimeError('Local server did not shut down cleanly.')
        sock.close()


def open_window(url, root, profile, webview, instance=None, background=False, startup_report=None):
    # Retain favorites and inventory in this dedicated browser profile.
    profile.mkdir(parents=True, exist_ok=True)
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    webview.settings['ALLOW_FILE_URLS'] = False
    from desktop_safety import DesktopBridge
    bridge = DesktopBridge(profile.parent / 'backups', url, startup_report, root)
    window = webview.create_window('MHF-ZZ Skill Simulator', url, js_api=bridge, width=1280,
                                   height=850, min_size=(800, 540),
                                   confirm_close=False)
    bridge._window = window
    # Native icon support depends on the backend; embed the ICO into the later EXE build.
    options = dict(gui='edgechromium', private_mode=False, storage_path=str(profile),
                   icon=str(root / 'web' / 'favicon.ico'), debug=False)
    if instance is None:
        webview.start(**options)
    else:
        controller = TrayController(window, Preferences(profile.parent / 'desktop_settings.json'),
                                    Startup(root), instance, url, root, background)
        window.events.closing += controller.closing
        window.events.minimized += controller.on_minimized
        window.events.restored += controller.on_restored
        try:
            webview.start(controller.start, **options)
        finally:
            controller.stop()
    return window


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--startup-report', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--background', action='store_true', help='Start in the notification area')
    args = parser.parse_args(argv)
    if os.name != 'nt':
        parser.error('Desktop window requires Windows. Use start_web.bat on Windows or web_api.py for local web.')
    profile = profile_directory()
    # Second launch signals the original window before loading the database or dependencies.
    with SingleInstance(profile) as instance:
        if not instance.primary:
            if not args.background:
                instance.activate()
            return
        # pythonw.exe has no standard streams; Uvicorn and child libraries need them.
        if sys.stdout is None or sys.stderr is None:
            profile.parent.mkdir(parents=True, exist_ok=True)
            log = (profile.parent / 'desktop.log').open('w', encoding='utf-8', buffering=1)
            if sys.stdout is None:
                sys.stdout = log
            if sys.stderr is None:
                sys.stderr = log
        db_argument = args.db.resolve() if args.db else None
        os.chdir(ROOT)
        set_app_id()
        try:
            import webview
            import pystray
        except ImportError as exc:
            raise RuntimeError('Desktop dependencies missing. Run setup_desktop.bat.') from exc
        db = db_argument if db_argument else select_database(ROOT)
        if args.db:
            check_db(db, master=(db.name == MASTER))
        # Read the preference for each new search, not only at startup.
        priority = lambda: Preferences(profile.parent / 'desktop_settings.json').game_priority
        with local_server(db, game_priority=priority) as url:
            open_window(url, ROOT, profile, webview, instance, args.background, args.startup_report)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        report_error(f'ERROR: {exc}')
        raise SystemExit(1)
