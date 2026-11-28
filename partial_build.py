"""Partial set editing shares the evaluator and strict search constraints.

Decoration sockets on one item are fungible in the supported point model. Slot
numbers here identify consumed units, not undocumented adjacency restrictions.
"""
import copy
from collections import Counter
from skill_engine import PARTS

def fixed_jewels(req,part):
 cfg=req.get('weapon',{}) if part=='weapon' else req.get('armor',{}).get(part,{})
 return list(cfg.get('jewels',[]))+list(req.get('pinned_jewels',{}).get(part,[]))

def fixed_count(req):return sum(len(fixed_jewels(req,p)) for p in (*PARTS,'weapon'))

def normalize(req,engine):
 if req.get('search_mode')=='partial':req['search_mode']='fixed'
 pins=req.get('pinned_jewels',{})
 if not isinstance(pins,dict) or set(pins)-set((*PARTS,'weapon')):raise ValueError('invalid pinned decoration parts')
 for part,items in pins.items():
  if not isinstance(items,list) or len(items)>3:raise ValueError('invalid pinned decorations')
  pins[part]=[engine.equipment(k,'jewel')['id'] for k in items]
  if sum(engine.equipment(k,'jewel')['slots'] for k in fixed_jewels(req,part))>3:raise ValueError('fixed decorations exceed three slots: '+part)
 cuffs=req.get('fixed_cuffs',[])
 if not isinstance(cuffs,list) or len(cuffs)>2:raise ValueError('invalid partially fixed cuffs')
 if 'fixed_cuffs' in req:req['fixed_cuffs']=[engine.equipment(k,'cuff')['id'] for k in cuffs]
 if 'cuffs' in req and not Counter(req.get('fixed_cuffs',[]))<=Counter(engine.equipment(k,'cuff')['id'] for k in req['cuffs']):raise ValueError('partial cuffs conflict with exact cuffs')
 if pins.get('weapon') and not req.get('auto_weapon') and not req.get('weapon'):raise ValueError('pinned weapon jewels require a weapon or automatic selection')
 return req

def placements(reader,req,build):
 result={}
 for part in (*PARTS,'weapon'):
  a=build.get('weapon',{}) if part=='weapon' else build.get('armor',{}).get(part,{})
  locked=Counter(reader.e.equipment(k,'jewel')['id'] for k in fixed_jewels(req,part));rows=[];offset=0
  for key in a.get('jewels',[]):
   item=reader.e.equipment(key,'jewel');is_fixed=locked[item['id']]>0
   if is_fixed:locked[item['id']]-=1
   rows.append({'item':item['id'],'start':offset,'slots':item['slots'],'fixed':is_fixed});offset+=item['slots']
  if rows:result[part]=rows
 locked=Counter(reader.e.equipment(k,'cuff')['id'] for k in req.get('cuffs',req.get('fixed_cuffs',[])))
 cuff_rows=[]
 for key in build.get('cuffs',[]):
  item=reader.e.equipment(key,'cuff');is_fixed=locked[item['id']]>0
  if is_fixed:locked[item['id']]-=1
  cuff_rows.append({'item':item['id'],'slots':item['slots'],'fixed':is_fixed})
 return {'decorations':result,'cuffs':cuff_rows}

def current(reader,req):
 req=copy.deepcopy(req)
 if req.get('search_mode')=='automatic':
  req['armor']={};req.pop('cuffs',None);req.pop('fixed_cuffs',None);req.pop('pinned_jewels',None);req['weapon']={};req['auto_weapon']=True
 normalize(req,reader.e)
 build={k:copy.deepcopy(req[k]) for k in ('weapon_type','job','sex','g_poogie','premium_poogie_clothes','external','armor') if k in req};build.setdefault('armor',{})
 pending={}
 for part in PARTS:
  if part in build['armor']:build['armor'][part]['jewels']=fixed_jewels(req,part)
  elif req.get('pinned_jewels',{}).get(part):pending[part]=req['pinned_jewels'][part]
 weapon=req.get('weapon',{})
 if weapon.get('page') or weapon.get('virtual') or weapon.get('template'):
  build['weapon']=copy.deepcopy(weapon);build['weapon']['jewels']=fixed_jewels(req,'weapon')
 elif fixed_jewels(req,'weapon'):pending['weapon']=fixed_jewels(req,'weapon')
 build['cuffs']=list(req.get('cuffs',req.get('fixed_cuffs',[])))
 report=reader.e.evaluate(build);wanted=reader.requirements(req.get('required',[]));points={s['id']:s['points'] for s in report['skills']};points.update({s['id']:s['raw_points'] for s in report['zenith']})
 rows=[]
 for sid in sorted(set(points)|set(wanted)):
  pt=points.get(sid,0);target=wanted.get(sid);tier=next((s for s in report['skills'] if s['id']==sid),None)
  if target is None:
   levels=[t['points'] for t in reader.e.levels[sid] if t['points']>0];target=next((p for p in sorted(levels) if p>pt),max(levels,default=0))
  from activation import supplied_points
  source_met=sid not in req.get('zenith_sources',{}) or supplied_points(report,sid,req['zenith_sources'][sid])>=target
  rows.append({'skill':sid,'ja':reader.e.skills[sid]['ja'],'points':pt,'required':target,'missing':max(0,pt-target) if target<0 else max(0,target-pt),'surplus':max(0,target-pt) if target<0 else max(0,pt-target),'satisfied':reader.achieved(report,sid,target) and source_met,'status':('source_not_met' if not source_met else tier['status'] if tier else 'not_reached')})
 slots=[]
 for row in report['slots']['equipment']:
  capacity=row['capacity'];used=row['used'];sigils=row.get('sigils',0)
  slots.append({**row,'free':max(0,capacity-used-sigils) if row.get('mode')!='sigil' else 0})
 return {'build':build,'evaluation':report,'points':rows,'equipment_slots':slots,'unselected_armor':[p for p in PARTS if p not in build['armor']],
  'pending_decorations':pending,'cuff_free':max(0,2-report['slots']['cuff_used']),'cuff_items_free':max(0,2-len(build['cuffs'])),'placement':placements(reader,req,build),'partial':True}
