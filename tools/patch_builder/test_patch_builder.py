#!/usr/bin/env python3
"""Tests for patch_builder.py"""
import hashlib, json, os, shutil, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patch_builder as pb

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
        self.manifest_path = os.path.join(self.tmp, 'manifest.json')
        json.dump(SAMPLE_MANIFEST, open(self.manifest_path, 'w'))
        self.dill_path = os.path.join(self.tmp, 'patch.dill')
        open(self.dill_path, 'wb').write(b'\x90' * 100)
        open(os.path.join(self.tmp, 'entry_table.bin'), 'wb').write(b'\x00' * 4)
        open(os.path.join(self.tmp, 'cid_map.bin'), 'wb').write(b'\x00' * 4)
        self.key_path = os.path.join(self.tmp, 'private_key.pem')
        _write_priv(self.key_path)
        self.out_dir = os.path.join(self.tmp, 'bundle')

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _build(self, patch_id='test-patch'):
        pb.build_bundle(
            linker_output_dir=self.tmp,
            bytecode_path=self.dill_path,
            private_key_path=self.key_path,
            patch_id=patch_id,
            app_version='1.0+3',
            platform='ios',
            output_dir=self.out_dir,
        )

    def test_bundle_creates_required_files(self):
        self._build()
        self.assertTrue(os.path.exists(f'{self.out_dir}/manifest.json'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/manifest.sig'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/bytecode/patch.dill'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/entry_table.bin'))
        self.assertTrue(os.path.exists(f'{self.out_dir}/cid_map.bin'))

    def test_manifest_has_required_fields(self):
        self._build('p1')
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        self.assertEqual(m['format_version'], '1')
        self.assertEqual(m['patch_id'], 'p1')
        self.assertEqual(m['target_build_fingerprint'], '1.0+3')
        self.assertEqual(m['platform'], 'ios')
        self.assertEqual(m['sig_alg'], 'ed25519')
        self.assertTrue(any(a['path'] == 'bytecode/patch.dill'
                           for a in m['artifacts']))

    def test_artifact_hashes_correct(self):
        self._build('p2')
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        for a in m['artifacts']:
            data = open(f'{self.out_dir}/{a["path"]}', 'rb').read()
            actual = hashlib.sha256(data).hexdigest()
            self.assertEqual(actual, a['sha256'], f'Hash mismatch: {a["path"]}')

    def test_signature_verifies(self):
        self._build('p3')
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        sig = open(f'{self.out_dir}/manifest.sig', 'rb').read()
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_PUB_BYTES)
        try:
            pub.verify(sig, pb.canonical_bytes(m))
            verified = True
        except Exception:
            verified = False
        self.assertTrue(verified)

    def test_tampered_manifest_fails_verify(self):
        self._build('p4')
        m = json.load(open(f'{self.out_dir}/manifest.json'))
        sig = open(f'{self.out_dir}/manifest.sig', 'rb').read()
        m['patch_id'] = 'tampered'
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = Ed25519PublicKey.from_public_bytes(_PUB_BYTES)
        verified = True
        try:
            pub.verify(sig, pb.canonical_bytes(m))
        except Exception:
            verified = False
        self.assertFalse(verified)

if __name__ == '__main__':
    unittest.main(verbosity=2)
