#!/usr/bin/env python3
"""Tests for patch_server.py"""
import json, os, shutil, sys, tempfile, threading, time, unittest, urllib.request
sys.path.insert(0, '/tmp')
import patch_server

class TestPatchServer(unittest.TestCase):
    def setUp(self):
        self.patches_dir = tempfile.mkdtemp()
        patch_server.PATCHES_DIR = self.patches_dir
        # Start server on random port
        self.server = patch_server.http.server.HTTPServer(
            ("127.0.0.1", 0), patch_server.PatchHandler
        )
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        shutil.rmtree(self.patches_dir)

    def _get_json(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())

    def _make_patch(self, fingerprint, patch_id, version=1, platform="ios"):
        d = os.path.join(self.patches_dir, fingerprint, patch_id, "bytecode")
        os.makedirs(d)
        manifest = {
            "patch_id": patch_id, "patch_version": version,
            "platform": platform, "target_build_fingerprint": fingerprint,
        }
        open(os.path.join(self.patches_dir, fingerprint, patch_id, "manifest.json"), "w").write(
            json.dumps(manifest))
        open(os.path.join(d, "patch.dill"), "wb").write(b"\x90" * 10)

    def test_check_no_patch_returns_empty(self):
        r = self._get_json("/check?platform=ios&fingerprint=1.0+1")
        self.assertEqual(r, {})

    def test_check_returns_patch_info(self):
        self._make_patch("1.0+1", "greet-v1")
        r = self._get_json("/check?platform=ios&fingerprint=1.0+1")
        self.assertEqual(r["patch_id"], "greet-v1")
        self.assertIn("manifest_url", r)

    def test_check_returns_latest_version(self):
        self._make_patch("1.0+1", "greet-v1", version=1)
        self._make_patch("1.0+1", "greet-v2", version=2)
        r = self._get_json("/check?platform=ios&fingerprint=1.0+1")
        self.assertEqual(r["patch_id"], "greet-v2")
        self.assertEqual(r["patch_version"], 2)

    def test_check_platform_filter(self):
        self._make_patch("1.0+1", "android-v1", platform="android")
        r = self._get_json("/check?platform=ios&fingerprint=1.0+1")
        self.assertEqual(r, {})

    def test_manifest_download(self):
        self._make_patch("1.0+1", "greet-v1")
        r = self._get_json("/patches/1.0+1/greet-v1/manifest.json")
        self.assertEqual(r["patch_id"], "greet-v1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
