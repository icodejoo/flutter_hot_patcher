"""Tests for patch_server.py"""
import json, os, shutil, sys, tempfile, threading, time, unittest, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
import patch_server

class TestPatchServer(unittest.TestCase):
    def setUp(self):
        self.patches_dir = tempfile.mkdtemp()
        patch_server.PATCHES_DIR = self.patches_dir
        patch_server._rolled_back_patches.clear()
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
        patch_server._rolled_back_patches.clear()

    def _get_json(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url) as r:
            return json.loads(r.read())

    def _post_json(self, path, payload):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def _make_patch(self, fingerprint, patch_id, version=1, platform="ios"):
        d = os.path.join(self.patches_dir, fingerprint, patch_id, "bytecode")
        os.makedirs(d)
        manifest = {
            "patch_id": patch_id, "patch_version": version,
            "platform": platform, "target_build_fingerprint": fingerprint,
        }
        with open(os.path.join(self.patches_dir, fingerprint, patch_id, "manifest.json"), "w") as f:
            f.write(json.dumps(manifest))
        with open(os.path.join(d, "patch.dill"), "wb") as f:
            f.write(b"\x90" * 10)

    def _make_shorebird_patch(self, release_version, bundle_name, patch_number=1, channel=patch_server.DEFAULT_CHANNEL, platform="ios"):
        """Create a patch dir with manifest including shorebird fields."""
        d = os.path.join(self.patches_dir, release_version, bundle_name)
        os.makedirs(d)
        manifest = {
            "patch_id": bundle_name,
            "patch_version": patch_number,
            "patch_number": patch_number,
            "platform": platform,
            "channel": channel,
            "target_build_fingerprint": release_version,
            "bundle_name": bundle_name,
        }
        with open(os.path.join(d, "manifest.json"), "w") as f:
            f.write(json.dumps(manifest))
        with open(os.path.join(d, "bundle.zst"), "wb") as f:
            f.write(b"\x00" * 8)

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

    def test_shorebird_patches_check_no_patch(self):
        payload = {
            "release_version": "2.0+1", "platform": "ios", "arch": "aarch64",
            "app_id": "com.example.app", "channel": patch_server.DEFAULT_CHANNEL, "current_patch_number": 0,
        }
        r = self._post_json("/api/v1/patches/check", payload)
        self.assertFalse(r["patch_available"])
        self.assertIsNone(r["patch"])
        self.assertEqual(r["rolled_back_patch_numbers"], [])

    def test_shorebird_patches_check_with_patch(self):
        self._make_shorebird_patch("1.0+1", "bundle-v1", patch_number=1, channel=patch_server.DEFAULT_CHANNEL)
        payload = {
            "release_version": "1.0+1", "platform": "ios", "arch": "aarch64",
            "app_id": "com.example.app", "channel": patch_server.DEFAULT_CHANNEL, "current_patch_number": 0,
        }
        r = self._post_json("/api/v1/patches/check", payload)
        self.assertTrue(r["patch_available"])
        self.assertIsNotNone(r["patch"])
        self.assertEqual(r["patch"]["number"], 1)
        self.assertIn("download_url", r["patch"])

    def test_shorebird_events(self):
        payload = [{"type": "PatchInstallSuccess", "patch_number": 1, "release_version": "1.0+1"}]
        r = self._post_json("/api/v1/events", payload)
        self.assertTrue(r["ok"])

    def test_shorebird_channels(self):
        r = self._get_json("/api/v1/channels")
        self.assertIn("channels", r)
        self.assertIsInstance(r["channels"], list)
        self.assertIn(patch_server.DEFAULT_CHANNEL, r["channels"])

if __name__ == "__main__":
    unittest.main(verbosity=2)
