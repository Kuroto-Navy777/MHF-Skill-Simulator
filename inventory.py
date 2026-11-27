"""Apply owned-only filters to a search without modifying its original request."""
import copy
from collections import Counter

ARMOR = ('head', 'body', 'arm', 'waist', 'leg')


def restrict_inventory(req, items, resolve):
    # All counts are keyed by canonical equipment ID. Unregistered means zero.
    if 'inventory' not in req:
        return req
    req = copy.deepcopy(req)
    counts = req.pop('inventory')
    req['inventory_g_filter'] = True
    if not isinstance(counts, dict) or any(k not in items or items[k]['kind'] not in (*ARMOR, 'jewel', 'cuff') or type(v) is not int or not 0 <= v <= 9999 for k, v in counts.items()):
        raise ValueError('invalid inventory item/count')

    # Intersect any existing allowlist; do not widen user constraints.
    def pool(kind, existing=None):
        owned = {k for k, n in counts.items() if n and items[k]['kind'] == kind}
        if existing is not None:
            owned &= {resolve(k, kind)['id'] for k in existing}
        return sorted(owned)

    allow = req.setdefault('armor_candidates', {})
    for part in ARMOR:
        allow[part] = pool(part, allow.get(part))
        fixed = req.get('armor', {}).get(part)
        if fixed and resolve(fixed['item'], part)['id'] not in allow[part]:
            raise ValueError('fixed armor not owned or excluded: ' + part)
        if not allow[part]:
            raise ValueError('no owned armor: ' + part)
    for kind, key, limits in [('jewel', 'jewel_candidates', 'jewel_limits'), ('cuff', 'cuff_candidates', 'cuff_limits')]:
        req[key] = pool(kind, req.get(key))
        prior = {resolve(k, kind)['id']: v for k, v in req.get(limits, {}).items()}
        if any(type(n) is not int or n < 0 for n in prior.values()):
            raise ValueError('invalid prior inventory limit')
        req[limits] = {k: min(counts[k], prior.get(k, counts[k])) for k in req[key]}
        fixed = req.get('cuffs', []) if kind == 'cuff' else [j for a in [*req.get('armor', {}).values(), req.get('weapon', {})] for j in a.get('jewels', [])]
        used = Counter(resolve(k, kind)['id'] for k in fixed)
        if any(n > req[limits].get(k, 0) for k, n in used.items()):
            raise ValueError('fixed ' + kind + ' exceeds owned quantity')
    return req
