"""Bounded process-local immutable DB snapshots; never change the source database."""
from collections import OrderedDict, defaultdict
from pathlib import Path
import time
from defense import armor_values

_CACHE=OrderedDict()


def database_identity(db):
    name=db.execute('PRAGMA database_list').fetchone()[2]
    if not name or db.in_transaction: return None
    p=Path(name);st=p.stat()
    return (str(p.resolve()),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns,
            db.execute('PRAGMA data_version').fetchone()[0])


def snapshot(db, loader):
    identity=database_identity(db)
    start=time.perf_counter()
    if identity is not None and identity in _CACHE:
        value=_CACHE.pop(identity);_CACHE[identity]=value
        return value,True,time.perf_counter()-start
    value=loader()
    if identity is not None:
        _CACHE[identity]=value
        while len(_CACHE)>1: _CACHE.popitem(last=False)
    return value,False,time.perf_counter()-start


def indices(items,points,zen,auto):
    providers=defaultdict(set);lookup=defaultdict(list)
    for eid,row in items.items():
        for name in {eid,row['ja'],row['en']}:
            if name is not None: lookup[row['kind'],name].append(eid)
        for sid in set(points.get(eid,{}))|set(zen.get(eid,{}))|set(auto.get(eid,{})):
            providers[sid].add(eid)
    return dict(providers),dict(lookup)


class ArmorStats(dict):
    """Defense-only/default queries do not need every armor's resistance JSON."""
    def __init__(self,items):
        super().__init__();self.items=items

    def __missing__(self,eid):
        value=armor_values(self.items[eid]['metadata'],None);self[eid]=value;return value
