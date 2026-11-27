"""Low-priority, idle-only feasibility work; persistent work state belongs to SearchArchive."""
import copy,ctypes,os,threading,time

class LoadSampler:
 def __init__(self):self.previous=None
 def load(self):
  if os.name!='nt':
   try:return min(1,os.getloadavg()[0]/max(1,os.cpu_count() or 1))
   except (AttributeError,OSError):return 0
  idle,kernel,user=(ctypes.c_ulonglong() for _ in range(3))
  if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle),ctypes.byref(kernel),ctypes.byref(user)):return 1
  now=(idle.value,kernel.value+user.value);old=self.previous;self.previous=now
  return max(0,min(1,1-(now[0]-old[0])/max(1,now[1]-old[1]))) if old else 0

class IdlePrecomputer:
 def __init__(self,candidates,launch,status,cancel):
  self.candidates=candidates;self.launch=launch;self.status=status;self.cancel=cancel
  self.lock=threading.Lock();self.context=None;self.stop=threading.Event();self.thread=None;self.active=None;self.last_finish=0;self.loads=LoadSampler();self.phase='disabled'
 def activity(self,request,targets,idle_seconds,enabled=True):
  with self.lock:self.context={'request':copy.deepcopy(request),'targets':copy.deepcopy(targets),'last_action':time.monotonic()-max(0,min(3600,float(idle_seconds))),'seen':time.monotonic(),'enabled':bool(enabled)}
  if self.thread is None:
   self.thread=threading.Thread(target=self.loop,name='MHF index idle',daemon=True);self.thread.start()
  return {'phase':self.phase}
 def loop(self):
  while not self.stop.wait(.5):
   try:
    with self.lock:context=copy.deepcopy(self.context)
    load=self.loads.load();now=time.monotonic()
    if self.active:
     if not context or not context['enabled'] or now-context['last_action']<3:
      try:self.cancel(self.active['job'])
      except Exception:pass
      self.candidates.finish_idle(self.active['task'],'unknown');self.active=None;self.last_finish=now;self.phase='paused';continue
     state=self.status(self.active['job'])
     if state['status']!='running':
      result=state.get('result',{});outcome='confirmed' if result.get('results') else 'proven_infeasible' if result.get('status')=='proven_infeasible' else 'data_incomplete' if result.get('status')=='data_incomplete' else 'unknown'
      self.candidates.finish_idle(self.active['task'],outcome);self.active=None;self.last_finish=now;self.phase=outcome
     continue
    if not context or not context['enabled'] or now-context['seen']>120 or now-context['last_action']<3 or now-self.last_finish<8 or load>.4:
     self.phase='waiting_for_idle';continue
    if self.candidates.index_status()['state']!='ready':self.phase='preparing';continue
    task=self.candidates.plan_idle(context['request'],context['targets'])
    if task is None:self.phase='known_or_cooling_down';continue
    req=task['request'];req.update(_feasibility_only=True,_index_job=True,_precompute_task=task['id'],seconds=min(2,float(req.get('seconds',2))),limit=1,live_preview=True)
    try:job=self.launch(req)
    except Exception:
     self.candidates.finish_idle(task['id'],'unknown');self.last_finish=now;continue
    self.active={'job':job['id'],'task':task['id']};self.phase='computing_unknown'
   except (OSError,ValueError,KeyError,TypeError):self.phase='waiting_for_valid_context'
   except Exception:self.phase='background_error'
 def close(self):
  self.stop.set()
  if self.thread:self.thread.join(3)
  if self.active:
   try:self.cancel(self.active['job'])
   except Exception:pass
   self.candidates.finish_idle(self.active['task'],'unknown');self.active=None
