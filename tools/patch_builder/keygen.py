#!/usr/bin/env python3
"""Generate Ed25519 key pair for patch signing."""
import argparse, os
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption
)

def main():
    p = argparse.ArgumentParser(description='Generate Ed25519 key pair')
    p.add_argument('--out', default='keys/', help='Output directory')
    p.add_argument('--key-id', default='anchor-key-1', help='Key identifier')
    args = p.parse_args()

    os.makedirs(args.out, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_path = os.path.join(args.out, 'private_key.pem')
    pub_path = os.path.join(args.out, 'public_key.pem')
    keyid_path = os.path.join(args.out, 'key_id.txt')

    with open(priv_path, 'wb') as f:
        f.write(private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    with open(pub_path, 'wb') as f:
        f.write(public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    with open(keyid_path, 'w') as f:
        f.write(args.key_id)

    pub_raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    print(f'Private key: {priv_path}')
    print(f'Public key:  {pub_path}')
    print(f'Key ID:      {args.key_id}')
    print(f'Public key (hex, embed in app): {pub_raw.hex()}')
    print('')
    print('IMPORTANT: Keep private_key.pem offline. Never commit it to git.')
    print('Add the public key hex to your app as TRUST_ANCHOR_PUBKEY constant.')

if __name__ == '__main__':
    main()
