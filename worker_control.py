"""OS scheduling and best-effort Windows job lifetime protection for solver children."""
import ctypes
from ctypes import wintypes
import logging
import os
import subprocess

LOG = logging.getLogger(__name__)


def creation_flags(game_priority=False):
    # Lower the scheduling priority, not the solver's constraints or candidate set.
    if os.name != 'nt':
        return 0
    return subprocess.CREATE_NO_WINDOW | (subprocess.BELOW_NORMAL_PRIORITY_CLASS if game_priority else 0)


class BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong),
                ('PerJobUserTimeLimit', ctypes.c_longlong),
                ('LimitFlags', wintypes.DWORD),
                ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t),
                ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t),
                ('PriorityClass', wintypes.DWORD),
                ('SchedulingClass', wintypes.DWORD)]


class IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount',
                'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', BasicLimits), ('IoInfo', IoCounters),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


class WorkerJob:
    def __init__(self, kernel, handle):
        self.kernel, self.handle = kernel, handle

    def close(self):
        # The last job handle closing terminates any remaining members.
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def attach_worker(proc):
    # Some managed Windows environments disallow nested jobs. Keep normal cancellation as fallback.
    if os.name != 'nt' or type(proc.pid) is not int or proc.pid<=0:
        return None
    handle = process = None
    try:
        k = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            ('SetInformationJobObject', [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('AssignProcessToJobObject', [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
        ):
            f = getattr(k, name)
            f.argtypes, f.restype = args, result
        handle = k.CreateJobObjectW(None, None)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        # PROCESS_SET_QUOTA | PROCESS_TERMINATE, required to assign a process.
        process = k.OpenProcess(0x0100 | 0x0001, False, proc.pid)
        if not process or not k.AssignProcessToJobObject(handle, process):
            raise ctypes.WinError(ctypes.get_last_error())
        job = WorkerJob(k, handle)
        handle = None
        return job
    except (OSError, AttributeError):
        LOG.warning('Solver job protection unavailable; normal shutdown cleanup remains enabled', exc_info=True)
        return None
    finally:
        if process:
            k.CloseHandle(process)
        if handle:
            k.CloseHandle(handle)


def release_job(job):
    guard = job.pop('guard', None)
    if guard is not None:
        guard.close()


def stop_worker(job, graceful=False):
    # Reap and release all handles even when termination raises.
    proc = job['process']
    try:
        if proc.poll() is None:
            if graceful:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            else:
                proc.kill()
                proc.wait(timeout=5)
    finally:
        release_job(job)
