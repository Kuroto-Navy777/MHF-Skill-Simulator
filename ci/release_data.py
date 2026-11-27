"""Sign an explicitly licensed data catalogue with the existing application key.

This optional step is separate from the no-DB application release. It refuses
unverified rights and validates every chunk before any upload.
"""
import argparse,json,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from data_packages import validate_catalog,decompress,file_hash
from ci.release import unlock_password
from cryptography.hazmat.primitives import serialization

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--catalog',type=Path,required=True);p.add_argument('--private-key',type=Path,required=True);p.add_argument('--public-key',type=Path,default=ROOT/'update_public_key.bin')
 p.add_argument('--gui-password',action='store_true');p.add_argument('--upload',action='store_true')
 a=p.parse_args();raw=a.catalog.read_bytes();catalog=json.loads(raw);validate_catalog(catalog,require_rights=True)
 chunks={c['asset']:c for package in catalog['packages'].values() for f in package['files'].values() for c in f['chunks']}
 for name,c in chunks.items():
  path=a.catalog.parent/name
  if path.stat().st_size!=c['size'] or file_hash(path)!=c['sha256']:raise ValueError('invalid data chunk: '+name)
  data=decompress(path.read_bytes(),c['codec'],c['raw_size'])
  if __import__('hashlib').sha256(data).hexdigest()!=c['raw_sha256']:raise ValueError('raw chunk hash mismatch')
 password=unlock_password(a.gui_password,catalog['application_release'])
 key=serialization.load_pem_private_key(a.private_key.read_bytes(),password=password.encode());del password
 if key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)!=a.public_key.read_bytes():raise ValueError('existing signing key mismatch')
 sig=Path(str(a.catalog)+'.sig');sig.write_bytes(key.sign(raw));key.public_key().verify(sig.read_bytes(),raw)
 if a.upload:
  # Upload the catalogue last so clients cannot see incomplete data releases.
  repo='Kuroto-Navy777/MHF-Skill-Simulator'
  by_release={}
  for name,c in chunks.items():by_release.setdefault(c['release'],[]).append(str(a.catalog.parent/name))
  for version,paths in by_release.items():
   for offset in range(0,len(paths),40):subprocess.run(['gh','release','upload','v'+version,'--repo',repo,*paths[offset:offset+40]],check=True)
  subprocess.run(['gh','release','upload','v'+catalog['application_release'],'--repo',repo,str(sig),str(a.catalog)],check=True)
 print('Validated and signed catalogue; chunks:',len(chunks),'uploaded:',a.upload)

if __name__=='__main__':main()
