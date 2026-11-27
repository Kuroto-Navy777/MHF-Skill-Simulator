"""Revalidate reusable builds against every current hard search condition."""
from collections import Counter
from armor_levels import endpoint
from defense import satisfies
from external import normalize
from skill_engine import PARTS,WEAPON_SECRET
from bounty import rules,item_allowed,banned_skill


def validate(searcher,req,build):
    s=searcher;e=s.e; reasons=[]
    job='ガンナー' if req['weapon_type'] in ('HBG','LBG','Bow') else '剣士'
    def require(condition,reason):
        if not condition: reasons.append(reason)
    def eid(key,kind): return e.equipment(key,kind)['id']
    try:
        require(build.get('weapon_type')==req['weapon_type'] and build.get('sex','男')==req.get('sex','男') and build.get('job',job)==job,'weapon/job/sex')
        for key in ('g_poogie','premium_poogie_clothes'):
            require(bool(build.get(key))==bool(req.get(key)),key)
        require(normalize(build.get('external'))==normalize(req.get('external')),'external effects')
        require(set(build.get('armor',{}))==set(PARTS),'five armor pieces')
        require(not any(all(build['armor'][p]['item']==combination.get(p) for p in PARTS) for combination in req.get('_excluded_armor_sets',[])),'discovery exclusion')
        if reasons: return None,reasons
        br=rules(req['bounty']) if req.get('bounty') else None
        excluded=set(req.get('exclude',[]));classes=set(req.get('exclude_classes',[]))
        def allowed(item):
            r=s.items[item]
            return (item_allowed(r,br) and not excluded.intersection((item,r['ja'],r['en']))
                    and r['class_code'] not in classes|{'(未)','(不)'} and r['job'] in (None,'共',job)
                    and r['sex'] in (None,'共',req.get('sex','男')) and r['group_name']!='SP'
                    and all(t in ('Ｇ級効果','スキル強化','スキル枠拡張','スキル枠消費なし','スキル発動') for t,v in s.abilities.get(item,[])))
        fixed_jewels=Counter();actual_jewels=Counter()
        for p in PARTS:
            a=build['armor'][p];item=eid(a['item'],p);cfg=req.get('armor',{}).get(p,{})
            require(allowed(item),'excluded armor: '+p)
            if cfg: require(item==eid(cfg['item'],p),'fixed armor: '+p)
            choices=req.get('armor_candidates',{}).get(p)
            if choices is not None: require(item in {eid(x,p) for x in choices},'armor pool: '+p)
            if not cfg and (choices is None or req.get('inventory_g_filter')) and req.get('g_armor_only',True):
                require(any(t=='Ｇ級効果' for t,v in s.abilities.get(item,[])),'G armor filter: '+p)
            level=cfg.get('level') or endpoint(s.levels[item],req.get('armor_level_mode','max'))[0]
            require(a['level']==level,'armor level: '+p)
            fixed=Counter(eid(x,'jewel') for x in cfg.get('jewels',[]))
            actual=Counter(eid(x,'jewel') for x in a.get('jewels',[]))
            require(fixed<=actual,'fixed jewels: '+p);fixed_jewels.update(fixed);actual_jewels.update(actual)
        w=build.get('weapon',{});expected=req.get('weapon',{})
        if req.get('auto_weapon'):
            require('page' in w,'physical auto weapon')
        elif not expected:
            require(not w,'unexpected weapon')
        else:
            for key in ('virtual','page','anchor','template','slots','slot_mode'):
                require(w.get(key)==expected.get(key),'weapon selector: '+key)
        require(w.get('sigils',0)==expected.get('sigils',0),'sigil reservation')
        if 'page' in w:
            row=s.db.execute('SELECT v.*,w.name_ja FROM ferias_variants v JOIN ferias_weapons w USING(weapon_type,upstream_id) WHERE v.weapon_type=? AND v.page=? AND v.anchor=?',
                             (req['weapon_type'],w['page'],w['anchor'])).fetchone()
            require(s.weapon_permitted(row,req),'weapon restrictions')
        if 'template' in w: require(allowed(eid(w['template'],'weapon_template')),'weapon template restrictions')
        fixed=Counter(eid(x,'jewel') for x in expected.get('jewels',[]))
        actual=Counter(eid(x,'jewel') for x in w.get('jewels',[]))
        require(fixed<=actual,'fixed weapon jewels');fixed_jewels.update(fixed);actual_jewels.update(actual)
        actual_cuffs=Counter(eid(x,'cuff') for x in build.get('cuffs',[]))
        if 'cuffs' in req:
            require(actual_cuffs==Counter(eid(x,'cuff') for x in req['cuffs']),'fixed cuffs')
        for kind,counts,fixed,allow,limit in [
            ('jewel',actual_jewels,fixed_jewels,req.get('jewel_candidates'),req.get('jewel_limits',{})),
            ('cuff',actual_cuffs,actual_cuffs if 'cuffs' in req else Counter(),req.get('cuff_candidates'),req.get('cuff_limits',{}))]:
            for item in counts: require(allowed(item),'excluded '+kind)
            if allow is not None:
                allowed_ids={eid(x,kind) for x in allow}
                require(all(item in allowed_ids for item in counts-fixed),'candidate '+kind+' pool')
            for key,n in limit.items(): require(counts[eid(key,kind)]<=n,'owned '+kind+' limit')
        report=e.evaluate(build)
        require(report['valid'],'equipment validation')
        require(satisfies(report,req),'stats')
        for sid,pt in s.requirements(req['required']).items(): require(s.achieved(report,sid,pt),'required '+sid)
        require(not s.forbidden_hit(report,s.conflicts(req)),'forbidden skill')
        if br:
            require(not any(banned_skill(x['ja'],br,req['weapon_type'],WEAPON_SECRET.values()) and x['status'] in ('active','overlap') for x in report['skills']),'bounty skill')
            require(not any(banned_skill(s.e.skills[x['id']]['ja'],br,req['weapon_type'],WEAPON_SECRET.values()) for x in report['automatic']),'bounty automatic')
        return (report if not reasons else None),reasons
    except (ValueError,KeyError,TypeError,IndexError) as exc:
        return None,['invalid cached build: '+type(exc).__name__]
