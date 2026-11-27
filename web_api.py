"""Local browser API. Run on loopback only; no game or remote network access."""
import argparse
import hashlib
import hmac
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import closing, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from weapon_names import JA, JOIN, register

from runtime_paths import app_root, search_command
from worker_control import creation_flags, attach_worker, release_job, stop_worker
from functools import lru_cache
import logging

ROOT = app_root()
KINDS = {'head','body','arm','waist','leg','jewel','cuff','weapon_template'}
WEAPON_TYPES = {'SnS','DB','GS','LS','Hammer','HH','Lance','GL','SA','Tonfas','MS','HBG','LBG','Bow'}

# Keep generated data outside the distributed source archive; open it read-only.
def connect(path, weapon_functions=True):
    db = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    if weapon_functions:
        register(db)
    return db

# Hydrate IDs only for returned builds, preserving original values for editing.
def enrich(db, build):
    items = {}
    for a in list(build.get('armor', {}).values()) + [build.get('weapon', {})]:
        for k in ([a['item']] if 'item' in a else []) + a.get('jewels', []):
            items[k] = None
    for k in build.get('cuffs', []):
        items[k] = None
    for k in items:
        rows = db.execute('SELECT id,ja,en,slots FROM equipment WHERE id=?',(k,)).fetchall()
        if not rows:rows=db.execute('SELECT id,ja,en,slots FROM equipment WHERE ja=? OR en=?',(k,k)).fetchall()
        if len(rows) == 1:
            items[k] = dict(rows[0])
    w=build.get('weapon',{})
    weapon=None
    if w.get('virtual') is True:
        weapon={'virtual':True,'ja':'仮想武器スロット','en':'Virtual weapon slots','slots':w['slots'],'slot_mode':w['slot_mode']}
    if 'page' in w:
        row=db.execute(f'SELECT v.name_source,{JA} AS name_ja,COALESCE({JA},v.name_source) AS ja,v.name_source AS en,v.weapon_type,v.upstream_id,v.rarity,v.attack,v.slots_reported,v.slot_mode,v.level,v.intrinsic_raw,v.category FROM {JOIN} WHERE v.weapon_type=? AND v.page=? AND v.anchor=?',(build['weapon_type'],w['page'],w['anchor'])).fetchone()
        weapon=dict(row) if row else None
    return {'items':items,'weapon':weapon}

# Search jobs run in separate processes, so cancellation terminates the actual solver.
def create_app(db_path, game_priority=None, candidate_cache_path=None):
    db_path=Path(db_path).resolve()
    from candidate_service import CandidateService
    if candidate_cache_path is None and os.environ.get('LOCALAPPDATA'):
        candidate_cache_path=Path(os.environ['LOCALAPPDATA'])/'MHFSkillSimulator'/'search-cache-v120.json'
    candidates=CandidateService(db_path,candidate_cache_path)
    jobs={}
    lock=threading.Lock()
    temp=tempfile.TemporaryDirectory(prefix='mhf-web-')

    # Stop active solver subprocesses when the local server closes.
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            idle.close()
            with lock:
                for j in jobs.values():
                    try:
                        stop_worker(j)
                    except (OSError, subprocess.TimeoutExpired):
                        logging.getLogger(__name__).exception('Solver cleanup failed')
            candidates.close()
            temp.cleanup()

    app=FastAPI(title='MHF Skill Simulator',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan)
    app.state.temp=temp
    app.state.jobs=jobs
    app.state.candidates=candidates
    # Serve JavaScript explicitly, independently of Windows MIME registry settings.
    @app.get('/static/app.js', include_in_schema=False)
    def app_script():
        return FileResponse(ROOT/'web'/'app.js', media_type='text/javascript', headers={'Cache-Control':'no-cache'})

    app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')

    # Restrict this local-only app to loopback hosts and same-origin browser requests.
    @app.middleware('http')
    async def local_only(request:Request, call_next):
        from starlette.responses import JSONResponse
        host=request.headers.get('host','')
        origin=request.headers.get('origin')
        if not (host.split(':')[0] in ('localhost','127.0.0.1','testserver')) or (origin and origin not in ('http://'+host,'https://'+host)):
            return JSONResponse({'detail':'local access only'},status_code=403)
        return await call_next(request)

    @app.get('/')
    def index():
        return FileResponse(ROOT/'web'/'index.html', headers={'Cache-Control':'no-cache'})

    @lru_cache(maxsize=1)
    def health_data(identity):
        # The desktop and browser both request health during startup. Reuse counts
        # for the same read-only DB, invalidating when its file identity changes.
        with closing(connect(db_path, weapon_functions=False)) as db:
            counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('equipment','skills','ferias_weapons')}
            from master_data import has_master
            return {'ready':True,'counts':counts,'rain_verified':False,'master':has_master(db),'version':(ROOT/'VERSION').read_text(encoding='utf-8').strip() if (ROOT/'VERSION').is_file() else 'dev'}

    @app.get('/api/health')
    def health():
        try:
            st=db_path.stat()
            return health_data((st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns))
        except (OSError,sqlite3.Error,ValueError) as e:
            return {'ready':False,'detail':str(e)}

    @app.get('/api/bounties')
    def bounty_groups():
        from bounty import GROUPS, SOURCE
        return {'groups':GROUPS,'source':SOURCE,'date':'2026-01-19'}

    @app.get('/api/bounty')
    def bounty_rule(group:str,number:int,mode:str='solo'):
        from bounty import public_rules
        try: return public_rules({'group':group,'number':number,'mode':mode})
        except ValueError as e: raise HTTPException(400,str(e)) from e

    # Expose source effects for reference only; actual Rain sigil values are user-entered.
    @app.get('/api/sigil-effects')
    def sigil_effects():
        with closing(connect(db_path, weapon_functions=False)) as db:
            rows = db.execute('SELECT row_index,cells_json FROM sigil_reference_rows WHERE table_index=0 AND row_index>0 ORDER BY row_index')
            result=[]
            for row in rows:
                cells=json.loads(row['cells_json'])
                if len(cells)>=3 and cells[0] and cells[0]!='－－－－－－':
                    from localization import sigil_reference
                    ja, detail_ja=sigil_reference(cells[0],cells[1])
                    result.append({'id':row['row_index'],'name':cells[0],'detail':cells[1],'range':cells[2],'name_ja':ja,'detail_ja':detail_ja})
            return result

    @app.get('/api/skill-reference')
    def skill_reference():
        from master_data import skill_reference as reference
        with closing(connect(db_path, weapon_functions=False)) as db:
            return reference(db,db_path.parent)

    @app.get('/api/master')
    def master_status():
        from master_data import manifest
        with closing(connect(db_path, weapon_functions=False)) as db:
            data=manifest(db)
            return {'master':data,'legacy':data is None}

    @app.get('/api/skills')
    def skills():
        with closing(connect(db_path, weapon_functions=False)) as db:
            return [dict(r) for r in db.execute('SELECT s.id,s.kind,s.ja AS family_ja,s.en AS family_en,l.points,l.ja,l.en FROM skills s JOIN skill_levels l ON l.skill_id=s.id WHERE (l.points>0 OR l.ja=?) ORDER BY s.kind,s.id,l.points',('青魂',))]

    @app.get('/api/items')
    def items(kind:str,q:str='',weapon_type:str='MS',limit:int=Query(60,ge=1,le=100)):
        if kind not in KINDS|{'weapon'} or weapon_type not in WEAPON_TYPES or len(q)>100:
            raise HTTPException(400,'invalid item query')
        # Escape LIKE wildcards so the query remains literal.
        pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        with closing(connect(db_path)) as db:
            if kind=='weapon':
                rows=db.execute(f"""SELECT v.weapon_type,v.upstream_id,v.page,v.anchor,v.name_source AS en,COALESCE({JA},v.name_source) AS ja,v.level,v.rarity,v.attack,v.category,v.slots_reported AS slots,v.slot_mode,w.conflict FROM {JOIN} WHERE v.weapon_type=? AND (v.name_source LIKE ? ESCAPE '\\' OR {JA} LIKE ? ESCAPE '\\') ORDER BY w.conflict,v.rarity DESC,v.name_source,v.level DESC LIMIT ?""",(weapon_type,pattern,pattern,limit)).fetchall()
            else:
                rows=db.execute("""SELECT id,ja,en,rarity,slots,class_code,job,sex FROM equipment WHERE kind=? AND (ja LIKE ? ESCAPE '\\' OR en LIKE ? ESCAPE '\\' OR id=?) ORDER BY rarity DESC,ja LIMIT ?""",(kind,pattern,pattern,q,limit)).fetchall()
            return [dict(r) for r in rows]

    # Paginated catalog for the browser; retain the legacy /api/items contract.
    @app.get('/api/catalog')
    def paged_catalog(kind:str,q:str='',weapon_type:str='MS',page:int=Query(1,ge=1,le=100000),page_size:int=Query(30,ge=1,le=100),rank:str='',job:str='',sex:str='',hide_unavailable:bool=True,hide_paid:bool=False,hide_festival:bool=False,sort:str='rarity',lang:str='ja',level_mode:str='max'):
        from catalog import catalog,RANKS
        if (kind not in KINDS|{'weapon'} or weapon_type not in WEAPON_TYPES or len(q)>100 or rank not in RANKS|{''} or job not in ('','剣士','ガンナー') or sex not in ('','男','女') or sort not in ('rarity','name','defense','attack') or lang not in ('ja','en') or level_mode not in ('first','max')):
            raise HTTPException(400,'invalid catalog query')
        with closing(connect(db_path)) as db:
            return catalog(db,kind=kind,q=q,weapon_type=weapon_type,page=page,page_size=page_size,rank=rank,job=job,sex=sex,hide_unavailable=hide_unavailable,hide_paid=hide_paid,hide_festival=hide_festival,sort=sort,lang=lang,level_mode=level_mode)

    @app.get('/api/levels')
    def levels(id:str):
        with closing(connect(db_path)) as db:
            return [dict(r) for r in db.execute('SELECT level,slots,defense FROM levels WHERE equipment_id=? AND slots IS NOT NULL ORDER BY CAST(substr(level,2) AS INTEGER)',(id,))]

    @app.get('/api/classes')
    def classes():
        with closing(connect(db_path)) as db:
            return [r[0] for r in db.execute('SELECT DISTINCT class_code FROM equipment WHERE class_code IS NOT NULL ORDER BY class_code')]

    @app.get('/api/material-source')
    def material_source(name: str = Query(..., min_length=1, max_length=200)):
        from master_data import material_lookup
        with closing(connect(db_path)) as db:
            return material_lookup(db,db_path.parent,name)

    @app.post('/api/material-plan')
    def material_plan(build:dict):
        from materials import Planner
        try:
            with closing(connect(db_path)) as db:
                return Planner(db,db_path.parent).plan(build)
        except (ValueError,KeyError,TypeError,sqlite3.Error,OSError) as e:
            raise HTTPException(400,str(e)) from e

    @app.post('/api/evaluate')
    def evaluate(build:dict):
        from skill_engine import Engine
        try:
            with closing(connect(db_path)) as db:
                return {'build':build,'evaluation':candidates.evaluate(build),'display':enrich(db,build)}
        except (ValueError,KeyError,TypeError,sqlite3.Error) as e:
            raise HTTPException(400,str(e)) from e

    # Shared builds are canonicalized and recalculated locally; never trust cached points.
    @app.post('/api/share/import')
    def share_import(payload:dict):
        from sharing import import_build
        try:
            with closing(connect(db_path)) as db:
                b,r,w=import_build(db,payload.get('text'),payload.get('format'),payload.get('context'))
                return {'build':b,'evaluation':r,'display':enrich(db,b),'import_warnings':w}
        except (ValueError,KeyError,TypeError,sqlite3.Error) as e:
            raise HTTPException(400,str(e)) from e

    @app.post('/api/share/export')
    def share_export(payload:dict):
        from skill_engine import Engine
        from sharing import canonical_build, envelope, encode_clip
        try:
            if len(json.dumps(payload))>100000: raise ValueError('request too large')
            with closing(connect(db_path)) as db:
                b=canonical_build(db,payload.get('build')); r=Engine(db).evaluate(b)
                if not r['valid']: raise ValueError('; '.join(r['errors']))
                fmt=payload.get('format')
                if fmt=='json': text=json.dumps(envelope(b),ensure_ascii=False,indent=2)
                elif fmt=='clip': text=encode_clip(db,b,r)
                else: raise ValueError('unsupported export format')
                return {'text':text}
        except (ValueError,KeyError,TypeError,sqlite3.Error) as e:
            raise HTTPException(400,str(e)) from e

    @app.post('/api/candidates/query')
    def query_candidates(payload:dict):
        if len(json.dumps(payload))>150000:raise HTTPException(400,'candidate query too large')
        req=payload.get('request',payload)
        try:
            response=candidates.query(req,payload.get('targets',[]),limit=min(64,max(1,int(payload.get('display_limit',30)))))
            with closing(connect(db_path)) as db:
                for h in response['results']:
                    if 'display' not in h:h['display']=enrich(db,h['build'])
            return response
        except (OSError,sqlite3.Error) as exc:raise HTTPException(503,'candidate database unavailable') from exc
        except (ValueError,TypeError,KeyError) as exc:raise HTTPException(400,str(exc)) from exc

    @app.post('/api/candidates/variants')
    def candidate_variants(payload:dict):
        if len(json.dumps(payload))>150000:raise HTTPException(400,'variant query too large')
        try:
            response=candidates.variants(payload['request'],payload['armor'],payload.get('exclude'))
            with closing(connect(db_path)) as db:
                for h in response['results']:h['display']=enrich(db,h['build'])
            return response
        except (ValueError,TypeError,KeyError) as exc:raise HTTPException(400,str(exc)) from exc

    # At most one active job; retain a bounded number of finished jobs in temporary files.
    @app.post('/api/search')
    def search(payload:dict):
        return start_search(payload)

    def start_search(payload,internal=False):
        if len(json.dumps(payload))>100000:
            raise HTTPException(400,'request too large')
        # A client-provided identifier makes retries safe if the POST response is lost.
        payload=dict(payload)
        if not internal:
            payload.pop('_index_job',None);payload.pop('_precompute_task',None)
        requested=payload.pop('_job_id',None)
        if requested is not None and (not isinstance(requested,str) or not re.fullmatch(r'[a-f0-9]{32}',requested)):
            raise HTTPException(400,'invalid search job ID')
        with lock:
            if requested in jobs:
                existing=jobs[requested]
                if existing.get('client_request',json.loads(existing['request'].read_text(encoding='utf-8')))!=payload:
                    raise HTTPException(409,'search job ID already used for different conditions')
                return {'id':requested,'status':'running'}
            if not internal:
                for j in jobs.values():
                    if j.get('index_job') and j['process'].poll() is None:
                        stop_worker(j,graceful=True);j['cancelled']=True
            if any(j['process'].poll() is None and not j.get('cancelled') for j in jobs.values()):
                raise HTTPException(409,'another search is running')
            # Reap completed jobs and their Windows job handles even if no client polled them.
            for j in jobs.values():
                if j['process'].poll() is not None:
                    release_job(j)
            for key in list(jobs)[:-7]:
                j=jobs.pop(key)
                for p in (j['request'],j['output'],j['error'],j['output'].with_suffix('.progress'),j['output'].with_suffix('.progress.tmp')): p.unlink(missing_ok=True)
            key=requested or uuid.uuid4().hex
            base=Path(temp.name)/key
            req=base.with_suffix('.json'); out=base.with_suffix('.out'); err=base.with_suffix('.err')
            client_request=dict(payload)
            try:
                if payload.get('_pool_discovery'):
                    coverage=candidates.coverage_targets(payload,int(payload.get('_coverage_pass',1)))
                    if coverage:payload['optional']=coverage
                seeds,exclusions=candidates.seed(payload,explore=bool(payload.get('_pool_discovery')))
                if seeds:payload['_seed_builds']=seeds
                if exclusions:payload['_excluded_armor_sets']=exclusions
            except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
                # Preserve the worker's existing detailed input-error behavior.
                pass
            req.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
            vector_env=candidates.archive.worker_environment() if candidates.archive else {}
            proof_key=os.urandom(32)
            low_priority = bool(internal or payload.get('live_preview') or (game_priority and game_priority()))
            with (open(os.devnull, 'wb') if getattr(sys, 'frozen', False) else err.open('wb')) as log:
                proc=subprocess.Popen(search_command(ROOT, db_path, req, out, err),cwd=ROOT,stdout=log,stderr=log,creationflags=creation_flags(low_priority),env={**os.environ,**vector_env,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','MHF_PROOF_CHANNEL_KEY':proof_key.hex()})
            jobs[key]={'proof_key':proof_key,'index_job':bool(internal),'process':proc,'client_request':client_request,'db_identity':candidates.identity,'request':req,'output':out,'error':err,'started':time.monotonic(),'guard':attach_worker(proc)}
        return {'id':key,'status':'running'}

    @app.get('/api/search/{key}')
    def status(key:str):
        with lock:
            j=jobs.get(key)
            if not j: raise HTTPException(404,'job not found')
            elapsed=round(time.monotonic()-j['started'],2)
            if j.get('db_identity'):
                try:changed=candidates.fingerprint()!=j['db_identity']
                except OSError:changed=True
                if changed:
                    stop_worker(j,graceful=True)
                    return {'status':'error','detail':'Database changed during search; retry with the current database'}
            if j.get('cancelled'): return {'status':'cancelled','elapsed_seconds':elapsed}
            code=j['process'].poll()
            if code is None:
                path = j['output'].with_suffix('.progress')
                reply = {'status':'running','elapsed_seconds':elapsed}
                try:
                    # Cache hydration for unchanged snapshots, to avoid repeated DB queries.
                    stamp = path.stat().st_mtime_ns
                    if stamp != j.get('progress_stamp'):
                        partial = json.loads(path.read_text(encoding='utf-8'))
                        with closing(connect(db_path)) as db:
                            for h in partial.get('results',[]):
                                h['display'] = enrich(db,h['build'])
                        j['progress_stamp'] = stamp
                        try:candidates.ingest(j.get('client_request',{}),partial,persist=False)
                        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):pass
                        j['progress_result'] = partial
                    reply['partial'] = j['progress_result']
                    reply['revision'] = stamp
                except (OSError, ValueError, KeyError):
                    pass
                return reply
            release_job(j)
            if code!=0 or not j['output'].exists():
                return {'status':'error','detail':j['error'].read_text(encoding='utf-8',errors='replace')[-2000:] if j['error'].exists() else f'Worker exited with code {code}'}
            result=json.loads(j['output'].read_text(encoding='utf-8'))
        with closing(connect(db_path)) as db:
            for h in result.get('results',[]):
                item=h.get('witness',h)
                if 'build' in item: item['display']=enrich(db,item['build'])
        if result.get('certificate'):
            cert=result['certificate'];signature=hmac.new(j['proof_key'],json.dumps(cert,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
            trusted=hmac.compare_digest(signature,result.get('proof_auth','')) and candidates.archive and cert.get('calculation')==candidates.archive.calculation and cert.get('source')==j.get('db_identity')
            if trusted:
                cert=candidates.accept_proof(j.get('client_request',{}),cert);result['certificate']=cert
                if not cert.get('coverage_complete'):result['status']='data_incomplete'
            else:result['status']='unknown';result.pop('certificate',None)
            result.pop('proof_auth',None)
        if not j.get('ingested'):
            try:candidates.ingest(j.get('client_request',{}),result);j['ingested']=True
            except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):pass
        return {'status':'done','result':result}

    @app.delete('/api/search/{key}')
    def cancel(key:str):
        with lock:
            j=jobs.get(key)
            if not j: raise HTTPException(404,'job not found')
            if j['process'].poll() is None:
                stop_worker(j, graceful=True)
                j['cancelled']=True
            else:
                release_job(j)
            return {'status':'cancelled' if j.get('cancelled') else 'done'}

    @app.post('/api/precompute/prepare')
    def prepare_precomputed():
        try:return candidates.prepare_index()
        except (OSError,ValueError,sqlite3.Error):raise HTTPException(503,'calculation index unavailable')

    @app.get('/api/precompute/status')
    def precompute_status():
        try:return {**candidates.index_status(),'idle_phase':idle.phase}
        except (OSError,ValueError,sqlite3.Error):raise HTTPException(503,'calculation index unavailable')

    @app.post('/api/precompute/activity')
    def precompute_activity(payload:dict):
        if len(json.dumps(payload))>150000:raise HTTPException(400,'context too large')
        try:
            request=payload['request'];targets=payload.get('targets',[])[:1000]
            candidates._ready().prepare_request(request)
            return idle.activity(request,targets,payload.get('idle_seconds',0),payload.get('enabled',True))
        except (ValueError,KeyError,TypeError):raise HTTPException(400,'invalid calculation context')

    @app.get('/api/precompute/data/catalog')
    def data_catalog():
        try:return distribution.check()
        except (OSError,ValueError,KeyError,TypeError) as exc:raise HTTPException(400,str(exc)) from exc

    @app.post('/api/precompute/data/download')
    def data_download(payload:dict):
        try:return distribution.start(payload['weapon_type'])
        except (ValueError,KeyError) as exc:raise HTTPException(400,str(exc)) from exc

    @app.get('/api/precompute/data/download/{key}')
    def data_download_status(key:str):
        try:return distribution.status(key)
        except KeyError:raise HTTPException(404,'data job not found')

    from precompute_distribution import DataDistribution
    distribution=DataDistribution(candidates,(ROOT/'VERSION').read_text(encoding='utf-8-sig').strip(),ROOT)
    from precompute_idle import IdlePrecomputer
    idle=IdlePrecomputer(candidates,lambda request:start_search(request,True),status,cancel)
    app.state.idle_precompute=idle
    return app

if __name__=='__main__':
    import uvicorn
    parser=argparse.ArgumentParser();parser.add_argument('--db',type=Path,required=True);parser.add_argument('--port',type=int,default=8765)
    args=parser.parse_args()
    if not args.db.is_file(): parser.error('database not found; import data first')
    uvicorn.run(create_app(args.db),host='127.0.0.1',port=args.port)
