"""Bounded on-demand DB reader for queries and manual verification; no solver import."""
from collections import OrderedDict
from search_contract import SearchContract
from skill_engine import Engine


class BoundedMap(OrderedDict):
    def __init__(self,limit=4096):
        super().__init__();self.limit=limit

    def __getitem__(self,key):
        value=super().__getitem__(key);self.move_to_end(key);return value

    def __setitem__(self,key,value):
        super().__setitem__(key,value);self.move_to_end(key)
        while len(self)>self.limit:self.popitem(last=False)


class LazyRows:
    def __init__(self,db,kind):
        self.db=db;self.kind=kind;self.cache=BoundedMap()

    def __getitem__(self,eid):
        if eid not in self.cache:
            if self.kind=='equipment':
                row=self.db.execute('SELECT * FROM equipment WHERE id=?',(eid,)).fetchone()
                if row is None:raise KeyError(eid)
                value=dict(row)
            elif self.kind=='abilities':
                value=[tuple(row) for row in self.db.execute('SELECT type_ja,value_ja FROM abilities WHERE equipment_id=?',(eid,))]
            else:
                value=[tuple(row) for row in self.db.execute('SELECT level,slots,defense FROM levels WHERE equipment_id=? AND slots IS NOT NULL',(eid,))]
            self.cache[eid]=value
        return self.cache[eid]

    def get(self,eid,default=None):
        try:return self[eid]
        except KeyError:return default

    def __contains__(self,eid):
        try:self[eid];return True
        except KeyError:return False


class CandidateReader(SearchContract):
    def __init__(self,db):
        self.db=db;self.e=Engine(db)
        self.items=LazyRows(db,'equipment');self.abilities=LazyRows(db,'abilities');self.levels=LazyRows(db,'levels')
        self.e._equipment_cache=BoundedMap();self.e._contribution_cache=BoundedMap();self.e._armor_levels_cache=BoundedMap()
        self.data_cache_hit=True
