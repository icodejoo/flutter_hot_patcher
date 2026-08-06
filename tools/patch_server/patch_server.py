#!/usr/bin/env python3
"""
4-E: flutter_hot_patcher patch distribution server.

Endpoints:
  GET /check?platform=ios&fingerprint=1.0+1    -> {patch_id, bundle_url} or {}
  GET /patches/<patch_id>/manifest.json         -> manifest.json content
  GET /patches/<patch_id>/<file>               -> artifact file
  POST /telemetry                              -> anonymous crash count (5-B)

Shorebird-protocol endpoints:
  POST /api/v1/patches/check                   -> PatchCheckResponse
  POST /api/v1/events                          -> {ok: true}
  GET  /api/v1/channels                        -> {channels: [...]}

Usage:
  python3 patch_server.py --patches-dir /path/to/patches/ --port 8765

Patch storage layout:
  patches_dir/
    1.0+1/                      <- indexed by build fingerprint
      greet-v1-ios-m4demo/      <- patch bundle (what 4-B produces)
        manifest.json
        manifest.sig
        bytecode/patch.dill
        entry_table.bin
        cid_map.bin
"""
import argparse, http.server, json, os, urllib.parse

PATCHES_DIR = "./patches"
_crash_counts = {}  # {patch_id: {"attempts": 0, "crashes": 0}}
_rolled_back_patches = {}  # {release_version: [patch_numbers]}

class PatchHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[server] {fmt % args}")

    def _send_json(self, code, obj):
        body = json.dumps(obj, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        try:
            data = open(path, "rb").read()
        except FileNotFoundError:
            self.send_error(404, "Not found")
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]

        # GET /check?platform=ios&fingerprint=1.0+1
        if parts == ["check"]:
            params = dict(urllib.parse.parse_qsl(parsed.query))
            fp = params.get("fingerprint", "")
            platform = params.get("platform", "ios")
            result = self._find_latest_patch(fp, platform)
            self._send_json(200, result)
            return

        # GET /api/v1/channels
        if parts == ["api", "v1", "channels"]:
            self._send_json(200, {"channels": ["stable", "beta"]})
            return

        # GET /patches/<fingerprint>/<patch_id>/manifest.json
        # GET /patches/<fingerprint>/<patch_id>/<file>
        if parts and parts[0] == "patches" and len(parts) >= 4:
            fp = parts[1]
            patch_id = parts[2]
            rest = parts[3:]
            file_path = os.path.join(PATCHES_DIR, fp, patch_id, *rest)
            self._send_file(file_path)
            return

        self.send_error(404, "Unknown endpoint")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        parts = [p for p in parsed.path.split("/") if p]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # POST /api/v1/patches/check
        if parts == ["api", "v1", "patches", "check"]:
            try:
                req = json.loads(body)
            except Exception:
                self._send_json(400, {"error": "invalid json"})
                return
            release_version = req.get("release_version", "")
            platform = req.get("platform", "ios")
            channel = req.get("channel", "stable")
            current_patch_number = req.get("current_patch_number", 0)
            host = self.headers.get("Host", "localhost")
            result = self._shorebird_check(release_version, platform, channel, current_patch_number, host)
            self._send_json(200, result)
            return

        # POST /api/v1/events
        if parts == ["api", "v1", "events"]:
            try:
                events = json.loads(body)
                for evt in (events if isinstance(events, list) else [events]):
                    print(f"[event] {evt}")
            except Exception as e:
                print(f"[events] parse error: {e}")
            self._send_json(200, {"ok": True})
            return

        if parsed.path == "/telemetry":
            try:
                data = json.loads(body)
                patch_id = data.get("patch_id", "")
                success = data.get("success", True)
                if patch_id:
                    c = _crash_counts.setdefault(patch_id, {"attempts": 0, "crashes": 0})
                    c["attempts"] += 1
                    if not success:
                        c["crashes"] += 1
                    crash_rate = c["crashes"] / max(c["attempts"], 1)
                    print(f"[telemetry] {patch_id}: {c['crashes']}/{c['attempts']} crashes ({crash_rate:.0%})")
                    if crash_rate > 0.05 and c["attempts"] >= 10:
                        print(f"[ALERT] High crash rate for {patch_id} — consider withdrawing")
            except Exception as e:
                print(f"[telemetry] parse error: {e}")
            self._send_json(200, {"ok": True})
            return
        self.send_error(404)

    def _find_latest_patch(self, fingerprint, platform):
        """Return latest patch info for this fingerprint, or empty dict."""
        fingerprint = fingerprint.replace(' ', '+')
        fp_dir = os.path.join(PATCHES_DIR, fingerprint)
        if not os.path.isdir(fp_dir):
            return {}
        best = None
        best_version = -1
        for patch_id in os.listdir(fp_dir):
            manifest_path = os.path.join(fp_dir, patch_id, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                m = json.load(open(manifest_path))
                if m.get("platform") != platform:
                    continue
                v = m.get("patch_version", 0)
                if v > best_version:
                    best_version = v
                    best = (patch_id, m)
            except Exception:
                continue
        if not best:
            return {}
        patch_id, manifest = best
        base_url = f"/patches/{fingerprint}/{patch_id}"
        return {
            "patch_id": patch_id,
            "patch_version": best_version,
            "manifest_url": f"{base_url}/manifest.json",
            "bundle_base_url": base_url,
        }

    def _shorebird_check(self, release_version, platform, channel, current_patch_number, host):
        """Shorebird-compatible patch check logic."""
        no_patch = {"patch_available": False, "patch": None, "rolled_back_patch_numbers": []}
        release_version = release_version.replace(' ', '+')
        rv_dir = os.path.join(PATCHES_DIR, release_version)
        if not os.path.isdir(rv_dir):
            return no_patch

        rolled_back = _rolled_back_patches.get(release_version, [])
        best = None
        best_number = current_patch_number

        for bundle_name in os.listdir(rv_dir):
            manifest_path = os.path.join(rv_dir, bundle_name, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            try:
                m = json.load(open(manifest_path))
                patch_number = m.get("patch_number", m.get("patch_version", 0))
                if patch_number <= current_patch_number:
                    continue
                if m.get("channel", "stable") != channel:
                    continue
                if patch_number in rolled_back:
                    continue
                if patch_number > best_number:
                    best_number = patch_number
                    best = (bundle_name, m)
            except Exception:
                continue

        if not best:
            return {**no_patch, "rolled_back_patch_numbers": rolled_back}

        bundle_name, manifest = best
        download_url = f"http://{host}/patches/{release_version}/{bundle_name}/bundle.zst"
        return {
            "patch_available": True,
            "patch": {
                "number": best_number,
                "download_url": download_url,
                "hash": manifest.get("hash", ""),
            },
            "rolled_back_patch_numbers": rolled_back,
        }


def main():
    global PATCHES_DIR
    p = argparse.ArgumentParser(description="flutter_hot_patcher patch server")
    p.add_argument("--patches-dir", default="./patches", help="Patch bundles root dir")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()
    PATCHES_DIR = os.path.abspath(args.patches_dir)
    os.makedirs(PATCHES_DIR, exist_ok=True)

    print(f"[server] Patch server starting on {args.host}:{args.port}")
    print(f"[server] Patches dir: {PATCHES_DIR}")
    httpd = http.server.HTTPServer((args.host, args.port), PatchHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
