#!/usr/bin/env python3
"""
patch_builder.py — Assemble and sign a flutter_hot_patcher patch bundle.

Usage:
  python3 patch_builder.py \
    --manifest <linker_output_dir> \
    --bytecode patch.dill \
    --private-key keys/private_key.pem \
    --patch-id "patch-v1-ios-2026-08-04" \
    --app-version "1.0+3" \
    --platform ios \
    --output-dir ./patch_bundle/
"""
import argparse, hashlib, json, os, shutil
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key


def canonical_bytes(obj: dict) -> bytes:
    """Deterministic JSON: sorted keys, no extra whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':')).encode('utf-8')


def _sha256_file(path: str) -> str:
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def build_bundle(
    linker_output_dir: str,
    bytecode_path: str,
    private_key_path: str,
    patch_id: str,
    app_version: str,
    platform: str,
    output_dir: str,
) -> None:
    """Assemble and sign a patch bundle."""
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, 'bytecode'), exist_ok=True)

    # Load linker manifest (from 4-A kernel_linker)
    linker_manifest_path = os.path.join(linker_output_dir, 'manifest.json')
    with open(linker_manifest_path) as f:
        linker_manifest = json.load(f)

    # Copy artifacts into bundle
    dill_dest = os.path.join(output_dir, 'bytecode', 'patch.dill')
    shutil.copy2(bytecode_path, dill_dest)

    entry_table_src = os.path.join(linker_output_dir, 'entry_table.bin')
    entry_table_dest = os.path.join(output_dir, 'entry_table.bin')
    shutil.copy2(entry_table_src, entry_table_dest)

    cid_map_src = os.path.join(linker_output_dir, 'cid_map.bin')
    cid_map_dest = os.path.join(output_dir, 'cid_map.bin')
    shutil.copy2(cid_map_src, cid_map_dest)

    # Load private key
    with open(private_key_path, 'rb') as f:
        private_key: Ed25519PrivateKey = load_pem_private_key(f.read(), None)

    # Compute artifact hashes
    artifacts = [
        {
            'path': 'bytecode/patch.dill',
            'sha256': _sha256_file(dill_dest),
            'size': os.path.getsize(dill_dest),
        },
        {
            'path': 'entry_table.bin',
            'sha256': _sha256_file(entry_table_dest),
            'size': os.path.getsize(entry_table_dest),
        },
        {
            'path': 'cid_map.bin',
            'sha256': _sha256_file(cid_map_dest),
            'size': os.path.getsize(cid_map_dest),
        },
    ]

    # Build complete manifest (merge 4-A fields + 4-B fields)
    manifest = {
        # ── 4-A fields ──
        'format_version': linker_manifest.get('format_version', '1'),
        'dart_sdk_commit': linker_manifest.get('dart_sdk_commit', 'unknown'),
        'baseline_sha256': linker_manifest.get('baseline_sha256', ''),
        'changed_functions': linker_manifest.get('changed_functions', []),
        'icf_affected': linker_manifest.get('icf_affected', []),
        'affected_closure': linker_manifest.get('affected_closure', []),
        'class_hierarchy_changed': linker_manifest.get('class_hierarchy_changed', False),
        'class_hierarchy': linker_manifest.get('class_hierarchy', {}),

        # ── 4-B fields ──
        'patch_id': patch_id,
        'patch_version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'platform': platform,
        'payload_type': 'bytecode',
        'target_build_fingerprint': app_version,
        'sig_anchor_key_id': f'anchor-{patch_id}',
        'sig_alg': 'ed25519',
        'cert_chain': [],
        'artifacts': artifacts,
    }

    # Write manifest.json
    manifest_dest = os.path.join(output_dir, 'manifest.json')
    with open(manifest_dest, 'w') as f:
        json.dump(manifest, f, indent=2)

    # Sign manifest (canonical bytes, Ed25519)
    sig = private_key.sign(canonical_bytes(manifest))
    sig_dest = os.path.join(output_dir, 'manifest.sig')
    with open(sig_dest, 'wb') as f:
        f.write(sig)

    print(f'[patch_builder] Bundle written to {output_dir}/')
    print(f'  patch_id:   {patch_id}')
    print(f'  platform:   {platform}')
    print(f'  app_version:{app_version}')
    print(f'  changed:    {len(manifest["changed_functions"])} functions')
    print(f'  affected:   {len(manifest["affected_closure"])} closures')
    print(f'  artifacts:  {len(artifacts)}')
    print(f'  sig_alg:    {manifest["sig_alg"]}')


def main():
    p = argparse.ArgumentParser(description='Build and sign a patch bundle')
    p.add_argument('--manifest', required=True,
                   help='Directory with kernel_linker output (manifest.json etc)')
    p.add_argument('--bytecode', required=True, help='patch.dill path')
    p.add_argument('--private-key', required=True, help='Ed25519 private key PEM')
    p.add_argument('--patch-id', required=True, help='Unique patch identifier')
    p.add_argument('--app-version', required=True, help='App build version string')
    p.add_argument('--platform', choices=['ios', 'android'], default='ios')
    p.add_argument('--output-dir', required=True, help='Output bundle directory')
    args = p.parse_args()

    build_bundle(
        linker_output_dir=args.manifest,
        bytecode_path=args.bytecode,
        private_key_path=args.private_key,
        patch_id=args.patch_id,
        app_version=args.app_version,
        platform=args.platform,
        output_dir=args.output_dir,
    )


if __name__ == '__main__':
    main()
