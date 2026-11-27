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
        self.identity=None;self.db=None;self.searcher=None;self.pool=None;self.outcomes={};self.primed=set();self.archive=None;self.index_thread=None;self.index_cancel=threading.Event();self.index_error=None

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
            if self.cache_path:
                try:
                    from search_archive import SearchArchive
                    self.archive=SearchArchive(self.path,Path(self.cache_path).with_suffix('.search.sqlite'))
                except (OSError,ValueError,sqlite3.Error):self.archive=None;self.index_error='persistent calculation cache unavailable'
        return self.searcher

    def _prepare(self,req):
        s=self._ready();prepared=s.prepare_request(copy.deepcopy(req))
        # Restore a whole scope against hard conditions, before applying today's
        # selected skills. Deleting a required skill can then restore older builds.
        scope=condition_key(req)
        if self.archive and self.archive.has_scope(req):
            changed=[b for b in self.pool.restored.get(scope,[]) if not self.archive.contains_build(req,b)]
            if changed:
                broad={**prepared,'required':[],'live_preview':True};checked=[];invalid=False
                for build in changed:
                    report,reasons=validate(s,broad,build)
                    if report:checked.append({'build':build,'evaluation':report})
                    else:invalid=True
                if invalid:self.archive.invalidate_scope(req)
                if checked:self.archive.ingest(req,checked)
            if self.archive.has_scope(req):
                self.pool.restored.pop(scope,None);self.primed.add(scope);return s,prepared
        old=self.pool.restored.pop(scope,[])
        if old:
            broad={**prepared,'required':[],'live_preview':True};hits=[]
            for build in old:
                report,reasons=validate(s,broad,build)
                if report:
                    total=sum(len(a.get('jewels',[])) for a in list(build['armor'].values())+[build.get('weapon',{})])
                    fixed=sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})])
                    hits.append({'build':build,'evaluation':report,'new_jewels':total-fixed})
            self.pool.ingest(req,hits)
            if self.archive:self.archive.ingest(req,hits)
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
            if self.archive:
                for hit in self.archive.cross_scope(req):
                    report,reasons=validate(s,broad,hit['build'])
                    if report:
                        total=sum(len(a.get('jewels',[])) for a in list(hit['build']['armor'].values())+[hit['build'].get('weapon',{})]);fixed=sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})])
                        adopted.append({**hit,'evaluation':report,'new_jewels':total-fixed})
            self.pool.ingest(req,adopted)
            if self.archive:self.archive.ingest(req,adopted)
        return s,prepared

    def query(self,req,targets=(),limit=30):
        with self.lock:
            try:
                s,prepared=self._prepare(req)
                wanted=s.requirements(prepared['required'])
                resolved=[s.requirement(t) for t in list(targets)[:1000]]
                normalized_optional=[{'skill':sid,'points':pt,'weight':weight} for (sid,pt),weight in s.optional_requirements(prepared).items()]
            except ValueError as exc:
                return {'status':'input_conflict','reason':str(exc),'results':[],'confirmed_builds':0,
                        'distinct_armor':0,'decoration_variants':0,'database_identity':self.identity,'complete_game_search':False}
            result=self.pool.query(req,wanted,resolved,limit=self.pool.capacity)
            persistent=bool(self.archive and self.archive.has_scope(req))
            if persistent:result=self.archive.query({**req,'optional':normalized_optional},wanted,resolved,limit=max(64,limit))
            all_hits=s.rank(result['results'],prepared)
            if req.get('diverse_armor',True):
                grouped=group_hits(all_hits)
                for h in grouped:
                    if h.get('archive_variant_count'):h['variant_count']=h['archive_variant_count']
                result['results']=[{k:v for k,v in h.items() if k!='variants'} for h in grouped[:limit]]
            else:result['results']=all_hits[:limit]
            if not persistent:result['reservoir_counts']=result.pop('pool_counts')
            if self.archive:
                self._interval_proofs(req,prepared,resolved,s)
                result['candidate_states']=self.archive.assess(req,wanted,resolved,result.get('candidate_counts',{}))
                if not all_hits and any(cert.get('coverage_complete') and __import__('search_archive').requirements_dominate(wanted,core) for core,cert in self.archive.proofs(req)):
                    result['status']='proven_infeasible';result['proof_scope']='supported_search_model'
                if not all_hits and result['status'] not in ('proven_infeasible','data_incomplete') and any(__import__('search_archive').requirements_dominate(wanted,core) for core,cert in self.archive.proofs(req)):
                    result['status']='data_incomplete';result['reason']='Supported model is infeasible, but unresolved eligible data prevents a complete infeasibility claim.'
                attempt=self.archive.attempt(req,wanted)
                if attempt:
                    result['exploration_status']=attempt['status'];result['feasibility_recent']=bool(attempt['retry_after']>0 and not all_hits);result['retry_after']=attempt['retry_after']
                result['precomputed']=self.archive.status()
            outcome=self.outcomes.get(self._query_key(req))
            if outcome:
                result['exploration_status']=outcome['status']
                if outcome.get('reason'):result['reason']=outcome['reason']
                if not all_hits and result['status'] not in ('proven_infeasible','data_incomplete') and outcome['status'] in ('time_limit','model_exhausted','input_conflict'):
                    result['status']=outcome['status']
            result['data_cache_hit']=s.data_cache_hit
            result['memory_bytes']=sum(x['bytes'] for x in self.pool.scopes.values())
            result['database_identity']=self.identity
            if self.archive:self.archive.park()
            return result

    def variants(self,req,armor,exclude=None):
        from candidate_groups import armor_key
        from candidate_pool import build_key
        with self.lock:
            s,prepared=self._prepare(req)
            if self.archive and self.archive.has_scope(req):
                result=self.archive.variants(req,s.requirements(prepared['required']),armor,exclude)
                result['results']=s.rank(result['results'],prepared);return result
            result=self.pool.query(req,s.requirements(prepared['required']),limit=self.pool.capacity)
            key=tuple((p,armor.get(p)) for p in ('head','body','arm','waist','leg'))
            hits=[h for h in result['results'] if armor_key(h['build'])==key and
                  (exclude is None or build_key(h['build'])!=build_key(exclude))]
            return {'results':s.rank(hits,prepared)[:8],'variant_count':len(hits),'complete_game_search':False}

    def evaluate(self,build):
        with self.lock:
            report=self._ready().e.evaluate(build)
            if self.archive:self.archive.park()
            return report

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
            if self.archive:
                self.archive.ingest(req,[h for h in hits if h.get('build')])
                if result.get('feasibility_only'):self.archive.put_attempt(req,s.requirements(prepared['required']),result.get('status','unknown'))
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
            if self.archive:self.archive.park()

    def _coverage(self,prepared,searcher):
        request=copy.deepcopy(prepared)
        try:
            for part,cfg in request.get('armor',{}).items():cfg['item']=searcher.e.equipment(cfg['item'],part)['id']
            for part,keys in request.get('armor_candidates',{}).items():request['armor_candidates'][part]=[searcher.e.equipment(x,part)['id'] for x in keys]
            for key,kind in [('cuffs','cuff'),('cuff_candidates','cuff'),('jewel_candidates','jewel')]:
                if key in request:request[key]=[searcher.e.equipment(x,kind)['id'] for x in request[key]]
            if request.get('weapon',{}).get('template'):request['weapon']['template']=searcher.e.equipment(request['weapon']['template'],'weapon_template')['id']
            return self.archive.coverage(request)
        except (ValueError,KeyError,TypeError):return {'complete':False,'reason':'unresolved_selection'}

    def _interval_proofs(self,req,prepared,targets,searcher):
        from skill_engine import WEAPON_SECRET
        known={tuple(sorted(core.items())) for core,cert in self.archive.proofs(req)}
        for sid,pt in set(targets)|set(searcher.requirements(prepared.get('required',[])).items()):
            name=searcher.e.skills[sid]['ja']
            if name in WEAPON_SECRET.values() and name!=WEAPON_SECRET.get(prepared['weapon_type']):
                threshold=min(t['points'] for t in searcher.e.levels[sid] if t['points']>0);key=((sid,threshold),)
                if key in known:continue
                known.add(key)
                self.archive.put_proof(req,{sid:threshold},{'kind':'semantic_rule','rule':'wrong_weapon_secret','coverage_complete':True,'source':self.identity,'calculation':self.archive.calculation})
        if self.archive.open_facts() is None:return
        from external import normalize
        meal=searcher.e.meal_level(normalize(prepared.get('external')))
        proofs=self.archive.proofs(req)
        if any(not cert.get('coverage_complete') for core,cert in proofs):
            coverage=self._coverage(prepared,searcher)
            if coverage['complete']:
                for core,cert in proofs:
                    if not cert.get('coverage_complete'):self.archive.put_proof(req,core,{**cert,'coverage_complete':True,'coverage':coverage})
        existing={tuple(sorted(core.items())) for core,cert in proofs}
        for sid,pt in set(targets)|set(searcher.requirements(prepared.get('required',[])).items()):
            if meal and meal['skill_id']==sid and pt>0 and meal['points']>=pt:continue
            allowed=prepared.get('zenith_sources',{}).get(sid) if sid.startswith('zenith:') else None
            cert=self.archive.safe_interval(sid,pt,allowed)
            if cert:cert['coverage_complete']=self._coverage(prepared,searcher)['complete'] or bool(allowed and self.archive.supply_coverage(allowed))
            if cert and ((sid,pt),) not in existing:self.archive.put_proof(req,{sid:pt},cert)

    def prepare_index(self):
        with self.lock:
            self._ready()
            if not self.archive:return {'state':'unavailable','reason':self.index_error}
            if self.index_thread and self.index_thread.is_alive():return {'state':'building'}
            archive=self.archive;self.index_cancel.clear()
            def build():
                try:
                    if __import__('os').name=='nt':
                        import ctypes
                        kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentThread.restype=ctypes.c_void_p;kernel.SetThreadPriority.argtypes=[ctypes.c_void_p,ctypes.c_int];kernel.SetThreadPriority(kernel.GetCurrentThread(),-2)
                    if archive.open_facts() is None:archive.prepare_facts(self.index_cancel)
                except InterruptedError:pass
                except (OSError,ValueError,sqlite3.Error,__import__('ctypes').ArgumentError) as exc:self.index_error=type(exc).__name__;archive.fact_state='error'
            self.index_thread=threading.Thread(target=build,name='MHF precompute catalogue',daemon=True);self.index_thread.start()
            return {'state':'preparing'}

    def index_status(self):
        with self.lock:
            self._ready()
            return {**(self.archive.status() if self.archive else {'state':'unavailable'}),'error':self.index_error}

    def plan_idle(self,req,targets):
        with self.lock:
            result=self.query(req,targets,limit=1)
            if not self.archive:return None
            if result['status'] in ('input_conflict','proven_infeasible','data_incomplete'):return None
            s,prepared=self._prepare(req)
            normalized=[{'skill':sid,'points':pt} for sid,pt in (s.requirement(t) for t in targets)]
            unknown=[t for t in normalized if result.get('candidate_states',{}).get(f"{t['skill']}|{t['points']}",{}).get('state')=='unknown' and not any(x['skill']==t['skill'] and x.get('points')==t['points'] for x in req.get('required',[]))]
            self.archive.enqueue(req,unknown if result['confirmed_builds'] else [None])
            return self.archive.next_work(req)

    def finish_idle(self,key,status):
        with self.lock:
            if self.archive:self.archive.finish_work(key,status)

    def accept_proof(self,req,certificate):
        # Only trusted feasibility workers or local generation call this method.
        with self.lock:
            searcher,prepared=self._prepare(req)
            if self.archive:
                certificate={**certificate,'coverage':self._coverage(prepared,searcher)};certificate['coverage_complete']=certificate['coverage']['complete']
                self.archive.put_proof(req,searcher.requirements(prepared['required']),certificate)
                return certificate

    def close(self):
        self.index_cancel.set()
        if self.index_thread and self.index_thread.is_alive():self.index_thread.join(3)
        self.index_thread=None
        if self.archive:self.archive.close();self.archive=None
        if self.pool:self.pool.save()
        if self.db:self.db.close()
        self.db=None;self.searcher=None;self.pool=None;self.identity=None
