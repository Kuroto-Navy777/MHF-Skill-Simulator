"""Compare full catalogue hydration with the on-demand reader in fresh processes."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--mode',choices=['full','on-demand'],required=True)
p.add_argument('--out',type=Path,required=True)
a=p.parse_args()
start=time.perf_counter()
if a.mode=='full':
    from search_engine import Searcher as Reader
else:
    from candidate_reader import CandidateReader as Reader
import_seconds=time.perf_counter()-start
with sqlite3.connect(a.db) as db:
    start=time.perf_counter();reader=Reader(db);init_seconds=time.perf_counter()-start
    fixture=json.loads((ROOT/'ci/v120_regression_builds.json').read_text(encoding='utf-8'))['road15']
    report=reader.e.evaluate(fixture['build']);assert report['valid']
    result={'mode':a.mode,'module_import_seconds':import_seconds,'reader_init_seconds':init_seconds,
            'solver_imported':'scipy' in sys.modules}
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
                        ('peak','working','page_peak','page','nonpage_peak','nonpage','pagefile','pagefile_peak','private')]
        value=Memory();value.cb=ctypes.sizeof(value)
        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
        api=ctypes.WinDLL('psapi');api.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD]
        if not api.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb):raise ctypes.WinError()
        result.update(working_set_mib=value.working/1024**2,peak_working_set_mib=value.peak/1024**2)
a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,indent=2))
