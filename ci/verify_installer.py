"""Verify the installer's detached Ed25519 signature with the existing pinned key."""
import argparse
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('installer',type=Path)
p.add_argument('--public-key',type=Path,default=Path(__file__).resolve().parents[1]/'update_public_key.bin')
a=p.parse_args()
Ed25519PublicKey.from_public_bytes(a.public_key.read_bytes()).verify(
    Path(str(a.installer)+'.sig').read_bytes(),a.installer.read_bytes())
print('Installer Ed25519 signature verified.')
