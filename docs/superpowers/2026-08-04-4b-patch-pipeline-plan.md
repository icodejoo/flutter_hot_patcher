# 4-B 补丁流水线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 `patch_builder.py` 工具：读取 kernel_linker 的 manifest + patch.dill → 组装 patch_bundle/ → Ed25519 签名。

**Architecture:** Python 脚本（无框架依赖），`cryptography` 包做 Ed25519，读 4-A 输出、写符合 PATCH_DELIVERY_SPEC §1 的完整补丁包。

**Tech Stack:** Python 3.10+, `cryptography>=42.0.0`

**Working directory:** `~/Documents/flutter_hot_patcher/tools/patch_builder/`

---

## Task 1: keygen.py — 密钥对生成

**Files:**
- Create: `tools/patch_builder/keygen.py`
- Create: `tools/patch_builder/requirements.txt`

- [ ] **Step 1: 创建目录 + requirements.txt**

```bash
mkdir -p ~/Documents/flutter_hot_patcher/tools/patch_builder
mkdir -p ~/Documents/flutter_hot_patcher/tools/patch_builder/keys/

cat > ~/Documents/flutter_hot_patcher/tools/patch_builder/requirements.txt << 'EOF'
cryptography>=42.0.0
EOF

cd ~/Documents/flutter_hot_patcher/tools/patch_builder
python3 -m pip install -r requirements.txt --quiet
```

- [ ] **Step 2: 写 keygen.py**

```python
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
```

- [ ] **Step 3: 运行 keygen.py，生成测试密钥对**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_builder
python3 keygen.py --out keys/ --key-id test-anchor-2026-08-04 2>&1
```

Expected output:
```
Private key: keys/private_key.pem
Public key:  keys/public_key.pem
Key ID:      test-anchor-2026-08-04
Public key (hex, embed in app): <64 hex chars>
IMPORTANT: Keep private_key.pem offline...
```

- [ ] **Step 4: 验证生成文件**

```bash
ls -la ~/Documents/flutter_hot_patcher/tools/patch_builder/keys/
python3 -c "
from cryptography.hazmat.primitives.serialization import load_pem_private_key
key = load_pem_private_key(open('keys/private_key.pem','rb').read(), None)
print('Private key loaded OK, type:', type(key).__name__)
msg = b'test message'
sig = key.sign(msg)
key.public_key().verify(sig, msg)
print('Sign + verify OK')
"
```

Expected: `Private key loaded OK` + `Sign + verify OK`

- [ ] **Step 5: Add keys/ to .gitignore**

```bash
echo 'tools/patch_builder/keys/*.pem' >> ~/Documents/flutter_hot_patcher/.gitignore
```

- [ ] **Step 6: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add tools/patch_builder/keygen.py tools/patch_builder/requirements.txt .gitignore
git commit -m "feat(4-B): keygen.py — Ed25519 key pair generation"
```

---

## Task 2: patch_builder.py — bundle 组装 + 签名

**Files:**
- Create: `tools/patch_builder/patch_builder.py`

- [ ] **Step 1: 写 test_patch_builder.py（先写测试）**

```python
#!/usr/bin/env python3
"""Tests for patch_builder.py"""
import hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(__file__))
import patch_builder as pb

# Generate a test key pair for tests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, PrivateFormat, PublicFormat, NoEncryption
)

_PRIV = Ed25519PrivateKey.generate()
_PUB_BYTES = _PRIV.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

def _write_priv(path):
    with open(path, 'wb') as f:
        f.write(_PRIV.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))

SAMPLE_MANIFEST = {
    "format_version": "1",
    "dart_sdk_commit": "1aa7d7321fb",
    "baseline_sha256": "deadbeef",
    "changed_functions": ["file:///lib/greet.dart::greet"],
    "icf_affected": [],
    "affected_closure": ["file:///lib/greet.dart::callGreet"],
    "class_hierarchy_changed": False,
    "class_hierarchy": {"added_classes": [], "removed_classes": [],
                        "hierarchy_changed": [], "member_layout_changed": []},
}

class TestCanonicalBytes(unittest.TestCase):
    def test_deterministic(self):
        a = pb.canonical_bytes({"b": 2, "a": 1})
        b = pb.canonical_bytes({"a": 1, "b": 2})
        self.assertEqual(a, b)

    def test_no_extra_whitespace(self):
        b = pb.canonical_bytes({"x": 1})
        self.assertNotIn(b' ', b)

class TestBuildBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # Write fake inputs
        self.manifest_path = os.path.join(self.tmp, 'manifest.json')
        json.dump(SAMPLE_MANIFEST, open(self.manifest_path, 'w'))

        self.dill_path = os.path.join(self.tmp, 'patch.dill')
        open(self.dill_path, 'wb').write(b'\x90' * 100)  # fake bytecode

        self.linker_dir = self.tmp
        # Write fake entry_table.bin + cid_map.bin (as if from kernel_linker)
        open(os.path.join(self.tmp, 'entry_table.bin'), 'wb').write(b'\x00' * 4)
        open(os.path.join(self.tmp, 'cid_map.bin'), 'wb').write(b'\x00' * 4)

        self.key_path = os.path.join(self.tmp, 'private_key.pem')
        _write_priv(self.key_path)

        self.out_dir = os.path.join(self.tmp, 'bundle')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_bundle_creates_required_files(self):
        pb.build_bundle(
            linker_output_dir=self.linker_dir,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id='test-patch-1',
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )
        self.assertTrue(os.path.exists(f'{self.out_dir}/manifest.json'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/manifest.sig'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/bytecode/patch.dill'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/entry_table.bin'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/cid_map.bin'))

    def test_manifest_has_required_fields(self):
        pb.build_bundle(
            linker_output_dir=self.linker_dir,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id='test-patch-1',
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        self.assertEqual(m['format_version'], '1')
        self.assertEqual(m['patch_id'], 'test-patch-1')
        self.assertEqual(m['target_build_fingerprint'], '1.0+3')
        self.assertEqual(m['platform'], 'ios')
        self.assertEqual(m['sig_alg'], 'ed25519')
        self.assertIn('artifacts', m)
        self.assertTrue(any(a['path'] == 'bytecode/patch.dill'
                           for a in m['artifacts']))

    def test_artifact_hashes_correct(self):
        pb.build_bundle(
            linker_output_dir=self.linker_dir,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id='test-patch-2',
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        for a in m['artifacts']:
            data = open(f'{self.out_dir}/{a["path"]}', 'rb').read()
            actual = hashlib.sha256(data).hexdigest()
            self.assertEqual(actual, a['sha256'], f'Hash mismatch for {a["path"]}')

    def test_signature_verifies(self):
        pb.build_bundle(
            linker_output_dir=self.linker_dir,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id='test-patch-3',
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        sig = open(f'{self.out_dir}/manifest.sig', 'rb').read()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_PUB_BYTES)
        try:
            pub.verify(sig, pb.canonical_bytes(m))
            verified = True
        except Exception:
            verified = False
        self.assertTrue(verified, 'Signature should verify with correct public key')

    def test_tampered_manifest_fails_verify(self):
        pb.build_bundle(
            linker_output_dir=self.linker_dir,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id='test-patch-4',
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        sig = open(f'{self.out_dir}/manifest.sig', 'rb').read()
        m['patch_id'] = 'tampered'  # tamper
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_PUB_BYTES)
        verified = True
        try:
            pub.verify(sig, pb.canonical_bytes(m))
        except Exception:
            verified = False
        self.assertFalse(verified, 'Tampered manifest should fail verification')


if __name__ == '__main__':
    unittest.main(verbosity=2)
```

- [ ] **Step 2: 运行测试（预期失败）**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_builder
python3 test_patch_builder.py 2>&1 | head -15
```

Expected: `ImportError: No module named 'patch_builder'`

- [ ] **Step 3: 实现 patch_builder.py**

```python
#!/usr/bin/env python3
"""
patch_builder.py — Assemble and sign a flutter_hot_patcher patch bundle.

Input:
  --manifest  <dir>        Directory containing manifest.json, entry_table.bin,
                           cid_map.bin (output of kernel_linker --output-dir)
  --bytecode  <path>       patch.dill produced by dart2bytecode
  --private-key <path>     Ed25519 private key PEM file
  --patch-id  <str>        Unique patch identifier
  --app-version <str>      App build version string (target_build_fingerprint)
  --platform ios|android   Target platform
  --output-dir <path>      Where to write patch_bundle/

Output: patch_bundle/ per PATCH_DELIVERY_SPEC §1
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
```

- [ ] **Step 4: 运行测试**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_builder
python3 test_patch_builder.py 2>&1
```

Expected:
```
test_artifact_hashes_correct ... ok
test_bundle_creates_required_files ... ok
test_manifest_has_required_fields ... ok
test_signature_verifies ... ok
test_tampered_manifest_fails_verify ... ok
----------------------------------------------------------------------
Ran 5 tests in X.XXXs
OK
```

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add tools/patch_builder/patch_builder.py tools/patch_builder/test_patch_builder.py
git commit -m "feat(4-B): patch_builder.py — bundle assembly + Ed25519 signing, 5/5 tests pass"
```

---

## Task 3: 端到端验证（用 M3 fixtures）

- [ ] **Step 1: 用 M3 greet fixture 跑完整流水线**

```bash
cd ~/Documents/flutter_hot_patcher/tools/patch_builder

LINKER_OUT=~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker/test/fixtures/linker_out
DILL=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice/build/patch.dill

# Generate linker output from existing fixtures
mkdir -p "$LINKER_OUT"
cd ~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
dart --packages=.dart_tool/package_config.json bin/kernel_linker.dart \
  --base test/fixtures/greet_base.dill \
  --patch test/fixtures/greet_patch.dill \
  --dart-sdk-commit 1aa7d7321fb \
  --baseline-snapshot test/fixtures/greet_base.dill \
  --output-dir "$LINKER_OUT" \
  --allow-empty

echo "Linker output:"
ls -la "$LINKER_OUT/"

# Build patch bundle
cd ~/Documents/flutter_hot_patcher/tools/patch_builder
python3 patch_builder.py \
  --manifest "$LINKER_OUT" \
  --bytecode "$DILL" \
  --private-key keys/private_key.pem \
  --patch-id "greet-v1-ios-2026-08-04" \
  --app-version "1.0+1" \
  --platform ios \
  --output-dir /tmp/test_bundle/
```

- [ ] **Step 2: 验证 bundle 结构**

```bash
echo "=== Bundle structure ==="
ls -la /tmp/test_bundle/
ls -la /tmp/test_bundle/bytecode/

echo "=== manifest.json ==="
cat /tmp/test_bundle/manifest.json

echo "=== manifest.sig (64 bytes) ==="
wc -c /tmp/test_bundle/manifest.sig
```

Expected: 64-byte sig file, manifest has `patch_id`, `artifacts` with SHA-256 hashes

- [ ] **Step 3: 写验签脚本验证**

```bash
python3 - << 'VERIFY_EOF'
import hashlib, json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

bundle = '/tmp/test_bundle'
manifest = json.load(open(f'{bundle}/manifest.json'))
sig = open(f'{bundle}/manifest.sig', 'rb').read()

# Load test public key
pub_pem = open('keys/public_key.pem', 'rb').read()
pub = load_pem_public_key(pub_pem)

import sys
sys.path.insert(0, '.')
import patch_builder as pb

try:
    pub.verify(sig, pb.canonical_bytes(manifest))
    print('PASS: Signature verified')
except Exception as e:
    print(f'FAIL: Signature verification failed: {e}')
    exit(1)

# Verify artifact hashes
for a in manifest['artifacts']:
    data = open(f'{bundle}/{a["path"]}', 'rb').read()
    actual = hashlib.sha256(data).hexdigest()
    if actual == a['sha256']:
        print(f'PASS: {a["path"]} hash correct')
    else:
        print(f'FAIL: {a["path"]} hash mismatch')
        exit(1)

print('')
print('All checks PASS — patch_bundle is valid')
VERIFY_EOF
```

Expected: `All checks PASS`

- [ ] **Step 4: commit + copy docs**

```bash
cd ~/Documents/flutter_hot_patcher

cp /tmp/2026-08-04-4b-patch-pipeline-design.md docs/superpowers/specs/
cp /tmp/2026-08-04-4b-patch-pipeline-plan.md docs/superpowers/plans/

git add docs/ tools/patch_builder/
git commit -m "feat(4-B): COMPLETE — patch_builder end-to-end verified with M3 fixtures

5/5 unit tests + E2E verification: manifest.json assembled, Ed25519 sig verifies,
all artifact SHA-256 hashes correct.
Input: kernel_linker manifest + patch.dill → Output: signed patch_bundle/.

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```
