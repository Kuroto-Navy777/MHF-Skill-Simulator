"""Version and source identity for locally generated calculation data."""
import hashlib,json,sys
from pathlib import Path
from runtime_paths import app_root
SCHEMA_VERSION=140
CALCULATION_ABI='140.1'
CALCULATION_FILES=('precompute_distribution.py','data_packages.py','calculation_identity.py','candidate_service.py','activation.py','skill_engine.py','search_contract.py','candidate_validation.py','search_engine.py','weapon_effects.py','external.py','bounty.py','defense.py','armor_levels.py','search_precompute.py','search_archive.py')

def calculation_identity(root=None):
 root=Path(root or app_root())
 if getattr(sys,'frozen',False):
  data=json.loads((root/'CALCULATION_FINGERPRINT.json').read_text(encoding='utf-8'))
  if data['abi']!=CALCULATION_ABI:raise ValueError('calculation ABI mismatch')
  return data['identity']
 h=hashlib.sha256(CALCULATION_ABI.encode())
 for name in CALCULATION_FILES:
  h.update(name.encode());h.update((root/name).read_text(encoding='utf-8-sig').replace('\r\n','\n').encode())
 return h.hexdigest()

def source_identity(path):
 path=Path(path).resolve();st=path.stat()
 return hashlib.sha256(repr((str(path),st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)).encode()).hexdigest()

def fingerprint_document(root=None):
 return {'abi':CALCULATION_ABI,'identity':calculation_identity(root)}
