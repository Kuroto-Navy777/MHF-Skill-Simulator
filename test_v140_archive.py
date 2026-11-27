"""1.4 storage invariants: persistence never substitutes for independent game validation."""
import copy,json,os,sqlite3,tempfile,time,unittest,zlib
from pathlib import Path
from unittest.mock import patch
from search_archive import SearchArchive,build_identity,condition_key
from data_packages import compress,decompress,add_file,download_selected,validate_catalog,verify_catalog


def hit(i=0):
 return {'build':{'weapon_type':'MS','sex':'男','armor':{p:{'item':p+str(i//2),'level':'L1','jewels':['j'+str(i)] if p=='head' else []} for p in ['head','body','arm','waist','leg']},'cuffs':['c'+str(i%2)]},
 'evaluation':{'valid':True,'skills':[{'id':'normal:a','threshold':20 if i%2 else 10,'status':'active','points':20 if i%2 else 10}], 'automatic':[], 'zenith':[], 'defense_stats':{'adjusted':{'defense':100+i}}},'new_jewels':1}

class Archive140UnitTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'source.sqlite';self.source.write_bytes(b'identity fixture, not a game DB');self.path=self.root/'cache.sqlite';self.a=SearchArchive(self.source,self.path);self.q={'weapon_type':'MS','required':[]}
 def tearDown(self):self.a.close();self.temp.cleanup()
 def test_persistence_keeps_more_than_display_and_memory_pool_limits(self):
  hits=[hit(i) for i in range(1200)];self.a.ingest(self.q,hits)
  r=self.a.query(self.q,{},[('normal:a',20)],limit=5);self.assertEqual(r['confirmed_builds'],1200);self.assertEqual(len(r['results']),5);self.assertEqual(r['distinct_armor'],600);self.assertEqual(r['candidate_counts']['normal:a|20'],600)
  self.a.close();self.a=SearchArchive(self.source,self.path);r=self.a.query(self.q,{'normal:a':20});self.assertEqual(r['confirmed_builds'],600)
  self.assertEqual(self.a.query(self.q,{})['confirmed_builds'],1200)
 def test_variants_do_not_merge_weapon_cuff_or_placement_differences(self):
  a=hit(0);b=copy.deepcopy(a);b['build']['weapon']={'page':'main','anchor':'one','sigils':0,'jewels':[]};c=copy.deepcopy(a);c['build']['cuffs']=['another'];d=copy.deepcopy(a);d['build']['armor']['head']['jewels']=[];d['build']['armor']['body']['jewels']=['j0']
  self.a.ingest(self.q,[a,b,c,d]);r=self.a.query(self.q,{});self.assertEqual(r['confirmed_builds'],4);self.assertEqual(r['results'][0]['archive_variant_count'],4)
  armor={p:x['item'] for p,x in a['build']['armor'].items()};self.assertEqual(self.a.variants(self.q,{},armor)['variant_count'],4)
 def test_tampered_payload_pattern_and_proof_are_never_evidence(self):
  self.a.ingest(self.q,[hit()]);self.a.put_proof(self.q,{'normal:b':10},{'kind':'safe_interval','coverage_complete':True})
  self.a.db.execute("UPDATE witness SET payload=?",(b'bad',));self.a.db.execute("UPDATE proof SET certificate='{}'");self.a.db.commit();self.a.indices.clear()
  self.assertEqual(self.a.query(self.q,{})['confirmed_builds'],0);self.assertEqual(self.a.proofs(self.q),[])
  self.a.ingest(self.q,[hit()]);self.assertEqual(self.a.query(self.q,{})['confirmed_builds'],1)
  self.a.db.execute("UPDATE pattern SET attained='{}'");self.a.db.commit();self.a.indices.clear();self.assertEqual(self.a.query(self.q,{})['confirmed_builds'],0)
 def test_model_only_infeasibility_is_not_red(self):
  self.a.put_proof(self.q,{'normal:a':10},{'kind':'full_model_infeasible','coverage_complete':False})
  states=self.a.assess(self.q,{},[('normal:a',20)],{});self.assertEqual(states['normal:a|20']['state'],'unresolved_data')
  self.a.put_proof(self.q,{'normal:a':10},{'kind':'full_model_infeasible','coverage_complete':True})
  self.assertEqual(self.a.assess(self.q,{},[('normal:a',20)],{})['normal:a|20']['state'],'proven_infeasible')
 def test_unknown_attempt_and_idle_cooldown_survive_restart(self):
  self.a.put_attempt(self.q,{},'unknown');self.a.enqueue(self.q,[{'skill':'normal:a','points':10}]);task=self.a.next_work(self.q);self.assertIsNotNone(task);self.a.finish_work(task['id'],'unknown')
  self.a.close();self.a=SearchArchive(self.source,self.path);self.assertIsNone(self.a.next_work(self.q));self.assertGreater(self.a.attempt(self.q,{})['retry_after'],0)
 def test_condition_normalization_does_not_erase_empty_restrictions(self):
  a={'weapon_type':'MS','search_mode':'automatic','armor':{'head':'stale'},'cuffs':['stale'],'weapon':{'page':'stale','sigils':0},'external':{'meal':'none','quality':3,'road_floor':99}}
  b={'weapon_type':'MS','search_mode':'automatic','armor':{},'weapon':{'sigils':0}}
  self.assertEqual(condition_key(a),condition_key(b));self.assertNotEqual(condition_key(b),condition_key({**b,'inventory':{}}));self.assertNotEqual(condition_key(b),condition_key({**b,'weapon_candidates':[]}))
 def test_source_change_invalidates_witnesses_and_proofs(self):
  self.a.ingest(self.q,[hit()]);self.a.close();self.source.write_bytes(b'changed source');self.a=SearchArchive(self.source,self.path);self.assertEqual(self.a.query(self.q,{})['confirmed_builds'],0)
 def test_supply_rules_change_activation_index_without_discarding_builds(self):
  q={**self.q,'zenith_sources':{'zenith:e':['weapon']}};a=hit();a['evaluation']['zenith']=[{'id':'zenith:e','level':2,'has_base_skill':True,'contributions':[{'item_id':'cuff:1','points':2}]}]
  self.a.ingest(q,[a]);r=self.a.query(q,{'zenith:e':1},[('zenith:e',1)]);self.assertEqual(r['confirmed_builds'],0);self.assertEqual(r['reservoir_counts']['confirmed_builds'],1)
 def test_exportable_scope_never_accepts_personal_inventory(self):
  with self.assertRaises(ValueError):self.a.ingest({**self.q,'inventory':{}},[hit()],exportable=True)
 def test_interrupted_work_recovers_after_restart_and_unknown_backs_off(self):
  self.a.enqueue(self.q,[{'skill':'normal:a','points':10}]);work=self.a.next_work(self.q);self.assertIsNotNone(work)
  self.a.close();self.a=SearchArchive(self.source,self.path);work=self.a.next_work(self.q);self.assertIsNotNone(work)
  self.a.finish_work(work['id'],'unknown');self.assertIsNone(self.a.next_work(self.q))

class DataPack140UnitTests(unittest.TestCase):
 def test_lossless_codecs_and_expansion_limits(self):
  raw=(b'point-table: armor jewel cuff weapon\n'*4096)
  codecs=['zlib','lzma2']
  try:import zstandard;codecs.append('zstd')
  except ImportError:pass
  for codec in codecs:
   blob=compress(raw,codec);self.assertEqual(decompress(blob,codec,len(raw)),raw)
   with self.assertRaises(ValueError):decompress(blob,codec,8)
 def catalogue(self,root):
  from calculation_identity import calculation_identity,SCHEMA_VERSION
  contents={};out=root/'assets';out.mkdir()
  for name,text in [('facts',b'A'*6000+b'B'*6000),('csr',b'offsets'*900),('MS',b'magnet-builds'*200),('GS',b'greatsword-builds'*200)]:
   p=root/name;p.write_bytes(text);contents[name]=add_file(p,out,'lzma2','1.4.0',1024)
  catalog={'schema':SCHEMA_VERSION,'calculation':calculation_identity(),'source_sha256':'0'*64,'data_version':'test','application_release':'1.4.0','rights':{'status':'verified','evidence':'https://example.invalid/test-license'},'packages':{'common':{'role':'common','files':{'facts.sqlite':contents['facts'],'vectors.csr':contents['csr']}},'MS':{'role':'weapon','files':{'builds.json':contents['MS']}},'GS':{'role':'weapon','files':{'builds.json':contents['GS']}}}}
  return catalog,out
 def test_selective_download_reuses_chunks_and_keeps_other_weapons_out(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);catalog,assets=self.catalogue(root);calls=[]
   def fetch(v,name,target,limit,expected):calls.append(name);target.write_bytes((assets/name).read_bytes())
   r=download_selected(catalog,'MS',root/'chunks',root/'installed',fetch)
   expected={c['asset'] for k in ('common','MS') for f in catalog['packages'][k]['files'].values() for c in f['chunks']}
   self.assertEqual(set(calls),expected);self.assertNotIn('GS/builds.json',r['files']);self.assertGreater(r['downloaded_bytes'],0)
   calls.clear();r=download_selected(catalog,'MS',root/'chunks',root/'installed',fetch);self.assertFalse(calls);self.assertEqual(r['downloaded_bytes'],0)
   # One append affects only the new tail chunk; all matching old chunks remain.
   old=catalog['packages']['MS']['files']['builds.json'];p=root/'MS';p.write_bytes(p.read_bytes()+b'new build\n');catalog['packages']['MS']['files']['builds.json']=add_file(p,assets,'lzma2','1.4.0',1024)
   calls.clear();r=download_selected(catalog,'MS',root/'chunks',root/'installed',fetch);self.assertGreater(r['reused_bytes'],0);self.assertLess(r['downloaded_bytes'],sum(c['size'] for c in catalog['packages']['MS']['files']['builds.json']['chunks']))
 def test_unverified_rights_and_unsigned_or_tampered_catalogues_fail_closed(self):
  from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
  from cryptography.hazmat.primitives import serialization
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);catalog,assets=self.catalogue(root);catalog['rights']['status']='unverified'
   with self.assertRaises(ValueError):validate_catalog(catalog)
   catalog['rights']['status']='verified';raw=json.dumps(catalog).encode();key=Ed25519PrivateKey.generate();pub=key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
   self.assertEqual(verify_catalog(raw,key.sign(raw),pub)['schema'],140)
   with self.assertRaises(Exception):verify_catalog(raw+b' ',key.sign(raw),pub)
 def test_download_hash_mismatch_never_installs_a_chunk(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);catalog,assets=self.catalogue(root)
   def bad(v,name,target,limit,expected):target.write_bytes(b'corrupt')
   with self.assertRaises(ValueError):download_selected(catalog,'MS',root/'chunks',root/'installed',bad)
   self.assertFalse(list((root/'chunks').glob('*.chunk')))

if __name__=='__main__':unittest.main()
