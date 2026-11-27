"""Private data packs: common facts, weapon-specific builds, content-addressed deltas.

No source or derived game DB is distributable merely because export succeeds.
The downloader requires a signed catalogue and independently recorded rights.
"""
import hashlib,json,lzma,os,shutil,sqlite3,tempfile,zlib
from pathlib import Path
from calculation_identity import SCHEMA_VERSION,calculation_identity
from search_archive import canonical
MAX_DOWNLOAD=5*1024**3
PREFERRED_DOWNLOAD=1024**3
MAX_CHUNK=2*1024**2
WEAPONS={'MS','SnS','DB','GS','LS','Hammer','HH','Lance','GL','SA','Tonfas','HBG','LBG','Bow'}

def file_hash(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024**2),b''):h.update(block)
 return h.hexdigest()

def compress(data,codec):
 if codec=='lzma2':return lzma.compress(data,format=lzma.FORMAT_XZ,preset=6)
 if codec=='zlib':return zlib.compress(data,9)
 if codec=='zstd':
  import zstandard as zstd
  return zstd.ZstdCompressor(level=9).compress(data)
 raise ValueError('unknown lossless codec')

def decompress(data,codec,size):
 if not 0<=size<=MAX_CHUNK:raise ValueError('expanded chunk size exceeds limit')
 if codec=='lzma2':
  d=lzma.LZMADecompressor(memlimit=64*1024**2);raw=d.decompress(data,max_length=size+1)
  if not d.eof or d.unused_data:raise ValueError('incomplete or concatenated compressed chunk')
 elif codec=='zlib':
  d=zlib.decompressobj();raw=d.decompress(data,size+1)
  if not d.eof or d.unconsumed_tail or d.unused_data:raise ValueError('invalid compressed chunk')
 elif codec=='zstd':
  import zstandard as zstd
  parameters=zstd.get_frame_parameters(data)
  if parameters.content_size!=size or parameters.window_size>64*1024**2:raise ValueError('unsafe or unknown Zstd frame size')
  raw=zstd.ZstdDecompressor().decompress(data,max_output_size=size,allow_extra_data=False)
 else:raise ValueError('unknown codec')
 if len(raw)!=size:raise ValueError('expanded chunk length mismatch')
 return raw

def add_file(path,out,codec,release_version,chunk_size=1024**2):
 if not 1024<=chunk_size<=MAX_CHUNK:raise ValueError('invalid chunk size')
 path=Path(path);out=Path(out);out.mkdir(parents=True,exist_ok=True);chunks=[]
 with path.open('rb') as f:
  while True:
   raw=f.read(chunk_size)
   if not raw:break
   blob=compress(raw,codec);digest=hashlib.sha256(blob).hexdigest();name='MHF_Data_'+digest+'.mhfchunk';target=out/name
   if not target.exists():target.write_bytes(blob)
   chunks.append({'asset':name,'release':release_version,'codec':codec,'sha256':digest,'size':len(blob),'raw_sha256':hashlib.sha256(raw).hexdigest(),'raw_size':len(raw)})
 return {'sha256':file_hash(path),'raw_size':path.stat().st_size,'chunks':chunks}

def export_packages(archive,out,release_version='1.4.0',data_version='1',codec='lzma2',rights=None,chunk_size=1024**2):
 from release_check import version_key
 version_key(release_version);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 if archive.open_facts() is None:raise ValueError('prepare the local facts index first')
 catalog={'schema':SCHEMA_VERSION,'data_version':str(data_version),'application_release':release_version,'calculation':archive.calculation,
  'source_sha256':file_hash(archive.source),'rights':rights or {'status':'unverified','evidence':None},'packages':{}}
 # Original SQLite is checkpointed/read-only; copying never modifies the source.
 catalog['packages']['common']={'role':'common','files':{name:add_file(path,out,codec,release_version,chunk_size) for name,path in [('facts.sqlite',archive.facts_path),('vectors.csr',archive.facts_path.with_suffix('.csr'))]}}
 with tempfile.TemporaryDirectory(prefix='mhf-export-') as folder:
  for wt in sorted(WEAPONS):
   data={'weapon_type':wt,'scopes':[]}
   for row in archive.db.execute('SELECT request FROM scope WHERE exportable=1'):
    req=json.loads(row[0])
    if req.get('weapon_type')!=wt:continue
    if any(k in req for k in ('inventory','owned_weapons')):raise ValueError('personal inventory scopes cannot be exported')
    idx=archive._index(req);builds=[]
    for r in idx.rows:
     hit=archive._hit(r)
     if hit:builds.append(hit['build'])
    data['scopes'].append({'request':req,'builds':builds,'proofs':[]})
   path=Path(folder)/(wt+'.json');path.write_text(canonical(data),encoding='utf-8')
   catalog['packages'][wt]={'role':'weapon','weapon_type':wt,'files':{'builds.json':add_file(path,out,codec,release_version,chunk_size)}}
 unique={c['sha256']:c for p in catalog['packages'].values() for f in p['files'].values() for c in f['chunks']}
 catalog['all_weapons_download_bytes']=sum(c['size'] for c in unique.values());catalog['all_weapons_expanded_bytes']=sum(f['raw_size'] for p in catalog['packages'].values() for f in p['files'].values())
 if catalog['all_weapons_download_bytes']>MAX_DOWNLOAD:raise ValueError('all-weapon package set exceeds 5 GiB; split/recompress without discarding builds')
 (out/'MHF_DataCatalog_140.json').write_text(canonical(catalog),encoding='utf-8');return catalog

def validate_catalog(catalog,source=None,require_rights=True):
 from release_check import version_key
 if catalog.get('schema')!=SCHEMA_VERSION or catalog.get('calculation')!=calculation_identity():raise ValueError('incompatible calculation data version')
 rights=catalog.get('rights',{})
 if require_rights and (rights.get('status')!='verified' or not isinstance(rights.get('evidence'),str) or not rights['evidence'].startswith('https://')):raise ValueError('redistribution rights are not verified; generate locally')
 if source is not None and file_hash(source)!=catalog.get('source_sha256'):raise ValueError('source DB differs from package basis')
 packages=catalog.get('packages',{})
 if 'common' not in packages or any(k!='common' and k not in WEAPONS for k in packages):raise ValueError('invalid package selection')
 chunks={};expanded=0
 for key,p in packages.items():
  if p.get('role')!=('common' if key=='common' else 'weapon'):raise ValueError('package role mismatch')
  files=p.get('files',{})
  if set(files)!=({'facts.sqlite','vectors.csr'} if key=='common' else {'builds.json'}):raise ValueError('unexpected package file')
  for filename,f in files.items():
   if type(f.get('raw_size')) is not int or f['raw_size']<0:raise ValueError('invalid expanded file size')
   size=0
   for c in f.get('chunks',[]):
    digest=c.get('sha256','');raw_digest=c.get('raw_sha256','')
    if not all(isinstance(x,str) and len(x)==64 and set(x)<=set('0123456789abcdef') for x in (digest,raw_digest)):raise ValueError('invalid chunk digest')
    if c.get('asset')!='MHF_Data_'+digest+'.mhfchunk':raise ValueError('invalid chunk asset name')
    if type(c.get('size')) is not int or not 0<c['size']<=MAX_CHUNK+65536 or type(c.get('raw_size')) is not int or not 0<c['raw_size']<=MAX_CHUNK:raise ValueError('chunk size exceeds limits')
    if c.get('codec') not in ('lzma2','zstd','zlib'):raise ValueError('invalid codec')
    version_key(c['release']);size+=c['raw_size']
    if digest in chunks and chunks[digest]!=c:raise ValueError('inconsistent repeated chunk')
    chunks[digest]=c
   if size!=f['raw_size']:raise ValueError('file chunk lengths differ')
   expanded+=size
 if sum(c['size'] for c in chunks.values())>MAX_DOWNLOAD:raise ValueError('download catalogue exceeds 5 GiB')
 if expanded>64*1024**3:raise ValueError('expanded catalogue exceeds safety limit')
 return chunks

def verify_catalog(raw,signature,public_key,source=None):
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
 if len(raw)>16*1024**2 or len(signature)!=64 or len(public_key)!=32:raise ValueError('invalid signed catalogue')
 Ed25519PublicKey.from_public_bytes(public_key).verify(signature,raw);catalog=json.loads(raw);validate_catalog(catalog,source);return catalog

def download_selected(catalog,weapon_type,cache,out,fetch,source=None,require_rights=True,include_common=True):
 validate_catalog(catalog,source,require_rights)
 if weapon_type not in WEAPONS or weapon_type not in catalog['packages']:raise ValueError('weapon data unavailable')
 cache=Path(cache);out=Path(out);cache.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
 selected={k:catalog['packages'][k] for k in (('common',weapon_type) if include_common else (weapon_type,))}
 required={c['sha256']:c for p in selected.values() for f in p['files'].values() for c in f['chunks']}
 expanded=sum(f['raw_size'] for p in selected.values() for f in p['files'].values())
 if shutil.disk_usage(out).free<expanded+128*1024**2:raise ValueError('not enough local disk space')
 downloaded=reused=0
 for digest,c in required.items():
  path=cache/(digest+'.chunk')
  if path.is_file() and path.stat().st_size==c['size'] and file_hash(path)==digest:reused+=c['size'];continue
  tmp=cache/(digest+'.download')
  try:
   if tmp.exists():tmp.unlink()
   fetch(c['release'],c['asset'],tmp,c['size'],{'size':c['size'],'sha256':digest})
   if tmp.stat().st_size!=c['size'] or file_hash(tmp)!=digest:raise ValueError('downloaded chunk checksum differs')
   os.replace(tmp,path);downloaded+=c['size']
  finally:
   if tmp.exists():tmp.unlink()
 files={}
 for package,p in selected.items():
  for name,info in p['files'].items():
   target=out/(package+'-'+name);tmp=target.with_suffix(target.suffix+'.assembling')
   if not (target.is_file() and file_hash(target)==info['sha256']):
    try:
     with tmp.open('wb') as f:
      for c in info['chunks']:
       raw=decompress((cache/(c['sha256']+'.chunk')).read_bytes(),c['codec'],c['raw_size'])
       if hashlib.sha256(raw).hexdigest()!=c['raw_sha256']:raise ValueError('expanded chunk digest differs')
       f.write(raw)
     if tmp.stat().st_size!=info['raw_size'] or file_hash(tmp)!=info['sha256']:raise ValueError('assembled package digest differs')
     os.replace(tmp,target)
    finally:
     if tmp.exists():tmp.unlink()
   files[package+'/'+name]=str(target)
 return {'downloaded_bytes':downloaded,'reused_bytes':reused,'selected_download_bytes':sum(c['size'] for c in required.values()),'expanded_bytes':expanded,'files':files}

def import_weapon_builds(archive,path,reader):
 from candidate_validation import validate
 data=json.loads(Path(path).read_text(encoding='utf-8'));accepted=rejected=0
 if data.get('weapon_type') not in WEAPONS:raise ValueError('invalid weapon build pack')
 for group in data.get('scopes',[]):
  req=group['request']
  if req.get('weapon_type')!=data['weapon_type']:raise ValueError('mixed weapon pack')
  prepared=reader.prepare_request(req);hits=[]
  for build in group.get('builds',[]):
   report,reasons=validate(reader,prepared,build)
   if report:hits.append({'build':build,'evaluation':report});accepted+=1
   else:rejected+=1
  archive.ingest(req,hits,exportable=True)
  # Foreign MILP statements are queued for local verification, never trusted as
  # red statuses merely because an equipment pack contained a claimed proof.
  if group.get('proofs'):archive.enqueue(req,[None])
 return {'accepted':accepted,'rejected':rejected}
