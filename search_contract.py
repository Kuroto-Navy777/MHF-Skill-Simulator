"""Shared hard conditions, actual activation scoring and stable build identities.

This module intentionally has no NumPy/SciPy dependency: candidate filtering and
manual verification do not load a solver or the complete equipment catalogue.
"""
import copy
import json
from collections import Counter
from skill_engine import PARTS,WEAPON_SECRET
from inventory import restrict_inventory
from defense import STATS,ELEMENTS,OBJECTIVES,constraints
from bounty import rules,weapon_allowed,banned_skill
from activation import achieved as report_achieved


class SearchContract:
    # Blue Soul is beneficial despite its negative threshold. Other negative tiers remain reference-only.
    @staticmethod
    def selectable(tier):
        return tier["points"] > 0 or tier["ja"] == "青魂"

    @staticmethod
    def reaches(value, threshold):
        return value <= threshold if threshold < 0 else value >= threshold

    def requirement(self, x):
        name=x['skill']
        if 'points' in x:
            ids=[sid for sid,s in self.e.skills.items() if name in (sid,s['ja'],s['en'])]
            if len(ids)!=1 or type(x['points']) is not int or not any(y['points']==x['points'] and self.selectable(y) for y in self.e.levels[ids[0]]):
                raise ValueError(f'invalid or ambiguous skill/threshold: {x}')
            return ids[0],x['points']
        matches=[(sid,y['points']) for sid,ls in self.e.levels.items() for y in ls if name in (y['ja'],y['en']) and self.selectable(y)]
        if len(matches)!=1: raise ValueError(f'ambiguous/unknown skill level: {x}')
        return matches[0]

    # Resolve point requirements once and retain the largest threshold per skill.
    def requirements(self, entries):
        wanted={}
        for entry in entries:
            sid,pt=self.requirement(entry)
            if sid in wanted and (wanted[sid]<0)!=(pt<0):
                raise ValueError("Opposite skill thresholds conflict / 正負の発動条件が矛盾しています")
            wanted[sid]=min(wanted.get(sid,pt),pt) if pt<0 else max(wanted.get(sid,pt),pt)
        return wanted

    # Score only skills actually active in the independent evaluator.
    def achieved(self, report, sid, pt):
        return report_achieved(report,sid,pt)

    # A forbidden tier means its positive point threshold must not be reached.
    # Keep the lowest selected prohibition per family; higher tiers are also excluded.
    def forbidden_requirements(self, req):
        forbidden = {}
        for entry in req.get('forbidden', []):
            sid, pt = self.requirement(entry)
            if sid in forbidden and (forbidden[sid]<0)!=(pt<0):
                raise ValueError("Opposite prohibitions must be specified separately; currently unsupported")
            forbidden[sid] = max(forbidden.get(sid, pt), pt) if pt<0 else min(forbidden.get(sid, pt), pt)
        return forbidden

    def conflicts(self, req):
        forbidden = self.forbidden_requirements(req)
        if any(sid in forbidden and self.reaches(pt,forbidden[sid]) for sid, pt in self.requirements(req['required']).items()):
            raise ValueError('Required and forbidden skill thresholds conflict / 必須・禁止スキルが矛盾しています')
        return forbidden

    # Automatic skills can bypass ordinary point totals; check the evaluated result as well.
    def forbidden_hit(self, report, forbidden):
        for s in report['skills']:
            if s['id'] in forbidden and self.reaches(s['points'],forbidden[s['id']]): return True
        for s in report['zenith']:
            if s['id'] in forbidden and s['raw_points'] >= forbidden[s['id']]: return True
        for s in report['automatic']:
            if s['id'] in forbidden and any(x['ja'] == s['ja'] and self.reaches(x['points'],forbidden[s['id']]) for x in self.e.levels[s['id']]): return True
        return False

    def optional_requirements(self, req):
        result={}
        for item in req.get('optional',[]):
            sid,pt=self.requirement(item); weight=item.get('weight',1)
            if type(weight) is not int or not 1<=weight<=100: raise ValueError('optional weight must be 1..100')
            key=(sid,pt); result[key]=max(result.get(key,0),weight)
        return result

    def supply_met(self,report,req):
        from activation import supplied_points
        return all(supplied_points(report,sid,req['zenith_sources'][sid])>=pt for sid,pt in self.requirements(req.get('required',[])).items() if sid in req.get('zenith_sources',{}))

    def metrics(self, hit, req):
        r=hit['evaluation']; wanted=self.requirements(req['required']); opt=self.optional_requirements(req)
        actual={s['id']:s['points'] for s in r['skills']}; actual.update({s['id']:s['raw_points'] for s in r['zenith']})
        optional=[{'id':sid,'threshold':pt,'weight':weight,'achieved':self.achieved(r,sid,pt) and (sid not in req.get('zenith_sources',{}) or __import__('activation').supplied_points(r,sid,req['zenith_sources'][sid])>=pt)} for (sid,pt),weight in opt.items()]
        stages=0
        for (sid,pt),weight in opt.items():
            tiers=[x for x in self.e.levels[sid] if self.selectable(x) and (x['points']<0)==(pt<0)]
            stages+=weight*sum(self.achieved(r,sid,x['points']) and (sid not in req.get('zenith_sources',{}) or __import__('activation').supplied_points(r,sid,req['zenith_sources'][sid])>=abs(x['points'])) for x in tiers)/max(1,len(tiers))
        surplus=sum(max(0,(actual.get(sid,0)-pt)*(1 if pt>0 else -1)) for sid,pt in wanted.items())
        active=sum(s['status'] in ('active','overlap') and ((s['threshold'] or 0)>0 or s['level_ja']=='青魂') for s in r['skills'])
        spare=sum(a['capacity']-a['used']-a.get('sigils',0) for a in r['slots']['equipment'] if a.get('mode','decoration') in ('shared','decoration'))
        return {'optional':optional,'optional_score':sum(s['weight'] for s in optional if s['achieved']),
                'optional_count':sum(s['achieved'] for s in optional),'optional_stage_score':stages,
                'active_normal_skills':active,'required_surplus':surplus,'free_jewel_slots':spare,
                'new_jewels':hit['new_jewels'], 'stat_mode':constraints(req)[1], **{('defense' if k=='defense' else 'res_'+k):r['defense_stats'][constraints(req)[1]][k] for k in STATS}, 'resistance_sum':sum(r['defense_stats'][constraints(req)[1]][k] for k in ELEMENTS) if all(r['defense_stats'][constraints(req)[1]][k] is not None for k in ELEMENTS) else None}

    # Sort the returned candidates by the requested objective using evaluated, not relaxed, values.
    def rank(self, hits, req):
        mode=req.get('objective','minimal_jewels')
        for h in hits: h['metrics']=self.metrics(h,req)
        def key(h):
            m=h['metrics']; o=m['optional_score']; a=m['active_normal_skills']; s=m['required_surplus']; j=m['new_jewels']
            return {'minimal_jewels':((-o,j,-a,s) if req.get('optional') else (j,-o,-a,s)), 'optional':(-o,j,-a,s), 'max_skills':(-a,-o,j,s), 'surplus':(s,j,-o,-a), 'defense':(-(m['defense'] if m['defense'] is not None else -100000),j,-o,-a), 'resistance':(-(m['resistance_sum'] if m['resistance_sum'] is not None else -100000),j,-o,-a)}[mode]
        hits.sort(key=lambda h:(key(h),-h['metrics']['optional_count'],-h['metrics']['optional_stage_score'],self.build_key(h['build'])))
        for i,h in enumerate(hits,1): h['rank']=i
        return hits

    def prepare_request(self, req):
        req=copy.deepcopy(req)
        if req.get('sigil_mode') not in (None,'auto','fixed'):raise ValueError('invalid sigil mode')
        mode=req.get('search_mode')
        if mode not in (None,'automatic','fixed','partial'):raise ValueError('invalid search mode')
        if mode=='automatic':
            req['armor']={};req.pop('cuffs',None)
            req.pop('fixed_cuffs',None);req.pop('pinned_jewels',None)
            req['weapon']={k:v for k,v in req.get('weapon',{}).items() if k=='sigils'}
            req['auto_weapon']=True;req['integrated_weapon']=True
            req.setdefault('g_poogie',True);req.setdefault('premium_poogie_clothes',True)
            req.setdefault('g_armor_only',False)
        from partial_build import normalize as normalize_partial
        req=normalize_partial(req,self.e)
        if req.get('sigil_mode')=='auto' and req.get('integrated_weapon') and not req.get('auto_weapon') and req.get('weapon',{}).get('page'):
            selector={k:req['weapon'][k] for k in ('page','anchor')}
            if 'weapon_candidates' in req and selector not in req['weapon_candidates']:raise ValueError('fixed weapon outside allowlist')
            req['weapon_candidates']=[selector];req['auto_weapon']=True
            req['weapon']={k:v for k,v in req['weapon'].items() if k in ('sigils','jewels')}
        sources=req.get('zenith_sources',{})
        if not isinstance(sources,dict):raise ValueError('invalid Zenith supply rules')
        for sid,providers in sources.items():
            if sid not in self.e.skills or not sid.startswith('zenith:') or not isinstance(providers,list) or not providers or any(p not in ('weapon','armor','jewel','cuff') for p in providers):raise ValueError('invalid Zenith supply source: '+str(sid))
        self.conflicts(req)
        req={k:v for k,v in req.items() if k!='_fast_armor_cap'}
        req=restrict_inventory(req,self.items,self.e.equipment)
        # A separate opt-in weapon inventory preserves the existing armor-only filter.
        if 'owned_weapons' in req:
            from weapon_inventory import restrict_weapons
            req=restrict_weapons(req,self.db)
        if req.get('bounty'):
            req=copy.deepcopy(req)
            r=rules(req['bounty'])
            if req['weapon_type'] in r['weapon_types_deny']: raise ValueError('Bounty: weapon type prohibited / 武器種禁止')
            if not req.get('auto_weapon') and not req.get('weapon',{}).get('page'): raise ValueError('Bounty: select physical weapon or auto / 武器固定または自動選択が必要')
            if r['no_sigils'] and req.get('weapon',{}).get('sigils',0): raise ValueError('Bounty: sigils prohibited / シジル禁止')
            if any(banned_skill(self.e.skills[sid]['ja'],r,req['weapon_type'],WEAPON_SECRET.values()) for sid in self.requirements(req['required'])): raise ValueError('Bounty: required skill prohibited / 必須スキル禁止')
            if r['armor_ranks'] is not None: req['g_armor_only']=False
        constraints(req)
        if req.get('objective','minimal_jewels') not in ('minimal_jewels','optional','max_skills','surplus',*OBJECTIVES):
            raise ValueError('unknown objective')
        return req

    # Apply physical weapon filters consistently to fixed and automatically selected weapons.
    def weapon_permitted(self, row, req):
        if row is None: return False
        if 'weapon_candidates' in req and not any(x['page']==row['page'] and x['anchor']==row['anchor'] for x in req['weapon_candidates']): return False
        if req.get('bounty') and not weapon_allowed(row,rules(req['bounty'])): return False
        filters=req.get('weapon_filters',{})
        excluded=set(req.get('exclude',[]))
        if excluded.intersection((row['name_source'],row['name_ja'],f"{row['page']}#{row['anchor']}",str(row['upstream_id']))): return False
        if 'categories' in filters and row['category'] not in filters['categories']: return False
        for key,op in [('min_rarity',lambda a,b:a>=b),('max_rarity',lambda a,b:a<=b)]:
            if key in filters and (row['rarity'] is None or not op(row['rarity'],filters[key])): return False
        return True

    # Placement of identical jewels is irrelevant to the current point-based evaluator.
    def build_key(self, build):
        armor=tuple((p,self.e.equipment(a['item'],p)['id'],a['level']) for p,a in sorted(build['armor'].items()))
        weapon=build.get('weapon',{}); wk=tuple((k,weapon[k]) for k in ('virtual','page','anchor','template','sigils','slots','slot_mode') if k in weapon)
        jewels=Counter(self.e.equipment(j,'jewel')['id'] for a in list(build['armor'].values())+[weapon] for j in a.get('jewels',[]))
        cuffs=Counter(self.e.equipment(c,'cuff')['id'] for c in build.get('cuffs',[]))
        return armor,wk,tuple(sorted(jewels.items())),tuple(sorted(cuffs.items()))
