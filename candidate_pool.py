"""Bounded verified candidate reservoir and integer-bitset activation index.

Persistence contains builds only. Restored builds cannot enter the query index
until the caller revalidates them with the current DB and hard conditions.
"""
import copy
import hashlib
import json
from collections import OrderedDict,defaultdict
from pathlib import Path
import time
from activation import attained,scoped_attained
from candidate_groups import armor_key,counts,group_hits

VERSION=120
SOFT={'required','optional','objective','seconds','limit','results_per_weapon_group',
      'structured_outcomes','collect_variants','search_strategy','full_jewel_pool','diverse_armor','dedupe_effects','live_preview','probe','candidate_target'}


def condition_key(req):
    hard={k:v for k,v in req.items() if k not in SOFT and not k.startswith('_')}
    return hashlib.sha256(json.dumps(hard,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def build_key(build):
    b=copy.deepcopy(build)
    jewels=[]
    for a in list(b.get('armor',{}).values())+[b.get('weapon',{})]:jewels.extend(a.pop('jewels',[]))
    b['decoration_multiset']=sorted(jewels)
    b['cuffs']=sorted(b.get('cuffs',[]))
    # Within one hard-condition scope both placements have already passed fixed
    # jewel and per-item packing checks. Preserve the first actual valid packing.
    return json.dumps(b,sort_keys=True,separators=(',',':'),ensure_ascii=False)


class CandidatePool:
    def __init__(self,identity,path=None,capacity=512,scope_capacity=256,max_bytes=32*1024*1024):
        self.identity=identity;self.path=Path(path) if path else None
        self.capacity=capacity;self.scope_capacity=scope_capacity;self.max_bytes=max_bytes
        self.scopes=OrderedDict();self.restored={};self.revision=0;self.last_save=0
        if self.path and self.path.is_file() and self.path.stat().st_size<=8*1024*1024:
            try:
                data=json.loads(self.path.read_text(encoding='utf-8'))
                if data['version']==VERSION and data['identity']==identity:
                    self.restored={k:v[:scope_capacity] for k,v in list(data['scopes'].items())[-4:] if isinstance(v,list)}
            except (ValueError,KeyError,TypeError,OSError): pass

    def _scope(self,key):
        if key not in self.scopes:self.scopes[key]={'hits':OrderedDict(),'postings':{},'outcomes':{},'bytes':0}
        self.scopes.move_to_end(key)
        return self.scopes[key]

    def _index(self,scope):
        postings=defaultdict(lambda:defaultdict(int))
        for i,h in enumerate(scope['hits'].values()):
            for sid,pt in scoped_attained(h['evaluation'],scope.get('sources')).items():postings[sid][pt]|=1<<i
        scope['postings']={sid:dict(tiers) for sid,tiers in postings.items()}

    def ingest(self,req,hits):
        key=condition_key(req);scope=self._scope(key);scope['sources']=req.get('zenith_sources',{});changed=False
        for h in hits:
            if not isinstance(h,dict) or not h.get('evaluation',{}).get('valid'):continue
            clean={k:copy.deepcopy(h[k]) for k in ('build','evaluation','metrics','display','new_jewels','rank') if k in h}
            identity=build_key(clean['build'])
            if identity not in scope['hits']:
                clean['_pool_bytes']=len(json.dumps(clean,ensure_ascii=False).encode())
                scope['hits'][identity]=clean;scope['bytes']+=clean['_pool_bytes'];changed=True
        while len(scope['hits'])>self.scope_capacity:
            _,old=scope['hits'].popitem(last=False);scope['bytes']-=old['_pool_bytes']
        while (sum(len(x['hits']) for x in self.scopes.values())>self.capacity or
               sum(x['bytes'] for x in self.scopes.values())>self.max_bytes or len(self.scopes)>4):
            oldest=next(iter(self.scopes))
            if oldest==key and len(self.scopes)==1:
                _,old=scope['hits'].popitem(last=False);scope['bytes']-=old['_pool_bytes']
            else:self.scopes.popitem(last=False)
        if changed:self._index(scope);self.revision+=1
        return changed

    @staticmethod
    def _mask(scope,sid,pt):
        mask=0
        for value,bits in scope['postings'].get(sid,{}).items():
            if (value<=pt if pt<0 else value>=pt):mask|=bits
        return mask

    def query(self,req,required,targets=(),limit=30):
        start=time.perf_counter();scope=self._scope(condition_key(req))
        hits=list(scope['hits'].values());mask=(1<<len(hits))-1
        for sid,pt in required.items():mask&=self._mask(scope,sid,pt)
        matched=[{k:v for k,v in h.items() if k!='_pool_bytes'} for i,h in enumerate(hits) if mask&(1<<i)]
        per_skill={f'{sid}|{pt}':(mask&self._mask(scope,sid,pt)).bit_count() for sid,pt in targets}
        status='confirmed' if matched else ('cached_unfound' if hits else 'unexplored')
        return {'status':status,'results':matched[:limit],'pool_counts':counts(hits),**counts(matched),
                'candidate_counts':per_skill,'revision':self.revision,'scope':condition_key(req),
                'filter_seconds':round(time.perf_counter()-start,6),'complete_game_search':False}

    def builds(self,req):
        scope=self._scope(condition_key(req))
        return [h['build'] for h in scope['hits'].values()]

    def exclusion_sets(self,req):
        return [dict(key) for key in dict.fromkeys(armor_key(b) for b in self.builds(req))][-128:]

    def save(self):
        if not self.path:return
        data={'version':VERSION,'identity':self.identity,'scopes':
              {k:[h['build'] for h in s['hits'].values()] for k,s in self.scopes.items()}}
        raw=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        if len(raw.encode())>8*1024*1024:return
        self.path.parent.mkdir(parents=True,exist_ok=True);tmp=self.path.with_suffix('.tmp')
        try:
            tmp.write_text(raw,encoding='utf-8');tmp.replace(self.path)
        except OSError:pass
