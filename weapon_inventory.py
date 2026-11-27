"""Validate and intersect a separate owned physical weapon allowlist."""
import copy


def restrict_weapons(req, db):
    req = copy.deepcopy(req)
    entries = req.pop('owned_weapons')
    if not isinstance(entries, list) or len(entries) > 10000:
        raise ValueError('invalid owned weapon list')
    wt = req['weapon_type']
    owned = set()
    # Selectors include type and actual variant, so upgrades are not silently interchangeable.
    for x in entries:
        if not isinstance(x, dict) or any(not isinstance(x.get(k), str) for k in ('weapon_type','page','anchor')):
            raise ValueError('invalid owned weapon selector')
        if x['weapon_type'] != wt:
            continue
        key = (x['page'], x['anchor'])
        if not db.execute('SELECT 1 FROM ferias_variants WHERE weapon_type=? AND page=? AND anchor=?',(wt,*key)).fetchone():
            raise ValueError('unknown owned weapon')
        owned.add(key)
    if 'weapon_candidates' in req:
        owned &= {(x['page'],x['anchor']) for x in req['weapon_candidates']}
    if not owned:
        raise ValueError('no owned weapons of selected type / 選択武器種の所持武器がありません')
    if not req.get('auto_weapon'):
        w = req.get('weapon',{})
        if (w.get('page'),w.get('anchor')) not in owned:
            raise ValueError('fixed weapon is not owned / 固定武器が未登録です')
    req['weapon_candidates'] = [{'page':p,'anchor':a} for p,a in sorted(owned)]
    return req
