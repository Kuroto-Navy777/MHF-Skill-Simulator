"""Bounded integer search, followed by the independent Phase 3 evaluator."""
import argparse
import copy
import json
import math
import heapq
import sqlite3
import time
import warnings
import sys
from collections import Counter, defaultdict, OrderedDict
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, vstack
from skill_engine import Engine, PARTS, WEAPON_SECRET
from search_contract import SearchContract
from search_data import snapshot as data_snapshot, indices as data_indices, ArmorStats
from ferias_import import validate_slots
from inventory import restrict_inventory
from armor_levels import endpoint
from defense import STATS, ELEMENTS, OBJECTIVES, armor_values, constraints, skill_modifier, satisfies
from external import normalize, upper_bonus, road_cost
from bounty import rules, item_allowed, weapon_allowed, banned_skill, public_rules


class Model:
    def __init__(self):
        self.cost, self.ub, self.rows, self.lo, self.hi = [], [], [], [], []
        self._matrix = None

    # All variables are bounded integers; decision bits also support exact no-good cuts.
    def var(self, upper=1, cost=0):
        i = len(self.cost)
        self.cost.append(cost)
        self.ub.append(upper)
        return i

    def add(self, coefficients, low=-np.inf, high=np.inf):
        self.rows.append({i: v for i, v in coefficients.items() if v})
        self.lo.append(low)
        self.hi.append(high)

    # Reuse the sparse matrix to validate all constraint rows without a Python loop.
    def feasible(self, x):
        if self._matrix is None or self._matrix.shape != (len(self.rows), len(self.cost)):
            return False
        if not np.all(np.isfinite(x)) or np.any(x<0) or np.any(x>np.asarray(self.ub)):
            return False
        sums=self._matrix @ x
        return bool(np.all(sums>=np.asarray(self.lo)-1e-5) and np.all(sums<=np.asarray(self.hi)+1e-5))

    def solve(self, seconds):
        # Preserve the base matrix between successive solves; append only newly added cuts.
        # A new variable invalidates the cached width and triggers a complete rebuild.
        if self._matrix is not None and self._matrix.shape[1] == len(self.cost):
            start=self._matrix.shape[0]
        else:
            start=0; self._matrix=None
        if self._matrix is None or start<len(self.rows):
            rr, cc, vv = [], [], []
            for i, row in enumerate(self.rows[start:]):
                for j, v in row.items():
                    rr.append(i); cc.append(j); vv.append(v)
            tail=coo_matrix((vv,(rr,cc)),shape=(len(self.rows)-start,len(self.cost))).tocsc()
            self._matrix=tail if self._matrix is None else vstack([self._matrix,tail],format='csc')
        matrix=self._matrix
        # HiGHS explicitly bounds native solver concurrency; background jobs also
        # run below normal Windows priority. Keep unrelated warnings visible.
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message=r"Unrecognized options detected: .*threads.*",category=RuntimeWarning)
            return milp(np.zeros(len(self.cost)) if getattr(self,'feasibility_first',False) else np.array(self.cost, dtype=float), integrality=np.ones(len(self.cost)),
                        bounds=Bounds(np.zeros(len(self.cost)), np.array(self.ub)),
                        constraints=LinearConstraint(matrix, self.lo, self.hi),
                        options={'time_limit': max(.05, seconds),'threads':1})


def plus(dest, src, factor=1):
    for k, v in src.items():
        dest[k] += factor*v


class DecisionBounds:
    """Safe integer bounds for skill rows, respecting mutually exclusive armor and budgets."""
    def __init__(self, armor_vars, jewel_vars, cuff_vars, items, maxslots):
        self.armor_vars=armor_vars
        self.armor_group={i:p for p,choices in armor_vars.items() for i in choices}
        self.maxslots=maxslots
        self.jewels={i:items[eid]['slots']*v for eid,bits in jewel_vars.items() for i,v in bits.items()}
        self.cuffs={i:v for bits in cuff_vars.values() for i,v in bits.items()}

    def interval(self, row, constant=0):
        lo=hi=constant
        # Scan only nonzero coefficients. An unmentioned armor variable has coefficient zero.
        seen=Counter(); lows={}; highs={}; jlo=jhi=clo=chi=0
        for i,v in row.items():
            part=self.armor_group.get(i)
            if part is not None:
                seen[part]+=1; lows[part]=min(lows.get(part,v),v); highs[part]=max(highs.get(part,v),v)
            elif i in self.jewels:
                w=self.jewels[i]; jlo=min(jlo,v//w); jhi=max(jhi,-(-v//w))
            elif i in self.cuffs:
                w=self.cuffs[i]; clo=min(clo,v//w); chi=max(chi,-(-v//w))
        for part,choices in self.armor_vars.items():
            a=lows.get(part,0); b=highs.get(part,0)
            if seen[part]<len(choices): a=min(a,0); b=max(b,0)
            lo+=a; hi+=b
        # Fractional knapsack relaxation, with outward-rounded integer ratios.
        lo+=jlo*self.maxslots+clo*2; hi+=jhi*self.maxslots+chi*2
        return lo,hi


class Searcher(SearchContract):
    def __init__(self, db):
        self.db = db
        self.progress = None
        self.witnesses=OrderedDict()
        self.e = Engine(db)
        data, self.data_cache_hit, self.data_load_seconds = data_snapshot(db,self._load_data)
        for name,value in data.items(): setattr(self,name,value)
        self.e._indexed_items=self.items; self.e._indexed_lookup=self.item_lookup
        self.e._indexed_points=self.points; self.e._indexed_abilities=self.abilities
        self.e._armor_levels_cache=self.levels

    def _load_data(self):
        db=self.db
        self.items = {r['id']: dict(r) for r in db.execute('SELECT * FROM equipment')}
        self.by_kind=defaultdict(dict)
        for eid,row in self.items.items(): self.by_kind[row['kind']][eid]=row
        self.points, self.abilities, self.levels = defaultdict(dict), defaultdict(list), defaultdict(list)
        from search_precompute import load_solver_vectors
        compiled=load_solver_vectors(db,self.items,self.e.skills);self.compiled_vectors_used=compiled is not None
        if compiled:self.points=compiled[0]
        else:
            for eid,sid,pt in db.execute('SELECT equipment_id,skill_id,points FROM equipment_skills'):
                self.points[self.items[eid]['id']][self.e.skills[sid]['id']]=pt
        for eid, typ, val in db.execute('SELECT equipment_id,type_ja,value_ja FROM abilities'):
            self.abilities[self.items[eid]['id']].append((sys.intern(typ),sys.intern(val) if isinstance(val,str) else val))
        for eid, lv, slots, defense in db.execute('SELECT equipment_id,level,slots,defense FROM levels'):
            if slots is not None:
                self.levels[self.items[eid]['id']].append((sys.intern(lv), slots, defense))
        self.armor_stats = ArmorStats(self.items)
        self.zen = defaultdict(dict)
        self.auto = defaultdict(dict)
        if compiled:self.zen,self.auto=compiled[1],compiled[2]
        else:
            for eid, abilities in self.abilities.items():
                for typ,val in abilities:
                    if typ=='スキル発動':
                        matches=self.e.level_names[('normal',val)]
                        if len(matches)==1:
                            x=matches[0]; sid=x['skill_id']
                            self.auto[eid][sid]=max(self.auto[eid].get(sid,0),x['points'])
                    if typ in ('スキル強化','スキル枠拡張'):
                        matches = self.e.level_names[('zenith',val)]
                        if len(matches)==1:
                            x=matches[0]; self.zen[eid][x['skill_id']]=self.zen[eid].get(x['skill_id'],0)+x['points']
        self.providers,self.item_lookup=data_indices(self.items,self.points,self.zen,self.auto)
        return {name:getattr(self,name) for name in ['items', 'by_kind', 'points', 'abilities', 'levels', 'armor_stats', 'zen', 'auto', 'providers', 'item_lookup','compiled_vectors_used']}

    # Include ordinary prerequisites and composite providers in the focused pool.
    def dependency_targets(self, targets):
        expanded=set(targets)
        for sid in targets:
            if not sid.startswith('zenith:'):
                continue
            name=json.loads(self.e.skills[sid]['metadata'])['ja'].get('Target')
            base=self.e.names.get(('normal',name))
            if not base:
                continue
            expanded.add(base)
            for provider, tiers in self.e.levels.items():
                if not provider.startswith('normal:'):
                    continue
                for tier in tiers:
                    for group in json.loads(tier['rules_json'])['ja']['children']:
                        if group['tag']!='ContainedSkills':
                            continue
                        for ch in group['children']:
                            matches=self.e.level_names[('normal',ch['attributes'].get('Name'))]
                            if len(matches)==1 and matches[0]['skill_id']==base:
                                expanded.add(provider)
        return expanded













    def feasibility(self,req):
        start=time.monotonic();prepared=self.prepare_request(req)
        for key in ('_seed_builds','_initial_hits','_excluded_armor_sets','_fast_armor_cap'):prepared.pop(key,None)
        prepared.update(limit=1,objective='minimal_jewels',optional=[],full_jewel_pool=True,search_strategy='full',diverse_armor=False,_feasibility_only=True)
        if prepared.get('auto_weapon'):prepared['integrated_weapon']=True
        budget=float(prepared.get('seconds',15));prepared['seconds']=budget
        first=None
        if budget>=.25:
            fast={**prepared,'full_jewel_pool':False,'_fast_armor_cap':240,'seconds':min(1.5,budget*.4)}
            first=self.search_fixed(fast)
            if first['results']:
                first.update(status='confirmed',feasibility_only=True,elapsed_seconds=round(time.monotonic()-start,3));return first
        prepared['seconds']=max(.05,budget-(time.monotonic()-start))
        result=self.search_fixed(prepared)
        if first:
            for key in ('attempts','rejected'):result[key]+=first[key]
        certificate=None
        if not result['results'] and result['status']=='model_exhausted' and result.get('pool_mode')=='full':
            from calculation_identity import calculation_identity,source_identity
            name=self.db.execute('PRAGMA database_list').fetchone()[2]
            certificate={'kind':'full_model_infeasible','scope':'supported_search_model','calculation':calculation_identity(),
                'source':source_identity(name) if name else 'in-memory','variables':result['model_variables'],
                'constraints':result['model_constraints'],'pool_counts':result['pool_counts'],'rejected':result['rejected']}
            result['status']='proven_infeasible';result['certificate']=certificate
        elif result['results']:result['status']='confirmed'
        else:result['status']='unknown'
        result['feasibility_only']=True;result['elapsed_seconds']=round(time.monotonic()-start,3)
        return result

    def search(self, req):
        try:return self._search(req)
        except (ValueError,KeyError,TypeError) as exc:
            if not req.get('structured_outcomes'):raise
            return {'status':'input_conflict','reason':str(exc),'results':[],
                    'confirmed_builds':0,'distinct_armor':0,'decoration_variants':0,
                    'attempts':0,'rejected':0,'elapsed_seconds':0,'complete_game_search':False}

    def _search(self, req):
        req=self.prepare_request(req)
        from candidate_pool import condition_key
        from candidate_validation import validate
        scope=condition_key(req)
        seeds=list(req.pop('_seed_builds',[]))[:32]+list(self.witnesses.get(scope,[]))
        valid=[]; seen=set()
        for build in seeds:
            report,reasons=validate(self,req,build)
            if report is None: continue
            key=self.build_key(build)
            if key in seen: continue
            seen.add(key)
            total=sum(len(a.get('jewels',[])) for a in list(build['armor'].values())+[build.get('weapon',{})])
            fixed=sum(len(a.get('jewels',[])) for a in list(req.get('armor',{}).values())+[req.get('weapon',{})])
            valid.append({'build':copy.deepcopy(build),'evaluation':report,'new_jewels':total-fixed,'reused_witness':True})
        if req.get('diverse_armor') and not (req.get('collect_variants') and all(req.get('armor',{}).get(p) for p in PARTS)):
            from candidate_groups import armor_key
            by_armor={}
            for h in self.rank(valid,req):by_armor.setdefault(armor_key(h['build']),h)
            valid=list(by_armor.values())
        req={**req,'_initial_hits':self.rank(valid,req)[:int(req.get('limit',3))]}
        result=self.search_weapons(req) if req.get('auto_weapon') and not req.get('integrated_weapon') else self.search_with_strategy(req)
        from candidate_groups import group_hits,counts
        result['armor_groups']=group_hits(result['results']);result.update(counts(result['results']))
        result['reused_witnesses']=len(valid)
        result['retained_witnesses']=sum(h.get('reused_witness',False) for h in result['results'])
        result['compiled_vectors_used']=self.compiled_vectors_used;result['data_cache_hit']=self.data_cache_hit;result['data_load_seconds']=round(self.data_load_seconds,6)
        existing=list(self.witnesses.pop(scope,[]))
        unique={self.build_key(b):b for b in existing+[h['build'] for h in result['results']]}
        self.witnesses[scope]=list(unique.values())[-128:]
        while len(self.witnesses)>4:self.witnesses.popitem(last=False)
        return result

    def search_with_strategy(self, req):
        # Keep legacy callers compatible. Adaptive mode retries the full pool if the focused search is incomplete.
        mode=req.get('search_strategy','full' if req.get('full_jewel_pool') else 'focused')
        if mode not in ('focused','adaptive','full'): raise ValueError('invalid search strategy')
        if mode!='adaptive' or req.get('full_jewel_pool') or req.get('objective')=='max_skills':
            return self.search_fixed({**req,'full_jewel_pool':mode=='full' or bool(req.get('full_jewel_pool'))})
        start=time.monotonic(); budget=float(req.get('seconds',15)); limit=int(req.get('limit',3))
        if not math.isfinite(budget) or not 0<budget<=300: raise ValueError('invalid time budget')
        first=self.search_fixed({**req,'seconds':budget*.35,'full_jewel_pool':False,'_fast_armor_cap':240})
        first['search_strategy']='adaptive'; first['search_passes']=[{'pool':'prioritized','status':first['status'],'count':len(first['results'])}]
        left=budget-(time.monotonic()-start)
        if len(first['results'])>=limit or left<=.05:
            return first
        # Once a legal incumbent exists, diversify by reoptimizing two free
        # parts jointly with every weapon group, jewels and cuffs. Fixing the
        # other parts breaks armor symmetry without changing user constraints.
        # A full model remains available if these neighborhoods do not suffice.
        if req.get('integrated_weapon') and req.get('auto_weapon') and first['results']:
            free=[p for p in PARTS if not req.get('armor',{}).get(p)]
            pairs=[free[i:i+2] for i in range(0,len(free)-1,2)]
            if len(free)>2:pairs.append([free[0],free[-1]])
            for pair in pairs:
                left=budget-(time.monotonic()-start)
                if len(first['results'])>=limit or left<=.1:break
                anchor=first['results'][0]['build']
                locked=copy.deepcopy(req.get('armor',{}))
                for part in free:
                    if part not in pair:
                        a=anchor['armor'][part];locked[part]={'item':a['item'],'level':a['level'],'jewels':[]}
                sub={**req,'armor':locked,'seconds':left/max(1,len(pairs)),
                     'full_jewel_pool':False,'_fast_armor_cap':240}
                refined=self.search_fixed(sub,initial_hits=first['results'])
                refined['search_strategy']='adaptive'
                refined['search_passes']=first['search_passes']+[{'pool':'neighborhood','status':refined['status'],'count':len(refined['results']),'free_parts':pair}]
                for k in ('attempts','rejected','duplicates'):refined[k]=refined.get(k,0)+first.get(k,0)
                refined['rejection_reasons']=dict(Counter(first.get('rejection_reasons',{}))+Counter(refined.get('rejection_reasons',{})))
                refined['rejection_samples']=(first.get('rejection_samples',[])+refined.get('rejection_samples',[]))[:20]
                refined['rejection_log']=first.get('rejection_log',[])+refined.get('rejection_log',[])
                first=refined
            left=budget-(time.monotonic()-start)
            if len(first['results'])>=limit or left<=.05:
                first['elapsed_seconds']=round(time.monotonic()-start,3);return first
        full=self.search_fixed({**req,'seconds':left,'full_jewel_pool':True,'_fast_armor_cap':0}, initial_hits=first['results'])
        full['search_strategy']='adaptive'; full['search_passes']=first['search_passes']+[{'pool':'full','status':full['status'],'count':len(full['results'])}]
        for k in ('attempts','rejected','duplicates'):
            full[k]=full.get(k,0)+first.get(k,0)
        full['rejection_reasons']=dict(Counter(first.get('rejection_reasons',{}))+Counter(full.get('rejection_reasons',{})))
        full['rejection_samples']=(first.get('rejection_samples',[])+full.get('rejection_samples',[]))[:20]
        full['rejection_log']=[{'pass':'prioritized',**entry} for entry in first.get('rejection_log',[])]+[{'pass':'full',**entry} for entry in full.get('rejection_log',[])]
        full['elapsed_seconds']=round(time.monotonic()-start,3)
        return full

    # Report only independently evaluated candidates; never claim exhaustive counts.
    def emit_progress(self, hits, req, start):
        if self.progress is not None and not req.get('_live_group'):
            ranked = self.rank(list(hits), req)[:int(req.get('limit', 3))]
            self.progress({'status': 'live_partial', 'results': ranked,
                           'elapsed_seconds': round(time.monotonic()-start, 3),
                           'complete_game_search': False})

    def search_fixed(self, req, initial_hits=()):
        start=time.monotonic()
        initial_hits=initial_hits or req.get('_initial_hits',())
        level_mode=req.get('armor_level_mode','max')
        if level_mode not in ('first','max'): raise ValueError('invalid armor level mode')
        seconds=float(req.get('seconds',15)); limit=int(req.get('limit',3))
        if not math.isfinite(seconds) or not 0<seconds<=300 or not 1<=limit<=30: raise ValueError('seconds 0..300, limit 1..30')
        wt=req['weapon_type']; job='ガンナー' if wt in ('HBG','LBG','Bow') else '剣士'
        joint=bool(req.get('auto_weapon') and req.get('integrated_weapon'))
        base={k:copy.deepcopy(req[k]) for k in ('weapon_type','sex','g_poogie','premium_poogie_clothes','weapon','cuffs','external') if k in req}
        if joint:base.pop('weapon',None)
        base['job']=job; base.setdefault('sex','男')
        if wt not in WEAPON_SECRET: raise ValueError('unknown weapon type')
        wanted=self.requirements(req['required'])
        optional=self.optional_requirements(req)
        forbidden=self.conflicts(req)
        objective=req.get('objective','minimal_jewels')
        targets=self.dependency_targets(set(wanted)|{sid for sid,pt in optional})
        targets.add(self.e.names[('zenith','スキル枠拡張')])
        br=rules(req['bounty']) if req.get('bounty') else None
        limits,stat_mode=constraints(req)
        ext=normalize(req.get('external'))
        if road_cost(ext)>130: raise ValueError('Road cost exceeds ZZ maximum 130')
        if any(ext['sigil'].values()) and not (joint and req.get('sigil_mode')=='auto') and req.get('weapon',{}).get('sigils',0)<1: raise ValueError('Sigil bonuses require reserved weapon slots')
        if br and any(ext['road'].values()) and not (req['bounty']['group']=='Free' and req['bounty']['number']==24 or req['bounty']['group']=='Event' and req['bounty']['number'] in (20,21)): raise ValueError('Road effects require a Road bounty or normal search')
        stat_targets=set(limits) | ({'defense'} if objective=='defense' else set(ELEMENTS) if objective=='resistance' else set())
        if not wanted and not stat_targets and req.get('live_preview') is not True: raise ValueError('required must not be empty')
        # Include known flat modifiers provided by composite tiers as well as direct skills.
        def tier_stats(tier):
            delta=Counter(skill_modifier(tier['ja']))
            for x in self.e.contained_levels(tier):
                for k,v in skill_modifier(x['ja']).items(): delta[k]=max(delta.get(k,0),v)
            return delta
        if stat_targets and stat_mode in ('adjusted','external'):
            targets.update(sid for sid,levels in self.e.levels.items() if any(set(tier_stats(x)) & stat_targets for x in levels))
        stat_rows=defaultdict(Counter)
        excluded=set(req.get('exclude',[])); classes=set(req.get('exclude_classes',[]))
        fixed=req.get('armor',{}); allow=req.get('armor_candidates',{}); jallow=req.get('jewel_candidates'); callow=req.get('cuff_candidates')
        if (set(fixed)|set(allow))-set(PARTS): raise ValueError('unknown armor part')
        def ids(keys,kind): return {self.e.equipment(k,kind)['id'] for k in keys}
        def permitted(r):
            return item_allowed(r,br) and not excluded.intersection((r['id'],r['ja'],r['en'])) and r['class_code'] not in classes and r['class_code'] not in ('(未)','(不)') and r['job'] in (None,'共',job) and r['sex'] in (None,'共',base['sex'])
        def relevant(eid):
            return (any(self.points[eid].get(sid,0)>0 or self.zen[eid].get(sid,0)>0 for sid in targets)
                    or (self.e.names.get(("normal","喝")) in targets and self.points[eid].get(self.e.names.get(("normal","喝")),0)<0)
                    or any(self.points[eid].get(sid,0)*(1 if pt>0 else -1)<0 for sid,pt in forbidden.items())
                    or bool(set(self.auto[eid]) & targets))
        def supported(eid):
            return all(t in ('Ｇ級効果','スキル強化','スキル枠拡張','スキル枠消費なし','スキル発動') for t,v in self.abilities[eid])
        def jewel_ok(eid):
            r=self.items[eid]
            return permitted(r) and r['group_name']!='SP' and r['slots'] in (1,2,3) and supported(eid)
        fast_mode=bool(req.get('_fast_armor_cap'))
        direction={sid:(1 if pt>0 else -1)/abs(pt) for sid,pt in wanted.items()}
        weights=defaultdict(float,{sid:v*8 for sid,v in direction.items()})
        for (sid,pt),weight in optional.items(): weights[sid]+=(1 if pt>0 else -1)*weight/abs(pt)
        for sid in sorted(targets-set(wanted)):
            if sid not in weights: weights[sid]=.04
        for sid,pt in forbidden.items(): weights[sid]-=(1 if pt>0 else -1)*.08
        ext_id=self.e.names[('zenith','スキル枠拡張')]
        weights[ext_id]+=.45
        def contribution(eid,sid,pt):
            v=self.points[eid].get(sid,0)+self.zen[eid].get(sid,0)
            if pt>0: v=max(v,self.auto[eid].get(sid,0))
            return v*(1 if pt>0 else -1)
        def item_score(eid):
            return (sum((min(v,abs(wanted[sid])) if sid in wanted and wanted[sid]>0 and v>0 else v)*weights.get(sid,0) for sid,v in self.points[eid].items())
                    +sum(v*weights.get(sid,0) for sid,v in self.zen[eid].items())
                    +sum(v*max(0,weights.get(sid,0)) for sid,v in self.auto[eid].items()))
        def shortlist(rows,cap,score):
            # Retain top overall and a small slice for every required family, including negative thresholds.
            # This is only the fast pass; full search restores every eligible item.
            chosen={a[0]:a for a in heapq.nlargest(cap,rows,key=score)}
            for sid,pt in sorted(set(wanted.items())|set(optional)):
                for a in heapq.nlargest(12,rows,key=lambda a:contribution(a[0],sid,pt)):
                    if contribution(a[0],sid,pt)>0: chosen[a[0]]=a
            return list(chosen.values())
        baseline_input=copy.deepcopy(base)
        if joint:baseline_input['weapon']={'virtual':True,'slots':3,'slot_mode':'shared','sigils':(1 if any(ext['sigil'].values()) else 0) if req.get('sigil_mode')=='auto' else req.get('weapon',{}).get('sigils',0),'jewels':req.get('weapon',{}).get('jewels',[])}
        baseline=self.e.evaluate(baseline_input)
        if base.get('weapon') and 'page' in base['weapon']:
            weapon=base['weapon']; row=self.db.execute('SELECT v.*,w.name_ja FROM ferias_variants v JOIN ferias_weapons w USING(weapon_type,upstream_id) WHERE v.weapon_type=? AND v.page=? AND v.anchor=?',(wt,weapon['page'],weapon['anchor'])).fetchone()
            if not self.weapon_permitted(row,req): raise ValueError('fixed physical weapon excluded')
        if 'template' in base.get('weapon',{}):
            if not permitted(self.items[self.e.equipment(base['weapon']['template'],'weapon_template')['id']]):
                raise ValueError('fixed weapon template excluded')
        if not baseline['valid']: raise ValueError(f"invalid fixed weapon/cuffs: {baseline['errors']}")
        for key,kind in [(k,'jewel') for k in base.get('weapon',{}).get('jewels',[])]+[(k,'cuff') for k in base.get('cuffs',[])]:
            if not permitted(self.items[self.e.equipment(key,kind)['id']]): raise ValueError('fixed equipment excluded')
        constant=Counter({s['id']:s['points'] for s in baseline['skills']})
        plus(constant,{s['id']:s['raw_points'] for s in baseline['zenith']})
        model=Model(); decisions=[]; armor_vars={}; item_vars=defaultdict(dict); capacities={}; fixed_jewels={}; pool_counts={}; eligible_armor={}
        # Preserve explicit imported levels; otherwise use the chosen source endpoint.
        for part in PARTS:
            cfg=fixed.get(part); a_ids=ids(allow[part],part) if part in allow else None
            if cfg:
                only=self.e.equipment(cfg['item'],part)['id']
                if a_ids is not None and only not in a_ids: raise ValueError('fixed armor outside allowlist')
                a_ids={only}
            js=[self.e.equipment(k,'jewel')['id'] for k in (cfg or {}).get('jewels',[])]
            if any(not jewel_ok(k) for k in js): raise ValueError('unsupported/excluded fixed jewel')
            fixed_jewels[part]=js; used=sum(self.items[k]['slots'] for k in js)
            for k in js: plus(constant,self.points[k]); plus(constant,self.zen[k])
            choices={}; cap={}; eligible=[]
            for eid,r in (self.by_kind[part].items() if a_ids is None else ((i,self.by_kind[part][i]) for i in sorted(a_ids))):
                if not permitted(r) or not supported(eid): continue
                if r['group_name']=='SP': continue
                # Default search is G-effect armor; explicit pools can opt into lower ranks.
                if not cfg and (a_ids is None or req.get('inventory_g_filter',False)) and req.get('g_armor_only',True) and not any(t=='Ｇ級効果' for t,v in self.abilities[eid]): continue
                ls=self.levels[eid]
                if cfg and 'level' in cfg: ls=[l for l in ls if l[0]==cfg['level']]
                if not ls: continue
                lv,slots,defense=endpoint(ls,level_mode)
                if slots<used: continue
                values={**self.armor_stats[eid],'defense':defense} if stat_targets-set(['defense']) else {'defense':defense}
                if any(values[k] is None for k in stat_targets): continue
                eligible.append((eid,lv,slots,values))
            eligible_armor[part]=len(eligible)
            # The shortlist is used ONLY in the first adaptive pass, never in a full pass.
            # Keep explicit allowlists intact and protect rare required contributions.
            fast_cap=req.get('_fast_armor_cap',0) if not cfg and a_ids is None else 0
            if fast_cap and len(eligible)>fast_cap:
                def score(a):
                    eid,lv,slots,values=a
                    return item_score(eid)+slots*.20+sum((values[k] or 0)/max(1,abs(limits.get(k,100)))*.15 for k in stat_targets)
                eligible=shortlist(eligible,fast_cap,score)
            for eid,lv,slots,values in eligible:
                i=model.var();
                for k in stat_targets: stat_rows[k][i]=values[k]
                decisions.append(i); choices[i]=(eid,lv); cap[i]=slots-used; item_vars[eid][i]=1
            if not choices: raise ValueError(f'no supported armor candidates: {part}')
            model.add({i:1 for i in choices},1,1); armor_vars[part]=choices; capacities[part]=cap; pool_counts[part]=len(choices)
        weapon_vars={};weapon_rows={};weapon_points={};weapon_auto={};weapon_skipped=0
        if joint:
            wreq=copy.deepcopy(req)
            if req.get('sigil_mode')=='auto':wreq['weapon']={**req.get('weapon',{}),'sigils':0}
            groups,weapon_skipped=self.weapon_groups(wreq)
            fixed_weapon_jewels=req.get('weapon',{}).get('jewels',[])
            used_weapon=sum(self.e.equipment(j,'jewel')['slots'] for j in fixed_weapon_jewels)
            minimum=1 if any(ext['sigil'].values()) else 0
            weapon_cap={}
            for _,_,rows in groups:
                r=rows[0]
                # With no generated sigil effects, reserving extra sockets provides
                # no benefit: the minimum reservation weakly dominates all larger ones.
                # Manual reservations remain exact; external values require at least one.
                for sigils in ([minimum] if req.get('sigil_mode')=='auto' else [req.get('weapon',{}).get('sigils',0)]):
                    if not validate_slots(r['slot_mode'],r['slots_reported'],used_weapon,sigils)['valid']:continue
                    if br and br['no_sigils'] and sigils:continue
                    i=model.var(cost=sigils*.001);decisions.append(i)
                    weapon_vars[i]=(r,sigils,rows)
                    weapon_cap[i]=(r['slots_reported']-used_weapon-sigils) if r['slot_mode'] in ('shared','decoration') else 0
                    for row in self.db.execute('SELECT skill_id,points FROM ferias_zenith WHERE weapon_type=? AND page=? AND anchor=?',(wt,r['page'],r['anchor'])):
                        weapon_points.setdefault(i,Counter())[row[0]]+=row[1]
                    from weapon_effects import intrinsic_levels
                    declared,_=intrinsic_levels(self.e,r)
                    weapon_auto[i]={x['skill_id']:x['points'] for x in declared}
                    if r['category']=='exotic':
                        t=self.e.level_names[('normal','早食い')][0];weapon_auto[i][t['skill_id']]=t['points']
            if not weapon_vars:raise ValueError('no supported physical weapon candidates')
            model.add({i:1 for i in weapon_vars},1,1)
            capacities['weapon']=weapon_cap
            pool_counts['weapon_groups']=len(groups);pool_counts['weapon_choices']=len(weapon_vars)
        walloc=next((x for x in baseline['slots']['equipment'] if x['part']=='weapon'),None)
        if not joint and walloc and walloc['mode'] in ('shared','decoration'):
            capacities['weapon']={}; weapon_capacity=walloc['capacity']-walloc['used']-walloc['sigils']
        else: weapon_capacity=0
        if joint:weapon_capacity=max(capacities['weapon'].values())
        # Global jewel counts encoded as bits; size-specific allocation ensures exact per-item packing.
        maxslots=sum(max(v.values()) for k,v in capacities.items() if k!='weapon')+weapon_capacity
        jids=ids(jallow,'jewel') if jallow is not None else None
        inventory={self.e.equipment(k,'jewel')['id']:v for k,v in req.get('jewel_limits',{}).items()}
        if any(type(v) is not int or v<0 for v in inventory.values()): raise ValueError('invalid jewel limit')
        fixed_counts=Counter(k for js in fixed_jewels.values() for k in js)
        fixed_counts.update(self.e.equipment(k,'jewel')['id'] for k in (req if joint else base).get('weapon',{}).get('jewels',[]))
        if any(fixed_counts[k]>v for k,v in inventory.items()): raise ValueError('fixed jewels exceed inventory limit')
        jewel_vars={}; by_size=defaultdict(dict)
        eligible_jewels=[]
        focused_ids=set().union(*(self.providers.get(sid,set()) for sid in targets|set(forbidden)))
        jewel_source=self.by_kind['jewel'].items()
        if jids is None and objective!='max_skills' and not req.get('full_jewel_pool',False):
            jewel_source=((eid,self.items[eid]) for eid in sorted(focused_ids) if self.items[eid]['kind']=='jewel')
        for eid,r in jewel_source:
            if not jewel_ok(eid) or (jids is not None and eid not in jids): continue
            if jids is None and objective!='max_skills' and not req.get('full_jewel_pool',False) and not relevant(eid): continue
            n=min(maxslots//r['slots'],inventory.get(eid,maxslots+fixed_counts[eid])-fixed_counts[eid])
            if n>0: eligible_jewels.append((eid,r,n))
        eligible_jewel_count=len(eligible_jewels)
        if fast_mode and jids is None and len(eligible_jewels)>300:
            eligible_jewels=shortlist(eligible_jewels,300,lambda a:item_score(a[0])/a[1]['slots'])
        for eid,r,n in eligible_jewels:
            bits={}
            for b in range(max(0,n).bit_length()):
                v=2**b; i=model.var(cost=v); decisions.append(i); bits[i]=v; item_vars[eid][i]=v; by_size[r['slots']][i]=v
            if bits:
                
                if sum(bits.values())>n: model.add(bits,high=n)
                jewel_vars[eid]=bits
        pool_counts['jewel']=len(jewel_vars)
        pack=defaultdict(dict)
        for part,cap in capacities.items():
            maxcap=weapon_capacity if part=='weapon' else max(cap.values())
            row=Counter({i:-v for i,v in cap.items()})
            for size in (1,2,3):
                i=model.var(maxcap//size); pack[part][size]=i; row[i]+=size
            model.add(row,high=weapon_capacity if part=='weapon' and not joint else 0)
        for size in (1,2,3):
            row=Counter(by_size[size]); row.update({v[size]:-1 for v in pack.values()}); model.add(row,0,0)
        # Cuffs can be locked exactly or searched (including a zero-slot secret cuff).
        cuff_vars={}; cids=ids(callow,'cuff') if callow is not None else None
        cuff_limits={self.e.equipment(k,'cuff')['id']:v for k,v in req.get('cuff_limits',{}).items()}
        if any(type(v) is not int or v<0 for v in cuff_limits.values()): raise ValueError('invalid cuff limit')
        fixed_cuffs=Counter(self.e.equipment(k,'cuff')['id'] for k in base.get('cuffs',[]))
        if any(fixed_cuffs[k]>v for k,v in cuff_limits.items()): raise ValueError('fixed cuffs exceed inventory limit')
        eligible_cuff_count=0
        if 'cuffs' not in base:
            countrow={}; slotrow={}; secretrow={}; eligible_cuffs=[]
            cuff_source=self.by_kind['cuff'].items()
            if cids is None and objective!='max_skills' and not req.get('full_jewel_pool',False):
                cuff_source=((eid,self.items[eid]) for eid in sorted(focused_ids) if self.items[eid]['kind']=='cuff')
            for eid,r in cuff_source:
                if not permitted(r) or not supported(eid) or (cids is not None and eid not in cids): continue
                if cids is None and objective!='max_skills' and not req.get('full_jewel_pool',False) and not relevant(eid): continue
                if r['slots'] not in (0,1,2): continue
                secret=any(t=='スキル枠消費なし' for t,v in self.abilities[eid])
                if r['group_name']=='P' and not base.get('premium_poogie_clothes'): continue
                if ('Ｇ' in (r['class_code'] or '') or '辿' in (r['class_code'] or '') or secret) and not base.get('g_poogie'): continue
                if cuff_limits.get(eid,2)>0: eligible_cuffs.append((eid,r,secret))
            eligible_cuff_count=len(eligible_cuffs)
            if fast_mode and cids is None and len(eligible_cuffs)>100:
                eligible_cuffs=shortlist(eligible_cuffs,100,lambda a:item_score(a[0])/max(1,a[1]['slots']))
            for eid,r,secret in eligible_cuffs:
                bits={}
                for v in (1,2) if r['slots']==1 and not secret else (1,):
                    i=model.var(cost=.01*v); decisions.append(i); bits[i]=v; item_vars[eid][i]=v; countrow[i]=v; slotrow[i]=v*r['slots']; secretrow[i]=v*int(secret)
                bound=min(cuff_limits.get(eid,2),2 if r['slots']==1 and not secret else 1)
                if sum(bits.values())>bound: model.add(bits,high=bound)
                cuff_vars[eid]=bits
            model.add(countrow,high=2); model.add(slotrow,high=2); model.add(secretrow,high=1)
        pool_counts['cuff']=len(cuff_vars)
        bounds=DecisionBounds({**armor_vars,**({'weapon':weapon_vars} if joint else {})},jewel_vars,cuff_vars,self.items,maxslots)
        # Build sparse skill coefficients once instead of scanning the pool for every skill.
        skill_rows=defaultdict(Counter)
        for eid,vs in item_vars.items():
            values=Counter(self.points[eid]); plus(values,self.zen[eid])
            for sid,val in values.items():
                if val: plus(skill_rows[sid],vs,val)
        for i,values in weapon_points.items():
            for sid,val in values.items():skill_rows[sid][i]+=val
        supply_rows=defaultdict(Counter);supply_constants=Counter()
        source_rules=req.get('zenith_sources',{})
        from activation import supplied_points
        for sid,providers in source_rules.items():
            supply_constants[sid]=supplied_points(baseline,sid,providers)
            if 'jewel' in providers:
                for keys in fixed_jewels.values():
                    for eid in keys:supply_constants[sid]+=self.points[eid].get(sid,0)+self.zen[eid].get(sid,0)
            for eid,vs in item_vars.items():
                kind=self.items[eid]['kind'];provider='armor' if kind in PARTS else kind
                if provider in providers:plus(supply_rows[sid],vs,self.points[eid].get(sid,0)+self.zen[eid].get(sid,0))
            if 'weapon' in providers:
                for i,values in weapon_points.items():supply_rows[sid][i]+=values.get(sid,0)
        # Automatic effects are alternatives to point activation, not actual points.
        # Relax only the requirement rows; bans and slot cuts still use raw points.
        fixed_auto={}; fixed_gear_auto={}
        for a in baseline['automatic']:
            sid=a['id']; fixed_auto[sid]=max(fixed_auto.get(sid,0),a['threshold'])
            if a.get('source')!='meal': fixed_gear_auto[sid]=max(fixed_gear_auto.get(sid,0),a['threshold'])
        auto_vars=defaultdict(list)
        for eid,vs in item_vars.items():
            for sid,pt in self.auto[eid].items():
                auto_vars[sid].append((pt,vs))
        for i,values in weapon_auto.items():
            for sid,pt in values.items():auto_vars[sid].append((pt,{i:1}))
        def attainment(sid,pt,include_meal=True):
            row=Counter(supply_rows[sid] if sid in source_rules else skill_rows[sid]); k=supply_constants[sid] if sid in source_rules else constant[sid]
            if pt<0:
                return Counter({i:-v for i,v in row.items()}),-k
            lower,_=bounds.interval(row,k)
            if (fixed_auto if include_meal else fixed_gear_auto).get(sid,0)>=pt:
                return Counter(),pt
            big=max(0,pt-lower)
            for level,vs in auto_vars[sid]:
                if level>=pt: plus(row,vs,big)
            return row,k
        for sid,pt in wanted.items():
            row,k=attainment(sid,pt)
            model.add(row,low=abs(pt)-k)
            if sid.startswith('zenith:'):
                target=json.loads(self.e.skills[sid]['metadata'])['ja'].get('Target')
                base_sid=self.e.names.get(('normal',target))
                if base_sid:
                    alternatives=set()
                    tiers=[t for t in self.e.levels[base_sid] if t['points']>0 or t['ja']=='青魂']
                    alternatives.update((base_sid,t['points']) for t in tiers)
                    for provider,tiers in self.e.levels.items():
                        if not provider.startswith('normal:'):continue
                        for tier in tiers:
                            if any(t['skill_id']==base_sid for t in self.e.contained_levels(tier)):
                                alternatives.add((provider,tier['points']))
                    # A mandatory gear provider already has the same point/automatic
                    # attainment constraint. Avoid redundant OR binaries; food is not
                    # a gear prerequisite, so its family cannot justify this shortcut.
                    meal=self.e.meal_level(ext)
                    if any(provider in wanted and self.reaches(wanted[provider],threshold)
                           and (meal is None or provider!=meal['skill_id'])
                           for provider,threshold in alternatives):continue
                    gates={};fixed_base=False
                    for provider,threshold in sorted(alternatives):
                        row,k=attainment(provider,threshold,include_meal=False)
                        lower,upper=bounds.interval(row,k);threshold=abs(threshold)
                        if lower>=threshold: fixed_base=True;break
                        if upper<threshold:continue
                        i=model.var();gates[i]=1;big=threshold-lower
                        c=Counter(row);c[i]-=big;model.add(c,low=threshold-k-big)
                    if not fixed_base:model.add(gates,low=1)
        # Every mandatory ordinary family must fit, unless it can be supplied
        # automatically or exempted by actual selected gear. Twelve is a safe
        # upper bound on the non-Zenith base capacity; extra earlier skills are
        # handled by the evaluator and learned cuts below.
        extension_id=self.e.names[('zenith','スキル枠拡張')]
        required_slots=0;capacity_row=Counter(skill_rows[extension_id])
        fixed_free={self.e.names.get(('normal',v)) for key in base.get('cuffs',[])
                    for t,v in self.abilities[self.e.equipment(key,'cuff')['id']] if t=='スキル枠消費なし'}
        for sid,pt in wanted.items():
            if not sid.startswith('normal:') or fixed_auto.get(sid,0)>=pt>0 or sid in fixed_free:continue
            required_slots+=1
            for level,vs in auto_vars[sid]:
                if pt>0 and level>=pt:plus(capacity_row,vs)
            for eid,vs in item_vars.items():
                if any(t=='スキル枠消費なし' and self.e.names.get(('normal',v))==sid for t,v in self.abilities[eid]):plus(capacity_row,vs)
        model.add(capacity_row,low=required_slots-12-constant[extension_id])
        # Positive cumulative tier bonuses are an optimistic relaxation. The evaluator
        # enforces actual activation, signed penalties and slot/overlap effects.
        if stat_targets and stat_mode in ('adjusted','external'):
            for sid,levels in self.e.levels.items():
                previous=Counter()
                for tier in sorted((v for v in levels if v['points']>0),key=lambda v:v['points']):
                    delta=tier_stats(tier)
                    if not delta or not (set(delta)&stat_targets): continue
                    pt=tier['points']; row,k0=attainment(sid,pt,include_meal=False)
                    lower,upper=bounds.interval(row,k0)
                    if upper<pt: continue
                    i=model.var(); big=max(0,pt-lower)
                    c=Counter(row); c[i]-=big
                    model.add(c,low=pt-k0-big)
                    for k in stat_targets:
                        stat_rows[k][i]+=max(0,delta.get(k,0)-previous[k])
                    previous.update({k:v-previous[k] for k,v in delta.items()})
        for k,v in limits.items(): model.add(stat_rows[k],low=v-(upper_bonus(ext)[k] if stat_mode=='external' else 0))
        # Base stats are exact linear sums; adjusted objectives are ranked after replay.
        if objective in OBJECTIVES:
            for k in ({'defense'} if objective=='defense' else ELEMENTS):
                for i,v in stat_rows[k].items(): model.cost[i]-=100*v
        for sid,pt in forbidden.items():
            if pt<0:
                model.add(skill_rows[sid],low=pt+1-constant[sid])
                continue
            model.add(skill_rows[sid],high=pt-1-constant[sid])
            if fixed_auto.get(sid,0)>=pt: model.add({},low=1)
            for level,vs in auto_vars[sid]:
                if level>=pt: model.add(vs,high=0)
        # Conservative: do not reach a forbidden positive skill threshold, even if it might overflow.
        if br:
            for sid,skill in self.e.skills.items():
                if banned_skill(skill['ja'],br,wt,WEAPON_SECRET.values()):
                    thresholds=[v['points'] for v in self.e.levels[sid] if v['points']>0]
                    if thresholds: model.add(skill_rows[sid],high=min(thresholds)-1-constant[sid])
        # Attainment indicators are a relaxation: the evaluator still checks actual slots and overlap.
        def reward(sid,pt,cost):
            row,k=attainment(sid,pt)
            pt=abs(pt)
            lower,upper=bounds.interval(row,k)
            if upper<pt: return
            if lower>=pt: return
            big=pt-lower; i=model.var(cost=-cost)
            constraint=Counter(row); constraint[i]-=big
            model.add(constraint,low=pt-k-big)
        if optional:
            # One optional score point dominates the cost of any extra jewels/cuffs.
            for (sid,pt),weight in optional.items(): reward(sid,pt,100*weight)
            # Stages break equal weighted attainment scores, including useful progress
            # toward a selected tier. They never become feasibility constraints.
            for (sid,pt),weight in optional.items():
                tiers=[x for x in self.e.levels[sid] if self.selectable(x) and (x['points']<0)==(pt<0)]
                for tier in tiers: reward(sid,tier['points'],weight/max(1,len(tiers)*(sum(optional.values())+1)))
        if objective=='max_skills':
            # Count positive ordinary skill families, excluding other weapon secrets.
            reward_cost=100*(sum(optional.values())+1)
            for sid,skill in self.e.skills.items():
                if not sid.startswith('normal:') or (skill['ja'] in WEAPON_SECRET.values() and skill['ja']!=WEAPON_SECRET[wt]): continue
                pts=[v['points'] for v in self.e.levels[sid] if v['points']>0]
                if pts: reward(sid,min(pts),reward_cost)
        if objective=='surplus':
            # The required thresholds are hard constraints, so minimizing their sum minimizes surplus.
            for sid,pt in wanted.items():
                for i,v in skill_rows[sid].items(): model.cost[i]+=100*v*(1 if pt>0 else -1)
        # Learn necessary slot constraints after overflow. Use optimistic bounds:
        # 12 base slots, raw extension points, and all potentially exempt families.
        slot_cuts=set(); reach_bits={}
        exempt={self.e.names.get(('normal',v)) for abilities in self.abilities.values()
                for t,v in abilities if t=='スキル枠消費なし'}
        extension=self.e.names[('zenith','スキル枠拡張')]
        def learn_overflow(sid):
            if sid in slot_cuts or sid in exempt:
                return
            slot_cuts.add(sid)
            row=Counter()
            fixed_reached=0
            priority=int(sid.split(':')[1])
            for prior,tiers in self.e.levels.items():
                if not prior.startswith('normal:') or prior in exempt or int(prior.split(':')[1])>=priority:
                    continue
                for sign in (1,-1):
                    pts=[sign*t['points'] for t in tiers if sign*t['points']>0]
                    if not pts:
                        continue
                    pt=min(pts); c=Counter({i:sign*v for i,v in skill_rows[prior].items()}); k=sign*constant[prior]
                    lower,upper=bounds.interval(c,k)
                    if upper<pt:
                        continue
                    if lower>=pt:
                        fixed_reached+=1; continue
                    key=(prior,sign)
                    if key not in reach_bits:
                        # Reaching a positive or negative threshold forces the indicator to 1.
                        i=model.var(); reach_bits[key]=i
                        c[i]-=upper-pt+1
                        model.add(c,high=pt-1-k)
                    row[reach_bits[key]]+=1
            plus(row,skill_rows[extension],-1)
            # Leave one ordinary slot for the required skill itself.
            model.add(row,high=11+constant[extension]-fixed_reached)

        rejection_reasons=Counter(); rejection_samples=[]; rejection_log=[]
        base_cost=list(model.cost)
        fully_fixed=all(req.get('armor',{}).get(p) for p in PARTS)
        diversify=bool(req.get('diverse_armor')) and not (fully_fixed and req.get('collect_variants'))
        results=list(initial_hits); seen_builds={self.build_key(h['build']) for h in results}; seen_effects={self.effect_key(h['build'],h['evaluation']) for h in results} if req.get('dedupe_effects') else set(); duplicates=0; rejected=0; attempts=0; status='time_limit'
        # Seed the expanded pass with already validated solutions; exclude their armor in diversity mode.
        if diversify:
            for h in results:
                selected={i:1 for part,choices in armor_vars.items() for i,(eid,lv) in choices.items() if eid==h['build']['armor'][part]['item']}
                if len(selected)==len(PARTS): model.add(selected,high=len(PARTS)-1)
        for h in results:
            b=h['build']; selected=set()
            for part,choices in armor_vars.items():
                selected.update(i for i,(eid,lv) in choices.items() if eid==b['armor'][part]['item'] and lv==b['armor'][part]['level'])
            if joint:
                w=b.get('weapon',{});selected.update(i for i,(r,n,_) in weapon_vars.items() if (r['page'],r['anchor'],n)==(w.get('page'),w.get('anchor'),w.get('sigils',0)))
            if len(selected)!=len(PARTS)+int(joint): continue
            counts=Counter(self.e.equipment(j,'jewel')['id'] for a in list(b['armor'].values())+[b.get('weapon',{})] for j in a.get('jewels',[]))
            counts.subtract(fixed_counts)
            ccounts=Counter(self.e.equipment(c,'cuff')['id'] for c in b.get('cuffs',[])); ccounts.subtract(fixed_cuffs)
            possible=True
            for pool,quantities in ((jewel_vars,counts),(cuff_vars,ccounts)):
                if any(v>0 and eid not in pool for eid,v in quantities.items()): possible=False;break
                for eid,bits in pool.items():
                    n=quantities[eid]
                    if n<0 or n>sum(bits.values()): possible=False;break
                    selected.update(i for i,v in bits.items() if n&v)
            if possible: model.add({i:-1 if i in selected else 1 for i in decisions},low=1-len(selected))
        for combination in req.get('_excluded_armor_sets',[])[:256]:
            selected={i:1 for part,choices in armor_vars.items() for i,(eid,lv) in choices.items() if eid==combination.get(part)}
            if len(selected)==5:model.add(selected,high=4)
        if results:self.emit_progress(results,req,start)
        build_seconds=time.monotonic()-start; solve_seconds=0; validation_seconds=0; first_candidate=None
        # A candidate is never published without replaying the independent evaluator.
        while (len(results)<limit or (initial_hits and attempts==0)) and time.monotonic()-start<seconds:
            if diversify and results:
                frequency=Counter(a['item'] for h in results for a in h['build']['armor'].values())
                for choices in armor_vars.values():
                    for i,(eid,lv) in choices.items():model.cost[i]=base_cost[i]+5*frequency[eid]/len(results)
            solve_start=time.monotonic()
            model.feasibility_first=bool(req.get('_feasibility_only')) or (joint and len(wanted)>=10 and not results and attempts==0)
            sol=model.solve(seconds-(time.monotonic()-start)); attempts+=1
            solve_seconds+=time.monotonic()-solve_start
            if sol.x is None or sol.status not in (0,1):
                status='model_exhausted' if sol.status==2 else 'time_limit' if sol.status==1 else 'solver_error'; break
            x=np.rint(sol.x).astype(int)
            if np.max(np.abs(sol.x-x))>1e-4 or not model.feasible(x):
                status='solver_invalid_candidate'; break
            build=copy.deepcopy(base); build['armor']={}
            for part,choices in armor_vars.items():
                eid,lv=next(v for i,v in choices.items() if x[i]); build['armor'][part]={'item':eid,'level':lv,'jewels':fixed_jewels[part][:]}
            if joint:
                r,n,alternatives=next(v for i,v in weapon_vars.items() if x[i]);build['weapon']={'page':r['page'],'anchor':r['anchor'],'sigils':n,'jewels':list(req.get('weapon',{}).get('jewels',[]))}
            if 'cuffs' not in build: build['cuffs']=[eid for eid,vs in cuff_vars.items() for _ in range(sum(x[i]*v for i,v in vs.items()))]
            queues=defaultdict(list)
            for eid,vs in jewel_vars.items(): queues[self.items[eid]['slots']].extend([eid]*sum(x[i]*v for i,v in vs.items()))
            for part,vs in pack.items():
                target=build['weapon'] if part=='weapon' else build['armor'][part]
                for size,i in vs.items():
                    for _ in range(x[i]): target.setdefault('jewels',[]).append(queues[size].pop())
            validation_start=time.monotonic()
            report=self.e.evaluate(build)
            validation_seconds+=time.monotonic()-validation_start
            normal={s['id']:s for s in report['skills']}; zenith={s['id']:s for s in report['zenith']}
            ok=report['valid'] and satisfies(report,req) and all(self.achieved(report,sid,pt) for sid,pt in wanted.items()) and not self.forbidden_hit(report,forbidden) and self.supply_met(report,req)
            if br and any(banned_skill(s['ja'],br,wt,WEAPON_SECRET.values()) and s['status'] in ('active','overlap') for s in report['skills']): ok=False
            if br and any(banned_skill(self.e.skills[s['id']]['ja'],br,wt,WEAPON_SECRET.values()) for s in report['automatic']): ok=False
            if br and ok: report['bounty']=public_rules(req['bounty'])
            if ok:
                key=self.build_key(build)
                effect_key=self.effect_key(build,report) if req.get('dedupe_effects') else None
                if key not in seen_builds and (effect_key is None or effect_key not in seen_effects):
                    # In diversity mode, exclude this five-piece armor combination only after validation.
                    if diversify:
                        model.add({i:1 for choices in armor_vars.values() for i in choices if x[i]},high=len(PARTS)-1)
                    seen_builds.add(key); seen_effects.add(effect_key); results.append({'build':build,'evaluation':report,'new_jewels':int(sum(x[i]*v for vs in jewel_vars.values() for i,v in vs.items())),'solver_optimal_for_relaxed_model':sol.status==0 and not model.feasibility_first})
                    if first_candidate is None:first_candidate=time.monotonic()-start
                    self.emit_progress(results, req, start)
                else: duplicates+=1
            else:
                rejected+=1
                reasons=[{'reason':'invalid_equipment','detail':error} for error in report['errors']]
                if not satisfies(report,req): reasons.append({'reason':'stat_constraints'})
                for sid,pt in wanted.items():
                    if not self.achieved(report,sid,pt):
                        s=normal.get(sid,zenith.get(sid,{}))
                        reasons.append({'reason':'required_'+s.get('status','not_reached'), 'skill':sid,'required':pt,
                                        'points':s.get('points',s.get('raw_points',0)), 'threshold':s.get('threshold'),
                                        'overlap_by':s.get('overlap_by',[])})
                if not self.supply_met(report,req):reasons.append({'reason':'zenith_supply_source'})
                if self.forbidden_hit(report,forbidden): reasons.append({'reason':'forbidden_skill'})
                if not reasons: reasons.append({'reason':'bounty_restriction'})
                rejection_reasons.update(r['reason'] for r in reasons)
                rejection_log.append({'attempt':attempts,'reasons':reasons})
                # Bounded samples retain concrete reproducible builds without unbounded output.
                if len(rejection_samples)<20: rejection_samples.append({'attempt':attempts,'reasons':reasons,'build':build})
                for sid in wanted:
                    if normal.get(sid,{}).get('status')=='overflow' and not auto_vars[sid] and (wanted[sid]<0 or fixed_auto.get(sid,0)<wanted[sid]): learn_overflow(sid)
            # Exclude the complete decision vector, not just armor; alternate jewels remain searchable.
            ones=sum(x[i] for i in decisions); model.add({i:-1 if x[i] else 1 for i in decisions},low=1-ones)
            if sol.status==1: status='time_limit'; break
        if len(results)>=limit: status='result_limit'
        return {'status':status,'objective':objective,'results':self.rank(results,req)[:limit],'attempts':attempts,'rejected':rejected,'rejection_reasons':dict(rejection_reasons),'rejection_samples':rejection_samples,'rejection_log':rejection_log,'duplicates':duplicates,'integrated_weapon':joint,'weapon_rows_skipped':weapon_skipped,'sigil_effect_scope':'Reserved slots only; no random sigil effects generated. Explicit external values are user supplied.','pool_counts':pool_counts,'eligible_armor':eligible_armor,'eligible_jewels_in_mode':eligible_jewel_count,'eligible_cuffs_in_mode':eligible_cuff_count,'pool_mode':'full' if req.get('full_jewel_pool') or objective=='max_skills' else 'prioritized' if req.get('_fast_armor_cap') else 'focused','model_variables':len(model.cost),'model_constraints':len(model.rows),'slot_cuts':len(slot_cuts),'timings':{'model_build_seconds':round(build_seconds,6),'solve_seconds':round(solve_seconds,6),'validation_seconds':round(validation_seconds,6),'first_candidate_seconds':round(first_candidate,6) if first_candidate is not None else None},'elapsed_seconds':round(time.monotonic()-start,3),'complete_game_search':False,'notes':['Only selected candidate pools and supported abilities; defense/resistance scope is armor plus supported flat skills and optional external effects.','Focused pools include Zenith prerequisites and their composite providers; full pool includes all supported jewels and cuffs. Both may miss solutions. Objectives are relaxed point attainment followed by actual activation ranking, not global game-optimal results.','Rain and unresolved evaluator rules are not fully verified. No result is not proof of game impossibility.']}



    # Equivalent weapon groups share slot behavior and skill contributions; no DPS equivalence is implied.
    def weapon_groups(self, req):
        wt=req['weapon_type']; fixed=req.get('weapon',{})
        if set(fixed)-{'jewels','sigils'}: raise ValueError('auto weapon accepts only reserved sigils and fixed jewels')
        selectors=req.get('weapon_candidates'); allowed=None
        if selectors is not None: allowed={(x['page'],x['anchor']) for x in selectors}
        used=sum(self.e.equipment(j,'jewel')['slots'] for j in fixed.get('jewels',[])); sigils=fixed.get('sigils',0)
        rows=self.db.execute('SELECT v.*,w.name_ja,w.conflict,w.pax_match FROM ferias_variants v JOIN ferias_weapons w USING(weapon_type,upstream_id) WHERE v.weapon_type=?',(wt,))
        z=defaultdict(list)
        for row in self.db.execute('SELECT page,anchor,skill_id,points FROM ferias_zenith WHERE weapon_type=?',(wt,)):
            z[(row[0],row[1])].append((row[2],row[3]))
        groups=defaultdict(list); seen=set(); skipped=0
        for row in rows:
            key=(row['page'],row['anchor'])
            if allowed is not None and key not in allowed: continue
            seen.add(key)
            from weapon_effects import intrinsic_levels
            declared,unmapped=intrinsic_levels(self.e,row)
            # Unsupported text and ambiguous weapon identities remain excluded.
            if not self.weapon_permitted(row,req) or row['conflict'] or unmapped or row['slot_mode'] not in ('shared','decoration','sigil') or any(sid is None or pt is None for sid,pt in z[key]): skipped+=1; continue
            if not validate_slots(row['slot_mode'],row['slots_reported'],used,sigils)['valid']: skipped+=1; continue
            pts=Counter()
            for sid,pt in z[key]: pts[sid]+=pt
            signature=(row['slot_mode'],row['slots_reported'],tuple(sorted(pts.items())),row['category']=='exotic',tuple(sorted((x['skill_id'],x['points']) for x in declared)))
            groups[signature].append(row)
        if allowed is not None and allowed-seen: raise ValueError(f'unknown weapon selectors: {allowed-seen}')
        def rep_key(r): return (r['pax_match']=='linked_stats_differ',-(r['attack'] or 0),r['page'],r['anchor'])
        wanted=self.requirements(req['required'])
        ordered=[]
        for signature,rs in groups.items():
            rs.sort(key=rep_key); points=dict(signature[2])
            priority=sum(min(abs(pt),points.get(sid,0)*(1 if pt>0 else -1)) for sid,pt in wanted.items())
            usable=signature[1]-sigils-used if signature[0] in ('shared','decoration') else 0
            ordered.append((priority,usable,rs))
        ordered.sort(key=lambda g:(-g[0],-g[1],rep_key(g[2][0])))
        return ordered,skipped

    def search_weapons(self, req):
        start=time.monotonic(); seconds=float(req.get('seconds',15)); limit=int(req.get('limit',3)); max_groups=req.get('weapon_group_limit'); per_group=req.get('results_per_weapon_group',limit if req.get('search_strategy')=='adaptive' else 1)
        if not math.isfinite(seconds) or not 0<seconds<=300 or not 1<=limit<=30 or (max_groups is not None and (type(max_groups) is not int or not 1<=max_groups<=100)) or type(per_group) is not int or not 1<=per_group<=30: raise ValueError('invalid search limits')
        groups,skipped=self.weapon_groups(req); hits=list(req.get('_initial_hits',[])); reports=[]; attempts=rejected=0; rejection_reasons=Counter(); rejection_log=[]; rejection_samples=[]
        selected=groups if max_groups is None else groups[:max_groups]
        # A single allowed group must not silently cap a multi-result search at one.
        # Keep an explicit per-group cap and the existing multi-group distribution.
        if len(selected)==1 and 'results_per_weapon_group' not in req:
            per_group=limit
        adaptive=req.get('search_strategy')=='adaptive' and not req.get('full_jewel_pool')
        def result_key(h):
            return tuple((p,a['item']) for p,a in sorted(h['build']['armor'].items())) if req.get('diverse_armor') and not req.get('collect_variants') else self.effect_key(h['build'],h['evaluation']) if req.get('dedupe_effects') else self.build_key(h['build'])
        selector_groups={(r['page'],r['anchor']):index for index,(_,_,rows) in enumerate(groups) for r in rows}
        def capped(source):
            counts=Counter();seen_keys=set();kept=[]
            for hit in self.rank(source,req):
                key=result_key(hit)
                if key in seen_keys:continue
                w=hit['build'].get('weapon',{});selector=(w.get('page'),w.get('anchor'))
                group=selector_groups.get(selector,selector)
                if counts[group]>=per_group:continue
                kept.append(hit);counts[group]+=1;seen_keys.add(key)
            return kept
        hits=capped(hits);seen={result_key(h) for h in hits}
        for i,(_,_,rows) in enumerate(selected):
            remaining=seconds-(time.monotonic()-start)
            if remaining<=.05: break
            r=rows[0]; sub=copy.deepcopy(req); sub['auto_weapon']=False; sub['_live_group']=True
            sub['weapon']={**req.get('weapon',{}),'page':r['page'],'anchor':r['anchor']}
            sub['_initial_hits']=[h for h in req.get('_initial_hits',[]) if h['build'].get('weapon',{}).get('page')==r['page'] and h['build'].get('weapon',{}).get('anchor')==r['anchor']]
            sub['seconds']=min(remaining,max(2.0,remaining/(len(selected)-i))); sub['limit']=min(limit,per_group)
            # One representative per group: equivalent alternatives remain visible to the user.
            result=self.search_with_strategy(sub); attempts+=result['attempts']; rejected+=result['rejected']
            rejection_reasons.update(result.get('rejection_reasons',{}))
            rejection_log.extend({'weapon_group':i,**entry} for entry in result.get('rejection_log',[]))
            rejection_samples.extend(result.get('rejection_samples',[])[:max(0,20-len(rejection_samples))])
            reports.append({'page':r['page'],'anchor':r['anchor'],'status':result['status'],'equivalent_count':len(rows)})
            for h in result['results']:
                h['weapon_group']={'representative':{'name':r['name_source'],'id':r['upstream_id'],'level':r['level']},'equivalent_count':len(rows),
                    'alternatives':[{'page':a['page'],'anchor':a['anchor'],'name':a['name_source'],'level':a['level']} for a in rows[1:21]],'alternatives_truncated':len(rows)>21}
                hits.append(h); seen.add(result_key(h))
            hits=capped(hits);seen={result_key(h) for h in hits}
            if self.progress is not None:
                # Avoid displaying duplicate equipment groups or unverified candidates.
                unique_progress = {}
                for h in self.rank(hits, req):
                    unique_progress.setdefault(result_key(h), h)
                self.emit_progress(list(unique_progress.values()), req, start)
            # Adaptive search returns promptly when the requested number of distinct results is reached.
            # Full mode retains the original exhaustive-within-budget behavior.
            if adaptive and len(seen)>=limit: break
        # Remove identical equipment decision sets independently of placement/order.
        unique={}
        for h in self.rank(hits,req):
            unique.setdefault(result_key(h),h)
        ranked=self.rank(list(unique.values()),req)[:limit]
        status='partial_weapon_search' if len(reports)<len(groups) or any(r['status']!='model_exhausted' for r in reports) else 'weapon_groups_searched'
        return {'status':status,'objective':req.get('objective','minimal_jewels'),'results':ranked,'attempts':attempts,'rejected':rejected,'rejection_reasons':dict(rejection_reasons),'rejection_log':rejection_log,'rejection_samples':rejection_samples,'elapsed_seconds':round(time.monotonic()-start,3),'complete_game_search':False,
                'weapon_groups':len(groups),'weapon_groups_searched':len(reports),'weapon_groups_untested':len(groups)-len(reports),'weapon_rows_skipped':skipped,'group_reports':reports,
                'notes':['Grouped by skill contribution and slot behavior, not damage; representative prefers non-discrepant data, then displayed attack.','Weapon filters and bounded group budget apply; unhandled effects/special sockets excluded. Rain availability not verified.']}

    # Optional equivalence: same armor/weapon, all raw skill totals, and same evaluated slot/stat values.
    # Different acquisition routes remain visible when the user disables this option.
    def effect_key(self, build, report):
        armor,weapon,_,_=self.build_key(build)
        normal=tuple(sorted((s['id'],s['points'],s['status'],s['threshold']) for s in report['skills']))
        zenith=tuple(sorted((s['id'],s['raw_points'],s['level'],s['has_base_skill']) for s in report['zenith']))
        automatic=tuple(sorted((s['id'],s['ja']) for s in report['automatic']))
        slots=report['slots']
        return armor,weapon,normal,zenith,automatic,slots['used'],slots['capacity'],slots['cuff_used'],json.dumps(report.get('defense_stats'),sort_keys=True)


    # Probe additional skill targets individually, preserving all original hard constraints.
    def probe(self, req, candidates=None, seconds=30, candidate_limit=24, candidate_offset=0):
        try:return self._probe(req,candidates,seconds,candidate_limit,candidate_offset)
        except (ValueError,KeyError,TypeError) as exc:
            if not req.get('structured_outcomes'):raise
            return {'status':'input_conflict','reason':str(exc),'auto_candidates':candidates is None,'results':[],
                    'next_offset':None,'elapsed_seconds':0,'complete_game_search':False}

    def _probe(self, req, candidates=None, seconds=30, candidate_limit=24, candidate_offset=0):
        start=time.monotonic(); seconds=float(seconds)
        if not math.isfinite(seconds) or not 0<seconds<=300: raise ValueError('invalid probe seconds')
        if type(candidate_limit) is not int or not 1<=candidate_limit<=1000: raise ValueError('invalid candidate_limit')
        if type(candidate_offset) is not int or candidate_offset<0:raise ValueError('invalid candidate offset')
        req=self.prepare_request(req)
        wanted=self.requirements(req['required']); forbidden=self.conflicts(req); todo=[]; seen=set(); untested_count=0; auto_candidates=candidates is None
        if auto_candidates:
            # Start from a valid baseline and propose the next unachieved tier of each skill family.
            seed=copy.deepcopy(req);seed['live_preview']=True;seed['limit']=1;seed['objective']='minimal_jewels' if wanted or req.get('min_stats') else req.get('objective','minimal_jewels');seed['seconds']=seconds*.25
            initial=self.search(seed); hits=initial['results']; report=hits[0]['evaluation'] if hits else None
            totals={s['id']:s['points'] for s in report['skills']} if report else {}
            if report: totals.update({s['id']:s['raw_points'] for s in report['zenith']})
            choices=[]
            for sid,skill in self.e.skills.items():
                if skill['ja'] in WEAPON_SECRET.values() and skill['ja']!=WEAPON_SECRET[req['weapon_type']]: continue
                if wanted.get(sid,0)<0: continue
                pts=sorted({s['points'] for s in self.e.levels[sid] if s['points']>0 and s['points']>wanted.get(sid,0)})
                if sid not in wanted and any(s['ja']=='青魂' for s in self.e.levels[sid]):
                    if not (sid in forbidden and self.reaches(-10,forbidden[sid])):
                        choices.append((max(0,totals.get(sid,0)+10),sid,-10))
                for next_pt in pts:
                    if not (sid in forbidden and self.reaches(next_pt,forbidden[sid])):choices.append((max(0,next_pt-totals.get(sid,0)),sid,next_pt))
            choices.sort(key=lambda x:(x[1],x[2]));untested_count=max(0,len(choices)-candidate_offset-candidate_limit)
            candidates=[{'skill':sid,'points':pt} for _,sid,pt in choices[candidate_offset:candidate_offset+candidate_limit]]
        for target in candidates:
            sid,pt=self.requirement(target)
            if sid in forbidden and self.reaches(pt,forbidden[sid]): continue
            if sid in wanted and (wanted[sid]<0)!=(pt<0): continue
            if req.get('bounty') and banned_skill(self.e.skills[sid]['ja'],rules(req['bounty']),req['weapon_type'],WEAPON_SECRET.values()): continue
            if (sid,pt) not in seen: todo.append((sid,pt,target)); seen.add((sid,pt))
        results=[]
        for i,(sid,pt,target) in enumerate(todo):
            if sid in wanted and self.reaches(wanted[sid],pt):
                results.append({'target':target,'status':'already_required'}); continue
            remaining=seconds-(time.monotonic()-start)
            if remaining<=.05:
                results.append({'target':target,'status':'not_tested'}); continue
            sub=copy.deepcopy(req); sub['required'].append(target);sub['limit']=1;sub['objective']='minimal_jewels';sub['seconds']=remaining/max(1,len(todo)-i)
            result=self.search(sub)
            if result['results']:
                results.append({'target':target,'status':'found','witness':result['results'][0]})
            else:
                results.append({'target':target,'status':'not_found_in_budget','search_status':result['status']})
        return {'status':'probe_partial' if any(x['status']=='not_tested' for x in results) else 'probe_complete','total_targets':len(choices) if auto_candidates else len(todo),'results':results,'auto_candidates':auto_candidates,'candidate_offset':candidate_offset,'next_offset':candidate_offset+len(candidates) if untested_count else None,'unselected_candidate_count':untested_count,'elapsed_seconds':round(time.monotonic()-start,3),'complete_game_search':False,'notes':['Each found target is individually achievable with original requirements in this model. Multiple found targets are not necessarily jointly achievable.']}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True,type=Path);p.add_argument('--request',required=True,type=Path);p.add_argument('--out',type=Path);a=p.parse_args(argv)
    with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        req=json.loads(a.request.read_text(encoding='utf-8-sig')); searcher=Searcher(db)
        probe=req.pop('probe',None)
        if req.get('live_preview') is True and probe is None and a.out:
            # Atomically publish intermediate results to the parent process.
            progress_path = a.out.with_suffix('.progress')
            def publish_progress(result):
                tmp = progress_path.with_suffix('.progress.tmp')
                try:
                    tmp.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
                    tmp.replace(progress_path)
                except OSError:
                    # Progress is advisory: a Windows file lock must not abort search.
                    pass
            searcher.progress = publish_progress
        result=searcher.probe(req,probe.get('candidates'),probe.get('seconds',30),probe.get('candidate_limit',24),probe.get('offset',0)) if probe is not None else searcher.feasibility(req) if req.get('_feasibility_only') else searcher.search(req)
    import os,hmac,hashlib
    channel=os.environ.pop('MHF_PROOF_CHANNEL_KEY',None)
    if channel and result.get('certificate'):
        result['proof_auth']=hmac.new(bytes.fromhex(channel),json.dumps(result['certificate'],sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()
    output=json.dumps(result,ensure_ascii=False,indent=2)
    if a.out: a.out.write_text(output,encoding='utf-8')
    else: print(output)


if __name__=='__main__': main()
