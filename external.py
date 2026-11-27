"""Optional ZZ-baseline food, Road and sigil bonuses. No Rain overrides."""
ELEMENTS=('Fire','Water','Thunder','Ice','Dragon')
ROAD_SINGLE=(0,10,15,25)
ROAD_ALL=(0,5,10,15)
ROAD_DEF=(0,30,50,80,110,150)
ROAD_ATK=(0,10,20,30,50,70)
# ZZ reference: https://w.atwiki.jp/giurasu/pages/1464.html
# Utility meal labels are mapped to direct automatic skill tiers by the evaluator.
MEALS={
    'brothers':('いたわり+1','いたわり+2','いたわり+3'),
    'wide':('広域化+1','広域化+2','広域化+3'),
    'medicine':('体力+30','広域化+3','薬仙人'),
    'encourage':('体力+30','激励+1','激励+2'),
    'support':('体力+30','絆','支援'),
    'protection':('体力+30','豪放+2','豪放+3'),
    'guts':('体力+30','逆鱗','ブチギレ'),
    'heroics':('体力+20','火事場力+1','火事場力+2'),
    'paralysis':('体力+10','麻痺半減','麻痺無効'),
    'sleep':('体力+10','睡眠半減','睡眠無効'),
    'poison':('体力+10','毒半減','毒無効'),
    'stun':('体力+10','気絶確率半減','気絶無効'),
}
ROAD_COSTS={'attack':(0,15,25,25,35,35),'defense':(0,5,5,5,10,10),
    **{k:(0,15,20,30) for k in ('all',*ELEMENTS)},
    'advance':(0,20,30,40),'last_stand':(0,50,70),'revival':(0,60),
    'points':(0,10,15,25),'initial_gm':(0,30,50)}
ADVANCE=((0,0,0,0,0,0),(0,20,30,40,50,60),(0,40,50,60,70,80),(0,60,70,80,90,100))

# Values are explicit user settings; no inventory entry is required.
def normalize(raw=None):
    if raw is None: raw={}
    if not isinstance(raw,dict): raise ValueError('invalid external effects')
    def integer(v,lo,hi):
        if type(v) is not int or not lo<=v<=hi: raise ValueError('invalid external effect value')
        return v
    meal=raw.get('meal','none'); quality=integer(raw.get('quality',0),0,3)
    if meal not in ('none','all',*ELEMENTS,*MEALS): raise ValueError('invalid meal')
    road=raw.get('road',{})
    if not isinstance(road,dict): raise ValueError('invalid Road settings')
    road={k:integer(road.get(k,0),0,len(costs)-1) for k,costs in ROAD_COSTS.items()}
    floor=integer(raw.get('road_floor',1),1,100000)
    sigils=raw.get('sigil',{})
    if not isinstance(sigils,dict): raise ValueError('invalid sigil settings')
    sigils={k:integer(sigils.get(k,0),-999,999) for k in ('attack','element','affinity','defense')}
    return {'meal':meal,'quality':quality,'road':road,'road_floor':floor,'sigil':sigils}

# Meal provides an ordinary resistance skill: same-family effects do not add.
def meal_value(e):
    return ((0,5,10,20) if e['meal']=='all' else (0,10,20,30))[e['quality']] if e['meal'] in ('all',*ELEMENTS) else 0

# Optimistic additive upper bound for solver; exact overlap is checked on replay.
def upper_bonus(e):
    road=e['road']; meal=meal_value(e)
    return {'defense':ROAD_DEF[road['defense']]+e['sigil']['defense'], **{k:ROAD_ALL[road['all']]+ROAD_SINGLE[road[k]]+(meal if e['meal'] in ('all',k) else 0) for k in ELEMENTS}}

# Return separate contributions; higher same-family resistance replaces weaker skill.
def contributions(e, names):
    road=e['road']; meal=meal_value(e); family='各耐性' if e['meal']=='all' else dict(zip(ELEMENTS,'火水雷氷龍')).get(e['meal'],'')+'耐性'
    values=[]
    for n in names:
        if n.startswith(family) and n[len(family):].startswith(('+','-')):
            try: values.append(int(n[len(family):]))
            except ValueError: pass
    # With no corresponding active skill, the food contributes its full value.
    food=max(0,meal-max(values,default=0)) if meal else 0
    return {'defense':ROAD_DEF[road['defense']]+e['sigil']['defense'], **{k:ROAD_ALL[road['all']]+ROAD_SINGLE[road[k]]+(food if e['meal'] in ('all',k) else 0) for k in ELEMENTS}}

# Old official skill costs; check against the player's own unlocked capacity separately.
def road_cost(e):
    r=e['road']; return sum(costs[r.get(k,0)] for k,costs in ROAD_COSTS.items())

# Conditional Road effects use the chosen floor, not the character's actual progress.
def road_special(e):
    r=e['road']; floor=e.get('road_floor',1); last=r['last_stand']
    return {'floor':floor,'advance_attack':ADVANCE[r['advance']][min(5,(floor-1)//5)],
        'last_stand_attack':(0,80,120)[last],'last_stand_affinity':(0,30,50)[last],
        'revival_bonus':r['revival'] if not last else 0,'revival_limit':1 if last else None,
        'points_bonus_percent':(0,10,20,40)[r['points']], 'initial_gm_bonus':(0,1000,3000)[r['initial_gm']]}

# Resolve the selected utility meal label; the evaluator checks it against the skill master.
def meal_reference(e):
    if e['meal'] in MEALS and e['quality']:
        return MEALS[e['meal']][e['quality']-1]
    return None

# Report only the effects we know, not final combat damage or invented element types.
def weapon_delta(e):
    s=e['sigil']; return {'raw_attack':s['attack'],'element_display':s['element']*10,'affinity':s['affinity'],'defense':s['defense'],'road_attack':ROAD_ATK[e['road']['attack']], 'road_special':road_special(e),'meal_reference':meal_reference(e)}

# Estimate only the static weapon plus sigil contribution, not full status attack.
WEAPON_COEFFICIENT={'SnS':1.4,'DB':1.4,'GS':4.8,'LS':4.8,'Hammer':5.2,'HH':5.2,'Lance':2.3,'GL':2.3,'SA':5.4,'Tonfas':1.8,'MS':5.4,'HBG':1.2,'LBG':1.2,'Bow':1.2}
def weapon_preview(e, wt, attack, affinity):
    coeff=WEAPON_COEFFICIENT[wt]; delta=weapon_delta(e)
    return {'base_attack':attack,'base_affinity':affinity,'sigil_attack_estimate':None if attack is None else round(attack+coeff*delta['raw_attack'],1),'sigil_affinity_estimate':None if affinity is None else affinity+delta['affinity'],'coefficient':coeff}
