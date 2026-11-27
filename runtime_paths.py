"""Resolve the writable distribution root, not PyInstaller's internal library directory."""
import sys
from pathlib import Path


def app_root():
    # External data and UI stay alongside the EXE, including after an update.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def search_command(root, db, request, output, log):
    # A frozen executable is not a Python interpreter; explicitly dispatch a worker.
    if getattr(sys, 'frozen', False):
        prefix = [sys.executable, '--search-worker', '--worker-log', str(log)]
    else:
        prefix = [sys.executable, str(root / 'search_engine.py')]
    return prefix + ['--db', str(db), '--request', str(request), '--out', str(output)]
