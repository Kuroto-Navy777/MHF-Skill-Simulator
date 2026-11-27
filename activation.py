"""One contract for confirmed activation; raw totals never stand in for activation."""


def attained(report):
    values={}
    for s in report.get('skills',[]):
        if s['status'] in ('active','overlap') and s.get('threshold') is not None:
            values[s['id']]=s['threshold']
    for s in report.get('automatic',[]):
        if s.get('effective',True):
            values[s['id']]=max(values.get(s['id'],0),s.get('threshold',0))
    for s in report.get('zenith',[]):
        if s['has_base_skill'] is not False and s.get('level',0)>0:
            values[s['id']]=s['level']
    return values


def achieved(report,sid,pt):
    # Recompute from the independent report: cached or caller supplied index fields
    # must never override overflow, wrong-weapon or missing Zenith prerequisites.
    value=attained(report).get(sid,0)
    return value<=pt if pt<0 else value>=pt
