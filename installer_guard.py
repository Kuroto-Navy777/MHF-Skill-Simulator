"""Expose a session-local activity marker for the installer and uninstaller."""
import ctypes
from ctypes import wintypes
from contextlib import contextmanager
import os

MUTEX_NAME = r'Local\MHFSkillSimulator.InstallerGuard'


@contextmanager
def installer_guard():
    # All frozen launcher, handoff and desktop processes hold a reference, not ownership.
    if os.name != 'nt':
        yield
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)
