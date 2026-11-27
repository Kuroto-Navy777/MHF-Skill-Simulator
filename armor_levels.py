"""Armor reinforcement endpoints. Skill points are attached to the equipment ID."""

# Sort only actual source levels; do not manufacture Lv7 for one-level armor.
def level_key(level):
    return (int(level[1:]) if level.startswith('L') and level[1:].isdigit() else -1, level)

# Both the solver and evaluator use the same source endpoints with known slot counts.
def endpoint(rows, mode):
    if mode not in ('first', 'max'):
        raise ValueError('invalid armor level mode')
    return (min if mode == 'first' else max)(rows, key=lambda r: level_key(r[0]), default=None)

# Compare the same armor IDs at both endpoints without changing a saved build.
def comparison(parts, stats):
    result={}
    for mode in ('first','max'):
        rows=[]
        for part, name, current, used, levels in parts:
            value=endpoint(levels,mode)
            if value is None:
                rows.append({'part':part,'item':name,'level':None,'defense':None,'slots':None,'used':used,'fits':False})
                continue
            lv,slots,defense=value
            rows.append({'part':part,'item':name,'level':lv,'defense':defense,'slots':slots,'used':used,'fits':used<=slots})
        known=all(r['defense'] is not None for r in rows)
        fits=all(r['fits'] for r in rows)
        base=sum(r['defense'] for r in rows) if known else None
        # The same skills only remain applicable if the decorations still fit.
        bonus=stats['bonus']['defense']; extra=stats['external_bonus']['defense']
        result[mode]={'parts':rows,'base':base,'fits':fits,'adjusted':base+bonus if base is not None and fits else None,'external':base+bonus+extra if base is not None and fits else None,'slots':sum(r['slots'] for r in rows) if all(r['slots'] is not None for r in rows) else None}
    return result
