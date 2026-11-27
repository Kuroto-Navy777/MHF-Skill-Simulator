"""Optional, signed, rights-gated downloads. Local generation always remains usable."""
import json,os,sys,threading,urllib.error,uuid
from pathlib import Path
from runtime_paths import app_root
from data_packages import verify_catalog,download_selected,import_weapon_builds
from update_core import fetch_asset

class DataDistribution:
 def __init__(self,candidates,version,root=None):
  self.candidates=candidates;self.version=version;self.root=Path(root or app_root());self.catalog=None;self.jobs={};self.lock=threading.Lock()
 def public_key(self):
  path=(Path(sys._MEIPASS)/'update_public_key.bin') if getattr(sys,'frozen',False) else self.root/'update_public_key.bin'
  key=path.read_bytes()
  if len(key)!=32:raise ValueError('invalid pinned public key')
  return key
 def check(self):
  import tempfile
  with tempfile.TemporaryDirectory(prefix='mhf-catalog-') as folder:
   folder=Path(folder);raw=folder/'catalog.json';sig=folder/'catalog.sig'
   try:
    fetch_asset(self.version,'MHF_DataCatalog_140.json',raw,16*1024**2)
    fetch_asset(self.version,'MHF_DataCatalog_140.json.sig',sig,64)
   except urllib.error.HTTPError as exc:
    if exc.code==404:return {'status':'unavailable','local_generation':True,'rights_status':'not_verified','reason':'No verified derived-data catalogue is published.'}
    raise
   self.catalog=verify_catalog(raw.read_bytes(),sig.read_bytes(),self.public_key(),self.candidates.path)
  packages={key:{'download_bytes':sum(c['size'] for f in p['files'].values() for c in f['chunks']),'expanded_bytes':sum(f['raw_size'] for f in p['files'].values())} for key,p in self.catalog['packages'].items()}
  return {'status':'available','data_version':self.catalog['data_version'],'packages':packages,'all_weapons_download_bytes':self.catalog.get('all_weapons_download_bytes'),'rights':self.catalog['rights']}
 def start(self,weapon_type):
  if self.catalog is None:raise ValueError('No verified data catalogue; generate this weapon locally instead.')
  key=uuid.uuid4().hex
  with self.lock:
   if any(j['state'] in ('downloading','installing') for j in self.jobs.values()):raise ValueError('a data install is already running')
   self.jobs[key]={'state':'downloading','weapon_type':weapon_type}
  def work():
   try:
    with self.candidates.lock:
     self.candidates._ready();archive=self.candidates.archive
     if archive is None:raise ValueError('persistent data directory unavailable')
     identity=self.candidates.identity;parent=archive.path.parent;common_ready=archive.open_facts() is not None
    result=download_selected(self.catalog,weapon_type,parent/'data-chunks',parent/('data-'+str(self.catalog['data_version']).replace('/','_').replace('\\','_')),fetch_asset,self.candidates.path,include_common=not common_ready)
    with self.lock:self.jobs[key]['state']='installing'
    with self.candidates.lock:
     if self.candidates.fingerprint()!=identity:raise ValueError('source DB changed during download')
     if not common_ready:
      self.candidates.index_cancel.set()
      if self.candidates.index_thread:self.candidates.index_thread.join(3)
      archive.adopt_signed_facts(result['files']['common/facts.sqlite'],result['files']['common/vectors.csr'],self.catalog['source_sha256'])
     accepted=import_weapon_builds(archive,result['files'][weapon_type+'/builds.json'],self.candidates.searcher)
    with self.lock:self.jobs[key].update(state='done',result={**result,**accepted,'common_used_locally':common_ready})
   except Exception as exc:
    with self.lock:self.jobs[key].update(state='error',reason=str(exc))
  threading.Thread(target=work,name='MHF optional data download',daemon=True).start();return {'id':key}
 def status(self,key):
  with self.lock:
   if key not in self.jobs:raise KeyError(key)
   return dict(self.jobs[key])
