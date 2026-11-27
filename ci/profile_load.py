"""Windows contention simulation; never launches or modifies the game process."""
import argparse
import copy
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--engine-dir',type=Path,default=ROOT)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
if os.name!='nt':p.error('Windows load profiler required')
kernel=ctypes.WinDLL('kernel32',use_last_error=True);psapi=ctypes.WinDLL('psapi')
kernel.GetCurrentProcess.restype=wintypes.HANDLE
kernel.GetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.POINTER(ctypes.c_size_t),ctypes.POINTER(ctypes.c_size_t)]
kernel.SetProcessAffinityMask.argtypes=[wintypes.HANDLE,ctypes.c_size_t]
class Memory(ctypes.Structure):
    _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                ('peak','working','page_peak','page','nonpage_peak','nonpage','pagefile','pagefile_peak','private')]
psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
kernel.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
own=kernel.GetCurrentProcess();original=ctypes.c_size_t();system=ctypes.c_size_t()
if not kernel.GetProcessAffinityMask(own,ctypes.byref(original),ctypes.byref(system)):raise ctypes.WinError()
mask=original.value&-original.value
data=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))['road15']
q=copy.deepcopy(data['build']);q['armor']={};q.pop('cuffs',None)
q.update(required=data['required'],seconds=4,limit=5,search_strategy='adaptive',diverse_armor=True,armor_level_mode='first')
report={'engine_version':(a.engine_dir/'VERSION').read_text().strip(),'scenario':'one logical CPU; foreground 1.5ms per 10ms; below-normal search worker',
        'solver_budget_seconds':4,'real_game_started':False}
with tempfile.TemporaryDirectory(prefix='mhf-contention-') as d:
    d=Path(d);request=d/'request.json';output=d/'result.json';request.write_text(json.dumps(q),encoding='utf-8')
    if not kernel.SetProcessAffinityMask(own,mask):raise ctypes.WinError()
    try:
        with (d/'worker.log').open('wb') as log:
            start=time.perf_counter()
            # The venv python.exe is a Windows redirector. Measure the actual
            # interpreter process, loading the same venv's ABI-compatible packages.
            executable=getattr(sys,'_base_executable',sys.executable)
            child=subprocess.Popen([executable,str(a.engine_dir.resolve()/'search_engine.py'),'--db',str(a.db.resolve()),
                                    '--request',str(request),'--out',str(output)],stdout=log,stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS,
                                   env={**os.environ,'PYTHONPATH':str(Path(sys.prefix)/'Lib/site-packages')+os.pathsep+str(a.engine_dir.resolve()),'PYTHONUTF8':'1','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            if not kernel.SetProcessAffinityMask(int(child._handle),mask):raise ctypes.WinError()
            delays=[];peak=0;tick=time.perf_counter()+.01
            while child.poll() is None and time.perf_counter()-start<30:
                time.sleep(max(0,tick-time.perf_counter()));delays.append(max(0,time.perf_counter()-tick))
                stop=time.perf_counter()+.0015
                while time.perf_counter()<stop:hashlib.sha256(b'x'*4096).digest()
                value=Memory();value.cb=ctypes.sizeof(value)
                if psapi.GetProcessMemoryInfo(int(child._handle),ctypes.byref(value),value.cb):peak=max(peak,value.peak)
                tick+=.01
            if child.poll() is None:child.kill()
            child.wait(timeout=5)
            creation,exit_time,kern,user=(wintypes.FILETIME() for _ in range(4))
            kernel.GetProcessTimes(int(child._handle),ctypes.byref(creation),ctypes.byref(exit_time),ctypes.byref(kern),ctypes.byref(user))
            seconds=lambda t:((t.dwHighDateTime<<32)|t.dwLowDateTime)/1e7
            delays.sort();result=json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
            report.update(worker_exit=child.returncode,worker_wall_seconds=time.perf_counter()-start,
                          worker_cpu_seconds=seconds(kern)+seconds(user),worker_peak_mib=peak/1024**2,
                          foreground_samples=len(delays),foreground_p95_delay_ms=1000*delays[int(len(delays)*.95)-1],
                          foreground_max_delay_ms=1000*max(delays),search_status=result.get('status'),
                          verified_results=len(result.get('results',[])),rejected=result.get('rejected'))
            if child.returncode!=0:raise RuntimeError((d/'worker.log').read_text(encoding='utf-8',errors='replace'))
    finally:
        kernel.SetProcessAffinityMask(own,original.value)
a.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps(report,indent=2))
