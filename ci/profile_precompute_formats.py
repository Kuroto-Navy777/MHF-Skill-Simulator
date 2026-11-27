"""Measured representations of actual source vectors and confirmed activation sets."""
import argparse,array,collections,ctypes,itertools,json,lzma,mmap,os,pickle,sqlite3,statistics,struct,subprocess,sys,tempfile,time,tracemalloc,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def retained_bytes(value,seen=None):
 """Python retained heap estimate; excludes process/module allocator overhead."""
 seen=set() if seen is None else seen
 if id(value) in seen:return 0
 seen.add(id(value));size=sys.getsizeof(value)
 if isinstance(value,dict):size+=sum(retained_bytes(k,seen)+retained_bytes(v,seen) for k,v in value.items())
 elif isinstance(value,(list,tuple,set,frozenset)):size+=sum(retained_bytes(v,seen) for v in value)
 return size

def memory():
 if os.name!='nt':return {}
 from ctypes import wintypes
 class C(ctypes.Structure):
  _fields_=[('cb',wintypes.DWORD),('faults',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in ['peak','working','page_peak','page','nonpage_peak','nonpage','pagefile','pagefile_peak','private']]
 v=C();v.cb=ctypes.sizeof(v);k=ctypes.WinDLL('kernel32');k.GetCurrentProcess.restype=wintypes.HANDLE;api=ctypes.WinDLL('psapi');api.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD];api.GetProcessMemoryInfo(k.GetCurrentProcess(),ctypes.byref(v),v.cb)
 return {'working_set_mib':round(v.working/1024**2,3),'peak_working_set_mib':round(v.peak/1024**2,3)}

def codec_measure(source,codec,chunk_size=0):
 import zstandard as zstd
 raw=Path(source).read_bytes();parts=[raw] if not chunk_size else [raw[i:i+chunk_size] for i in range(0,len(raw),chunk_size)]
 enc={'zlib':lambda b:zlib.compress(b,9),'lzma2':lambda b:lzma.compress(b,preset=6),'zstd':lambda b:zstd.ZstdCompressor(level=9).compress(b)}[codec]
 dec={'zlib':zlib.decompress,'lzma2':lzma.decompress,'zstd':zstd.ZstdDecompressor().decompress}[codec]
 start=time.perf_counter();compressed=[enc(b) for b in parts];build=time.perf_counter()-start;start=time.perf_counter()
 for original,blob in zip(parts,compressed):assert dec(blob)==original
 elapsed=time.perf_counter()-start
 return {'codec':codec,'chunk_bytes':chunk_size,'raw_bytes':len(raw),'compressed_bytes':sum(map(len,compressed)),'compression_seconds':round(build,6),'decompression_seconds':round(elapsed,6),**memory()}

class DecisionGraph:
 def __init__(self,family,variables,zdd):
  self.nodes={};self.unique={};self.zdd=zdd;self.variables=variables
  cache={}
  def build(level,fam):
   if not fam:return 0
   if level==variables:return 1
   key=(level,frozenset(fam))
   if key in cache:return cache[key]
   low=frozenset(m for m in fam if not (m>>level)&1);high=frozenset(m^(1<<level) for m in fam if (m>>level)&1)
   lo=build(level+1,low);hi=build(level+1,high)
   if zdd and hi==0:value=lo
   elif not zdd and lo==hi:value=lo
   else:
    node=(level,lo,hi)
    if node not in self.unique:
     ident=len(self.unique)+2;self.unique[node]=ident;self.nodes[ident]=node
    value=self.unique[node]
   cache[key]=value;return value
  self.root=build(0,frozenset(family))
 def count_supersets(self,wanted):
  memo={}
  def walk(node,level):
   key=(node,level)
   if key in memo:return memo[key]
   if node==0:return 0
   if node==1:
    remaining=self.variables-level
    return int((wanted>>level)==0) if self.zdd else 1<<max(0,remaining-(wanted>>level).bit_count())
   variable,lo,hi=self.nodes[node];skipped_mask=((1<<variable)-1)^((1<<level)-1)
   if self.zdd and wanted&skipped_mask:return 0
   factor=1 if self.zdd else 1<<max(0,(variable-level)-(wanted&skipped_mask).bit_count())
   value=walk(hi,variable+1) if wanted&(1<<variable) else walk(lo,variable+1)+walk(hi,variable+1)
   memo[key]=factor*value;return memo[key]
  return walk(self.root,0)

def median_ms(fn,repeats=30):
 vals=[]
 for _ in range(repeats):
  t=time.perf_counter();fn();vals.append((time.perf_counter()-t)*1000)
 return {'median_ms':statistics.median(vals),'p95_ms':sorted(vals)[int((len(vals)-1)*.95)]}

def main():
 p=argparse.ArgumentParser();p.add_argument('--facts',type=Path);p.add_argument('--archive',type=Path);p.add_argument('--out',type=Path);p.add_argument('--codec-child');p.add_argument('--source',type=Path);p.add_argument('--chunk-size',type=int,default=0);a=p.parse_args()
 if a.codec_child:print(json.dumps(codec_measure(a.source,a.codec_child,a.chunk_size)));return
 result={'codecs':{},'representations':{}}
 for path in [a.facts,a.facts.with_suffix('.csr'),a.archive]:
  result['codecs'][path.name]=[]
  for codec in ('zlib','zstd','lzma2'):
   for size in (0,1024**2):
    cmd=[sys.executable,__file__,'--codec-child',codec,'--source',str(path),'--chunk-size',str(size)]
    row=json.loads(subprocess.check_output(cmd));result['codecs'][path.name].append(row);print(path.name,codec,size,row['compressed_bytes'],flush=True)
 facts=sqlite3.connect(a.facts);facts.row_factory=sqlite3.Row;archive=sqlite3.connect(a.archive)
 tiers=[(r[0],r[1]) for r in facts.execute('SELECT s.source_id,t.points FROM tier t JOIN skill s ON s.id=t.skill_id WHERE t.points>0 OR t.name=?',('青魂',))]
 patterns=[json.loads(r[0]) for r in archive.execute('SELECT attained FROM pattern ORDER BY id')]
 family=[]
 for values in patterns:
  bits=0
  for i,(sid,pt) in enumerate(tiers):
   actual=values.get(sid,0)
   if actual<=pt if pt<0 else actual>=pt:bits|=1<<i
  family.append(bits)
 family=sorted(set(family));n=len(family);queries=[0]+[1<<i for i in range(len(tiers))]+[family[i]&family[(i+1)%n] for i in range(min(n,64))]
 start=time.perf_counter();postings=[sum(1<<i for i,mask in enumerate(family) if mask&(1<<j)) for j in range(len(tiers))];build=time.perf_counter()-start
 def lookup(wanted):
  mask=(1<<n)-1
  while wanted:
   low=wanted&-wanted;mask&=postings[low.bit_length()-1];wanted^=low
  return mask.bit_count()
 expected=[lookup(q) for q in queries]
 result['representations']['integer_bitsets']={'build_seconds':build,'retained_object_bytes':retained_bytes(postings),'serialized_bytes':len(pickle.dumps(postings,protocol=5)),**median_ms(lambda:[lookup(q) for q in queries])}
 import pyroaring
 start=time.perf_counter();roar=[pyroaring.BitMap(i for i,mask in enumerate(family) if mask&(1<<j)) for j in range(len(tiers))]
 def roaring_lookup(q):
  mask=pyroaring.BitMap(range(n))
  while q:
   low=q&-q;mask&=roar[low.bit_length()-1];q^=low
  return len(mask)
 assert [roaring_lookup(q) for q in queries]==expected
 result['representations']['roaring']={'build_seconds':time.perf_counter()-start,'retained_object_bytes':retained_bytes(roar),'serialized_bytes':sum(len(r.serialize()) for r in roar),**median_ms(lambda:[roaring_lookup(q) for q in queries])}
 for name,zdd in [('zdd',True),('bdd',False)]:
  start=time.perf_counter();graph=DecisionGraph(family,len(tiers),zdd);build=time.perf_counter()-start
  assert [graph.count_supersets(q) for q in queries]==expected,name
  result['representations'][name]={'build_seconds':build,'retained_object_bytes':retained_bytes([graph.nodes,graph.unique,graph.root]),'nodes':len(graph.nodes),'serialized_bytes':len(pickle.dumps((graph.nodes,graph.root),protocol=5)),**median_ms(lambda:[graph.count_supersets(q) for q in queries],5)}
 from search_precompute import MappedVectors
 ids=[r[0] for r in facts.execute('SELECT DISTINCT entity_id FROM vector LIMIT 512')];mm=MappedVectors(a.facts.with_suffix('.csr'))
 def sql_read():return [[tuple(r) for r in facts.execute('SELECT skill_id,CASE kind WHEN "normal" THEN 1 WHEN "zenith" THEN 2 ELSE 3 END,points FROM vector WHERE entity_id=? ORDER BY skill_id,kind',(eid,))] for eid in ids]
 assert sql_read()==[mm.get(i) for i in ids]
 result['sparse_lookup']={'rows':len(ids),'sqlite':median_ms(sql_read),'mmap':median_ms(lambda:[mm.get(i) for i in ids]),'csr_bytes':a.facts.with_suffix('.csr').stat().st_size};mm.close()
 result['observed_family']={'patterns':n,'skill_tiers':len(tiers),'queries_per_repeat':len(queries),'coverage_note':'Graphs describe only observed activation patterns, not all legal game combinations.'}
 result['versions']={'pyroaring':__import__('importlib.metadata').metadata.version('pyroaring'),'zstandard':__import__('importlib.metadata').metadata.version('zstandard')}
 result['source_sizes']={p.name:p.stat().st_size for p in [a.facts,a.facts.with_suffix('.csr'),a.archive]}
 facts.close();archive.close();a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
