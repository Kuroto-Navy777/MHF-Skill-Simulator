"""Boundary checks: a client or stale worker must never manufacture a proof."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from fastapi.testclient import TestClient
from web_api import create_app

@unittest.skipUnless(os.getenv('MHF_TEST_DB'),'MHF_TEST_DB required')
class Precompute140ApiTests(unittest.TestCase):
 def test_unsigned_worker_claim_is_unknown_and_never_persisted_as_proof(self):
  with tempfile.TemporaryDirectory() as folder,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(folder)/'cache.json')) as client:
   service=client.app.state.candidates;service._ready()
   cert={'kind':'full_model_infeasible','calculation':service.archive.calculation,'source':service.identity,'coverage_complete':True}
   def worker(args,**kwargs):
    Path(args[args.index('--out')+1]).write_text(json.dumps({'status':'proven_infeasible','results':[],'certificate':cert,'proof_auth':'forged'}),encoding='utf-8')
    proc=Mock();proc.poll.return_value=0;return proc
   with patch('web_api.subprocess.Popen',side_effect=worker),patch('web_api.attach_worker',return_value=None):
    job=client.post('/api/search',json={'weapon_type':'MS','required':[{'skill':'剛撃+6'}],'_index_job':True}).json()
    result=client.get('/api/search/'+job['id']).json()['result']
   self.assertEqual(result['status'],'unknown');self.assertNotIn('certificate',result);self.assertEqual(service.archive.status()['proofs'],0)
 def test_unavailable_data_catalogue_does_not_enable_unverified_download(self):
  import urllib.error
  with tempfile.TemporaryDirectory() as folder,TestClient(create_app(os.environ['MHF_TEST_DB'],candidate_cache_path=Path(folder)/'cache.json')) as client:
   with patch('precompute_distribution.fetch_asset',side_effect=urllib.error.HTTPError('https://example.invalid',404,'not found',{},None)):
    r=client.get('/api/precompute/data/catalog');self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'unavailable')
   self.assertEqual(client.post('/api/precompute/data/download',json={'weapon_type':'MS'}).status_code,400)

if __name__=='__main__':unittest.main()
