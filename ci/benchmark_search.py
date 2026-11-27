"""Reproduce the reported 4-skill search against a private local integrated DB."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--db',type=Path,required=True)
p.add_argument('--engine-dir',type=Path,default=Path(__file__).resolve().parents[1])
p.add_argument('--out',type=Path,required=True)
a=p.parse_args();sys.path.insert(0,str(a.engine_dir.resolve()))
from search_engine import Searcher

q=dict(weapon_type='MS',sex='男',g_poogie=True,premium_poogie_clothes=True,
       required=[{'skill':s} for s in ['磁斬鎚技【磁星】','不退ノ構','剛撃+6','一閃+2']],
       seconds=20,limit=5,search_strategy='adaptive')
with sqlite3.connect(f'file:{a.db.resolve().as_posix()}?mode=ro',uri=True) as db:
    r=Searcher(db).search(q)
a.out.write_text(json.dumps({'request':q,'response':r},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:r[k] for k in ('status','elapsed_seconds','attempts','rejected')},ensure_ascii=False))
print('verified candidates:',len(r['results']))
