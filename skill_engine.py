"""Deterministic skill evaluator for locally imported MHF data (ZZ baseline)."""
import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from ferias_import import validate_slots
from defense import armor_values, evaluate_stats, skill_modifier
from armor_levels import comparison
from external import normalize, road_cost, weapon_preview, meal_reference, meal_value, ELEMENTS

PARTS = ('head', 'body', 'arm', 'waist', 'leg')
WEAPON_SECRET = dict(zip('SnS DB GS LS Hammer HH Lance GL SA Tonfas MS HBG LBG Bow'.split(),
                         '片手剣技 双剣技 大剣技 太刀技 鎚技 狩猟笛技 槍技 銃槍技 剣斧技 穿龍棍技 磁斬鎚技 重銃技 軽銃技 弓技'.split()))

# Read thresholds in both directions: negative levels are not positive activations.
def reached(levels, total):
    if total >= 0:
        return max((x for x in levels if 0 < x['points'] <= total), key=lambda x: x['points'], default=None)
    return min((x for x in levels if total <= x['points'] < 0), key=lambda x: x['points'], default=None)

class Engine:
    def __init__(self, db):
        self.db = db
        self._equipment_cache = {}
        self._contribution_cache = {}
        self._armor_levels_cache = {}
        self._rule_cache = {}
        db.row_factory = sqlite3.Row
        self.skills = {r['id']: dict(r) for r in db.execute('SELECT * FROM skills')}
        self.levels = defaultdict(list)
        self.names = {}
        self.level_names = defaultdict(list)
        for sid, s in self.skills.items():
            self.names[(s['kind'], s['ja'])] = sid
        for r in db.execute('SELECT * FROM skill_levels'):
            x = dict(r)
            self.levels[x['skill_id']].append(x)
            self.level_names[(self.skills[x['skill_id']]['kind'], x['ja'])].append(x)

    def rule_groups(self,level):
        key=(level['skill_id'],level['points'])
        if key not in self._rule_cache:
            self._rule_cache[key]=json.loads(level['rules_json'])['ja']['children']
        return self._rule_cache[key]

    # Resolve known direct XML relations; do not invent effects absent from the data.
    def contained_levels(self, level):
        for group in self.rule_groups(level):
            if group['tag'] == 'ContainedSkills':
                for ch in group['children']:
                    matches = self.level_names[('normal', ch['attributes'].get('Name'))]
                    if len(matches) == 1:
                        yield matches[0]

    # Highest direct utility meal skill, separate from equipment points and Zenith.
    def meal_level(self, ext):
        name=meal_reference(ext)
        value=meal_value(ext)
        if value:
            family='各耐性' if ext['meal']=='all' else dict(zip(ELEMENTS,'火水雷氷龍'))[ext['meal']]+'耐性'
            name=f'{family}+{value}'
        matches = self.level_names.get(('normal', name), [])
        return matches[0] if len(matches) == 1 and matches[0]['points'] > 0 else None

    # Equipment IDs are version-local, and ambiguous localized names are rejected.
    def equipment(self, key, kind):
        # Cache repeated exact lookups within the same immutable-data engine instance.
        cache_key=(kind,key)
        if cache_key in self._equipment_cache:return self._equipment_cache[cache_key]
        if hasattr(self,'_indexed_lookup'):
            ids=self._indexed_lookup.get((kind,key),[])
            if len(ids)!=1: raise ValueError(f'{kind}: expected one equipment for {key!r}, got {len(ids)}')
            return self._indexed_items[ids[0]]
        rows = self.db.execute('SELECT * FROM equipment WHERE kind=? AND (id=? OR ja=? OR en=?)', (kind,key,key,key)).fetchall()
        if len(rows) != 1:
            raise ValueError(f'{kind}: expected one equipment for {key!r}, got {len(rows)}')
        self._equipment_cache[cache_key]=rows[0]
        return rows[0]

    # The evaluator uses a read-only imported database; cache only immutable source rows.
    def contribution_rows(self, eid):
        if eid not in self._contribution_cache:
            if hasattr(self,'_indexed_points'):
                points=tuple(self._indexed_points.get(eid,{}).items()); abilities=tuple(self._indexed_abilities.get(eid,[]))
                self._contribution_cache[eid]=(points,abilities)
                return points,abilities
            points=tuple(self.db.execute('SELECT skill_id,points FROM equipment_skills WHERE equipment_id=?',(eid,)))
            abilities=tuple(self.db.execute('SELECT type_ja,value_ja FROM abilities WHERE equipment_id=?',(eid,)))
            self._contribution_cache[eid]=(points,abilities)
        return self._contribution_cache[eid]

    def evaluate(self, build):
        job, sex, wt = build.get('job','剣士'), build.get('sex','男'), build['weapon_type']
        if wt not in WEAPON_SECRET or job != ('ガンナー' if wt in ('HBG','LBG','Bow') else '剣士') or sex not in ('男','女'):
            raise ValueError('invalid weapon type/job/sex')
        ext=normalize(build.get('external'))
        totals, zenith = Counter(), Counter()
        details = defaultdict(list); zenith_details=defaultdict(list)
        automatic, free = {}, set()
        warnings, errors, allocation = [], [], []
        g_count = 0
        armor_stats = []
        comparison_parts = []
        # Check every individual item's restrictions and retain signed contributions.
        def add(r):
            if r['job'] not in (None,'共',job) or r['sex'] not in (None,'共',sex):
                errors.append(f"incompatible job/sex: {r['ja']}")
            pts, ab = self.contribution_rows(r['id'])
            for p in pts:
                totals[p[0]] += p[1]
                details[p[0]].append({'item_id':r['id'],'ja':r['ja'],'en':r['en'],'points':p[1]})
            for typ,val in ab:
                if typ in ('スキル強化','スキル枠拡張'):
                    matches = self.level_names[('zenith',val)]
                    if len(matches)==1:
                        x=matches[0]; zenith[x['skill_id']] += x['points'];zenith_details[x['skill_id']].append({'item_id':r['id'],'ja':r['ja'],'en':r['en'],'points':x['points']})
                    else: warnings.append(f'unknown zenith ability: {val}')
                elif typ=='スキル発動':
                    matches=self.level_names[('normal',val)]
                    if len(matches)==1:
                        x=matches[0]; sid=x['skill_id']
                        if sid not in automatic or automatic[sid]['points']<x['points']: automatic[sid]=x
                    else: warnings.append(f'unknown automatic ability: {val}')
                elif typ=='スキル枠消費なし':
                    sid=self.names.get(('normal',val))
                    if sid: free.add(sid)
                    else: warnings.append(f'unknown slot exemption: {val}')
                elif typ=='スキルUP': warnings.append('conditional skill rank-up not evaluated')
                elif typ=='天刻印装着可能': warnings.append('tower armor special sockets not evaluated')
                elif typ not in ('Ｇ級効果','ＳＰ装飾品装着可能'): warnings.append(f'unknown ability: {typ}')
            return {a[0] for a in ab}

        def jewels(keys, sp=False):
            used=0
            for key in keys:
                r=self.equipment(key,'jewel'); add(r)
                if (r['group_name']=='SP') != sp: errors.append(f"incompatible SP jewel/socket: {r['ja']}")
                if r['slots'] is None: errors.append(f"unknown jewel size: {r['ja']}")
                else: used+=r['slots']
            return used

        armor=build.get('armor',{})
        if set(armor)-set(PARTS): raise ValueError('unknown armor slot')
        for part in PARTS:
            if part not in armor: continue
            a=armor[part]; r=self.equipment(a['item'],part); ab=add(r)
            g_count+=int('Ｇ級効果' in ab)
            # An explicit level is required; do not assume a fully upgraded armor.
            if r['id'] not in self._armor_levels_cache:
                self._armor_levels_cache[r['id']]=tuple(self.db.execute('SELECT level,slots,defense FROM levels WHERE equipment_id=? AND slots IS NOT NULL',(r['id'],)))
            levels=self._armor_levels_cache[r['id']]
            selected=next((l for l in levels if l[0]==a['level']),None)
            if selected is None: raise ValueError(f"unknown level/slots: {r['ja']} {a['level']}")
            lv=selected[1:]
            armor_stats.append(armor_values(r['metadata'],lv[1]))
            used=jewels(a.get('jewels',[]),'ＳＰ装飾品装着可能' in ab)
            if used>lv[0]: errors.append(f"armor slot overflow: {r['ja']}")
            allocation.append({'part':part,'item':r['ja'],'capacity':lv[0],'used':used})
            comparison_parts.append((part,r['ja'],a['level'],used,levels))
        # A physical weapon variant or a MHSX2G template can be selected, not both.
        weapon=build.get('weapon'); physical_weapon=None
        if weapon:
            keys=weapon.get('jewels',[]); used=jewels(keys); sigils=weapon.get('sigils',0)
            if weapon.get('virtual') is True:
                if any(k in weapon for k in ('template','page','anchor')): raise ValueError('mixed virtual/physical weapon selectors')
                capacity=weapon.get('slots');mode=weapon.get('slot_mode','decoration')
                if type(capacity) is not int or not 0<=capacity<=3 or mode not in ('decoration','shared'):
                    raise ValueError('invalid virtual weapon slots/mode')
                if type(sigils) is not int or not 0<=sigils<=3: raise ValueError('invalid virtual sigil reservation')
                warnings.append('virtual weapon slots: no intrinsic or Zenith weapon effects')
            elif 'template' in weapon:
                if 'page' in weapon or 'anchor' in weapon: raise ValueError('mixed weapon selectors')
                r=self.equipment(weapon['template'],'weapon_template'); add(r)
                mode,capacity=weapon['slot_mode'],weapon['slots']
                warnings.append('weapon template capacity/mode is user supplied')
            else:
                row=self.db.execute('SELECT * FROM ferias_variants WHERE weapon_type=? AND page=? AND anchor=?',(wt,weapon['page'],weapon['anchor'])).fetchone()
                if row is None: raise ValueError('weapon variant not found')
                physical_weapon=row
                mode,capacity=row['slot_mode'],row['slots_reported']
                for p in self.db.execute('SELECT skill_id,points FROM ferias_zenith WHERE weapon_type=? AND page=? AND anchor=?',(wt,weapon['page'],weapon['anchor'])):
                    if p[0] is None or p[1] is None: warnings.append('unmapped weapon zenith skill')
                    else:
                        zenith[p[0]]+=p[1];zenith_details[p[0]].append({'part':'weapon','page':row['page'],'anchor':row['anchor'],'ja':row['name_source'],'en':row['name_source'],'points':p[1]})
                if row['category']=='exotic':
                    x=self.level_names[('normal','早食い')][0]
                    automatic[x['skill_id']]=x
                from weapon_effects import intrinsic_levels
                declared,unmapped=intrinsic_levels(self,row)
                for x in declared:
                    sid=x['skill_id']
                    if sid not in automatic or automatic[sid]['points']<x['points']:automatic[sid]=x
                if unmapped:warnings.append('weapon intrinsic skill not evaluated')
                conflict=self.db.execute('SELECT conflict,pax_match FROM ferias_weapons WHERE weapon_type=? AND upstream_id=?',(wt,row['upstream_id'])).fetchone()
                if conflict and (conflict[0] or conflict[1]=='linked_stats_differ'): warnings.append('weapon source discrepancy; Ferias variant used provisionally')
            check=validate_slots(mode,capacity,used,sigils)
            if not check['valid']: errors.append('weapon: '+check['reason'])
            if not check['complete']: warnings.append('weapon: '+check['reason'])
            allocation.append({'part':'weapon','capacity':capacity,'used':used,'sigils':sigils,'mode':mode})
        cuffs=build.get('cuffs',[]); cslots=0; secret_count=0
        for key in cuffs:
            r=self.equipment(key,'cuff'); ab=add(r)
            cslots+=r['slots']; secret_count+=int('スキル枠消費なし' in ab)
            if r['group_name']=='P' and not build.get('premium_poogie_clothes',False): errors.append('P cuff requires compatible clothes')
            if 'Ｇ' in (r['class_code'] or '') or '辿' in (r['class_code'] or '') or 'スキル枠消費なし' in ab:
                if not build.get('g_poogie',False): errors.append('G/Zenith/secret cuff requires upgraded poogie (baseline)')
        if len(cuffs)>2 or secret_count>1 or cslots>2: errors.append('cuff slot/count overflow')
        # The data's ID is the activation priority, not its display-order No.
        extension=self.names[('zenith','スキル枠拡張')]
        zlevels={sid:reached(self.levels[sid],pt) for sid,pt in zenith.items()}
        slot_cap=10+int(g_count>=3)+int(g_count>=5)+(zlevels.get(extension) or {}).get('points',0)
        candidates={sid:reached(self.levels[sid],pt) for sid,pt in totals.items()}
        selected={}; overflow=[]; used=0; inactive_weapon=[]
        for sid,x in sorted(candidates.items(),key=lambda p:int(p[0].split(':')[1])):
            if x is None: continue
            # Wrong-weapon secret skills are marked explicitly; slot behavior needs in-game comparison.
            name=self.skills[sid]['ja']
            if name in WEAPON_SECRET.values() and name!=WEAPON_SECRET[wt]:
                inactive_weapon.append(sid);warnings.append('other-weapon secret skill slot behavior unverified')
            # Automatic activation does not consume an additional slot itself; whether duplicate point skills remain shown needs validation.
            if sid in automatic and automatic[sid]['points']>=x['points']:
                warnings.append(f"duplicate automatic/point skill: {x['ja']}")
            cost=int(sid not in free)
            if used+cost<=slot_cap:
                selected[sid]=x;used+=cost
            else: overflow.append(sid)
        effective=dict(selected)
        for sid,x in automatic.items():
            if sid not in effective or effective[sid]['points']<x['points']: effective[sid]=x
        for sid in automatic:
            if self.skills[sid]['ja'] in WEAPON_SECRET.values() and self.skills[sid]['ja']!=WEAPON_SECRET[wt]:inactive_weapon.append(sid)
        for sid in inactive_weapon: effective.pop(sid,None)
        # Food can satisfy a direct skill, but does not supply a Zenith prerequisite.
        gear_effective=dict(effective)
        meal=self.meal_level(ext)
        if meal:
            sid=meal['skill_id']
            if sid not in effective or effective[sid]['points']<meal['points']:
                effective[sid]=meal
        # XML relations describe effect overlap, not removal from the skill slot list.
        contained=defaultdict(list); suppressed=defaultdict(list); relations=[]
        for sid,x in effective.items():
            for group in self.rule_groups(x):
                if group['tag'] not in ('ContainedSkills','DeactivateSkills'):
                    warnings.append(f"unknown rule: {group['tag']}"); continue
                for ch in group['children']:
                    target=ch['attributes'].get('Name'); matches=self.level_names[('normal',target)]
                    if len(matches)!=1:
                        warnings.append(f'unresolved skill relation: {target}');continue
                    dest=matches[0]; tid=dest['skill_id']
                    relations.append({'source':x['ja'],'type':group['tag'],'target':target})
                    if group['tag']=='ContainedSkills': contained[tid].append((dest,x['ja']))
                    if tid in effective and tid!=sid and 0<effective[tid]['points']<=dest['points']:
                        suppressed[tid].append(x['ja'])
        # Do not promise exact effect resolution for overlapping composite skills.
        for sid in suppressed:
            if any(r['tag']=='ContainedSkills' for r in self.rule_groups(effective[sid])):
                warnings.append(f"partial composite overlap: {effective[sid]['ja']}")
        # Keep only actual providers for Zenith and flat stats. A suppressed composite
        # may have surviving effects, so preserve its warning but do not assert them.
        gear_contained=defaultdict(list)
        for sid,x in gear_effective.items():
            if sid not in suppressed:
                for dest in self.contained_levels(x): gear_contained[dest['skill_id']].append(dest)
        # Pick one strongest positive value per family; never add duplicate composite effects.
        def flat_names(source, included):
            chosen={sid:x for sid,x in source.items() if sid not in suppressed and skill_modifier(x['ja'])}
            for sid,levels in included.items():
                for x in levels:
                    if not skill_modifier(x['ja']): continue
                    if sid not in chosen or chosen[sid]['points']<x['points']: chosen[sid]=x
            return [x['ja'] for x in chosen.values()]
        stat_names=flat_names(gear_effective,gear_contained)
        result=[]
        for sid,total in sorted(totals.items(),key=lambda p:int(p[0].split(':')[1])):
            x=candidates[sid]; status='not_reached' if x is None else 'overflow' if sid in overflow else 'wrong_weapon' if sid in inactive_weapon else 'overlap' if sid in suppressed else 'active'
            result.append({'id':sid,'ja':self.skills[sid]['ja'],'en':self.skills[sid]['en'],'points':total,'level_ja':x['ja'] if x else None,'level_en':x['en'] if x else None,'threshold':x['points'] if x else None,'status':status,'slot_cost':int(sid in selected and sid not in free),'overlap_by':suppressed.get(sid,[]),'contributions':details[sid]})
        zresult=[]
        for sid,total in sorted(zenith.items()):
            x=zlevels[sid]; target=json.loads(self.skills[sid]['metadata'])['ja'].get('Target'); tid=self.names.get(('normal',target)); has_base=None
            if tid:
                has_base=bool((tid in gear_effective and tid not in suppressed and (gear_effective[tid]['points']>0 or target=='喝')) or gear_contained.get(tid))
            elif target: warnings.append(f'unresolved zenith target: {target}')
            zresult.append({'id':sid,'ja':x['ja'] if x else None,'en':x['en'] if x else None,'raw_points':total,'level':x['points'] if x else 0,'target':target,'has_base_skill':has_base,'contributions':zenith_details[sid]})
        # The three protection skills can be supplied by composite or innate effects.
        protection=[]
        for base,boost,super_name in [('聴覚保護','耳栓強化','超咆哮無効'),('風圧','風圧強化','超風圧無効'),('耐震','耐震強化','超震動無効')]:
            sid=self.names[('normal',base)]; zid=self.names[('zenith',boost)]
            stages=sorted((x for x in self.levels[sid] if x['points']>0),key=lambda x:x['points'])
            available=list(gear_contained.get(sid,[]))
            if sid in gear_effective and sid not in suppressed and gear_effective[sid]['points']>0: available.append(gear_effective[sid])
            current=max((i+1 for i,x in enumerate(stages) if any(a['points']>=x['points'] for a in available)),default=0)
            increase=(zlevels.get(zid) or {}).get('points',0)
            final=min(len(stages)+1,current+increase) if current else 0
            # Meal protection is a separate unboosted stage, even when its tier is higher.
            food_levels=[]
            if meal and meal['skill_id'] not in suppressed:
                food_levels=[x for x in [meal,*self.contained_levels(meal)] if x['skill_id']==sid]
            food_stage=max((i+1 for i,x in enumerate(stages) if any(a['points']>=x['points'] for a in food_levels)),default=0)
            final=max(final,food_stage)
            protection.append({'meal_level':stages[food_stage-1]['ja'] if food_stage else None,'skill':base,'base_level':stages[current-1]['ja'] if current else None,'boost':increase,'effective_level':super_name if final>len(stages) else stages[final-1]['ja'] if final else None,'super_protection':final>len(stages)})
        # The baseline is provisional, even if no configuration-specific warning remains.
        # External effects are optional and never consume ordinary armor skill slots.
        if any(ext['sigil'].values()) and (not weapon or weapon.get('sigils',0)<1): errors.append('Sigil bonuses require reserved weapon slots')
        if road_cost(ext)>130: errors.append('Road cost exceeds ZZ maximum 130')
        stats=evaluate_stats(armor_stats,stat_names,ext)
        stats['armor_levels']=comparison(comparison_parts,stats)
        if physical_weapon is not None:
            stats['weapon_preview']=weapon_preview(ext,wt,physical_weapon['attack'],physical_weapon['affinity'])
        report={'defense_stats':stats,'valid':not errors,'rain_verified':False,'no_known_issues':not warnings and not errors,'fully_verified':False,'configuration_warnings':sorted(set(warnings)),'errors':errors,'slots':{'capacity':slot_cap,'used':used,'g_armor_count':g_count,'cuff_used':cslots,'equipment':allocation},'skills':result,'zenith':zresult,'automatic':[{'id':sid,'ja':x['ja'],'en':x['en'],'source':'equipment','threshold':x['points'],'effective':sid not in suppressed and sid not in inactive_weapon} for sid,x in automatic.items()]+([{'id':meal['skill_id'],'ja':meal['ja'],'en':meal['en'],'source':'meal','threshold':meal['points'],'effective':meal['skill_id'] not in suppressed}] if meal else []),'relations':relations,'protection':protection}
        from activation import attained
        report['attained']=attained(report)
        return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--db',required=True,type=Path);p.add_argument('--build',required=True,type=Path);a=p.parse_args()
    with sqlite3.connect(a.db.resolve().as_uri()+'?mode=ro',uri=True) as db:
        print(json.dumps(Engine(db).evaluate(json.loads(a.build.read_text(encoding='utf-8-sig'))),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
