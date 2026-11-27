"""Server-side candidate reuse. Solver jobs remain cancellable separate processes."""
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from candidate_pool import CandidatePool,condition_key
from candidate_validation import validate
from candidate_groups import counts,group_hits


class CandidateService:
    def __init__(self,db_path,cache_path=None):
        self.path=Path(db_path);self.cache_path=cache_path;self.lock=threading.RLock()
        self.identity=None;self.db=None;self.searcher=None;self.pool=None;self.outcomes={};self.primed=set()

    def fingerprint(self):
        st=self.path.stat()
        return hashlib.sha256(repr((str(self.path.resolve()),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)).encode()).hexdigest()

    def _ready(self):
        identity=self.fingerprint()
        if identity!=self.identity:
            self.close()
            from candidate_reader import CandidateReader
            self.db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,check_same_thread=False)
            self.searcher=CandidateReader(self.db);self.pool=CandidatePool(identity,self.cache_path)
            self.identity=identity;self.outcomes={};self.primed=set()
        return self.searcher

    def _prepare(self,req):
        s=self._ready();prepared=s.prepare_request(copy.deepcopy(req))
        # Restore a whole scope against hard conditions, before applying today's
        # selected skills. Deleting a required skill can then restore older builds.
        scope=condition_key(req);old=self.pool.restored.pop(scope,[])
        if old:
            broad={**prepared,'required':[],'live_preview':True};hits=[]
            for build in old:
                report,reasons=validate(s,broad,build)
                if report:
                    total=sum(len(a.get('jewels',[])) for a in list(build['armor'].values())+[build.get('weapon',{})])
                    fixed=sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})])
                    hits.append({'build':build,'evaluation':report,'new_jewels':total-fixed})
            self.pool.ingest(req,hits)
        if scope not in self.primed:
            self.primed.add(scope)
            broad={**prepared,'required':[],'live_preview':True};adopted=[]
            for other,records in list(self.pool.scopes.items()):
                if other==scope:continue
                for hit in list(records['hits'].values())[-64:]:
                    report,reasons=validate(s,broad,hit['build'])
                    if report:
                        total=sum(len(a.get('jewels',[])) for a in list(hit['build']['armor'].values())+[hit['build'].get('weapon',{})])
                        fixed=sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})])
                        adopted.append({**hit,'evaluation':report,'new_jewels':total-fixed})
            self.pool.ingest(req,adopted)
        return s,prepared

    def query(self,req,targets=(),limit=30):
        with self.lock:
            try:
                s,prepared=self._prepare(req)
                wanted=s.requirements(prepared['required'])
                resolved=[s.requirement(t) for t in list(targets)[:1000]]
            except ValueError as exc:
                return {'status':'input_conflict','reason':str(exc),'results':[],'confirmed_builds':0,
                        'distinct_armor':0,'decoration_variants':0,'database_identity':self.identity,'complete_game_search':False}
            result=self.pool.query(req,wanted,resolved,limit=self.pool.capacity)
            all_hits=s.rank(result['results'],prepared)
            if req.get('diverse_armor',True):
                grouped=group_hits(all_hits);result['results']=[{k:v for k,v in h.items() if k!='variants'} for h in grouped[:limit]]
            else:result['results']=all_hits[:limit]
            result['reservoir_counts']=result.pop('pool_counts')
            outcome=self.outcomes.get(self._query_key(req))
            if outcome:
                result['exploration_status']=outcome['status']
                if outcome.get('reason'):result['reason']=outcome['reason']
                if not all_hits and outcome['status'] in ('time_limit','model_exhausted','input_conflict'):
                    result['status']=outcome['status']
            result['data_cache_hit']=s.data_cache_hit
            result['memory_bytes']=sum(x['bytes'] for x in self.pool.scopes.values())
            result['database_identity']=self.identity
            return result

    def variants(self,req,armor,exclude=None):
        from candidate_groups import armor_key
        from candidate_pool import build_key
        with self.lock:
            s,prepared=self._prepare(req)
            result=self.pool.query(req,s.requirements(prepared['required']),limit=self.pool.capacity)
            key=tuple((p,armor.get(p)) for p in ('head','body','arm','waist','leg'))
            hits=[h for h in result['results'] if armor_key(h['build'])==key and
                  (exclude is None or build_key(h['build'])!=build_key(exclude))]
            return {'results':s.rank(hits,prepared)[:8],'variant_count':len(hits),'complete_game_search':False}

    def evaluate(self,build):
        with self.lock:
            return self._ready().e.evaluate(build)

    def coverage_targets(self,req,pass_number):
        """Idle bootstrap gets useful decoration sets, after a fast first batch."""
        if req.get('required') or req.get('optional') or pass_number<2:return []
        from skill_engine import WEAPON_SECRET
        with self.lock:
            s=self._ready();targets=[]
            family=s.e.names.get(('normal',WEAPON_SECRET.get(req.get('weapon_type'))))
            if family:
                thresholds=[t['points'] for t in s.e.levels[family] if t['points']>0]
                if thresholds:targets.append({'skill':family,'points':max(thresholds),'weight':4})
            names=['剛撃+6','一閃+3','不退ノ構','豪放+3','纏雷','猛進','閃転','巧撃','雌伏','獅子奮迅']
            if pass_number>=3:names+=['耳栓強化+1','巧流']
            for name in names:
                try:sid,pt=s.requirement({'skill':name})
                except ValueError:continue
                targets.append({'skill':sid,'points':pt,'weight':1})
            return targets

    def _query_key(self,req):
        return condition_key(req)+json.dumps(sorted(self.searcher.requirements(req.get('required',[])).items()))

    def seed(self,req,explore=False):
        with self.lock:
            result=self.query(req,limit=8)
            seeds=[h['build'] for h in result['results']]
            exclusions=self.pool.exclusion_sets(req) if self.pool and explore else []
            # Do not exclude the sole armor when all five parts are fixed.
            if all(req.get('armor',{}).get(p) for p in ('head','body','arm','waist','leg')):exclusions=[]
            return seeds,exclusions

    def ingest(self,req,result,persist=True):
        with self.lock:
            s,prepared=self._prepare(req)
            hits=[entry.get('witness',entry) for entry in result.get('results',[])]
            # Workers publish only independently verified hits. Recheck their
            # activation index; restored disk records use the stricter full validator.
            self.pool.ingest(req,hits)
            if not req.get('_excluded_armor_sets'):
                self.outcomes[self._query_key(req)]={'status':result.get('status','unexplored'),'reason':result.get('reason')}
                if len(self.outcomes)>128:self.outcomes.pop(next(iter(self.outcomes)))
            for entry in result.get('results',[]):
                if 'target' not in entry:continue
                extended={**req,'required':req['required']+[entry['target']]}
                status='confirmed' if entry.get('status')=='found' else entry.get('search_status','unexplored')
                self.outcomes[self._query_key(extended)]={'status':status}
            while len(self.outcomes)>128:self.outcomes.pop(next(iter(self.outcomes)))
            if persist:self.pool.save()

    def close(self):
        if self.pool:self.pool.save()
        if self.db:self.db.close()
        self.db=None;self.searcher=None;self.pool=None;self.identity=None
