#!/usr/bin/env python3
"""自建补丁分发服务端，实现设备更新器所需的最小协议。

端点（third_party/updater/library/src/network.rs:16,20）：
  POST /api/v1/patches/check    -> PatchCheckResponse
  POST /api/v1/patches/events   -> 201（遥测，落盘留档）
  GET  /patches/<ver>/<n>.bin   -> 增量文件

请求字段：app_id / channel / release_version / platform / arch /
          client_id / current_patch_number
应答字段：patch_available / patch{number,hash,download_url,hash_signature}
          / rolled_back_patch_numbers
"""
import argparse, json, pathlib, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path(".")
APP_ID = None


def load_index(release_version: str):
    p = REPO / "releases" / release_version / "index.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


class Handler(BaseHTTPRequestHandler):
    server_version = "fhp-patch-server/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "bad json"})
            return

        if self.path.rstrip("/") == "/api/v1/patches/check":
            self._check(req)
        elif self.path.rstrip("/") == "/api/v1/patches/events":
            ev = REPO / "events.log"
            with ev.open("a") as f:
                f.write(json.dumps(req) + "\n")
            self.send_response(201)
            self.end_headers()
        else:
            self._json(404, {"error": "unknown endpoint"})

    def _check(self, req):
        app_id = req.get("app_id")
        rv = req.get("release_version", "")
        current = req.get("current_patch_number")
        channel = req.get("channel") or "stable"
        print(f"[check] app_id={app_id} release={rv} current={current} "
              f"channel={channel} platform={req.get('platform')} arch={req.get('arch')}")

        if APP_ID and app_id != APP_ID:
            # app_id 不匹配一律不下发，避免把补丁发给别的应用
            self._json(200, {"patch_available": False})
            return

        idx = load_index(rv)
        if not idx or not idx["patches"]:
            self._json(200, {"patch_available": False,
                             "rolled_back_patch_numbers": []})
            return

        rolled = idx.get("rolled_back", [])
        # 已下线的不能再下发；未标 channel 的旧条目按 stable 处理。
        eligible = [p for p in idx["patches"]
                    if p["number"] not in rolled
                    and p.get("channel", "stable") == channel]
        if not eligible:
            self._json(200, {"patch_available": False,
                             "rolled_back_patch_numbers": rolled})
            return

        latest = eligible[-1]
        if current is not None and current >= latest["number"]:
            self._json(200, {"patch_available": False,
                             "rolled_back_patch_numbers": rolled})
            return

        patch = {k: latest[k] for k in ("number", "hash", "download_url") if k in latest}
        if latest.get("hash_signature"):
            patch["hash_signature"] = latest["hash_signature"]
        self._json(200, {"patch_available": True, "patch": patch,
                         "rolled_back_patch_numbers": rolled})

    def do_GET(self):
        parts = [p for p in self.path.split("/") if p]
        if len(parts) == 3 and parts[0] == "patches":
            f = REPO / "releases" / parts[1] / "patches" / parts[2]
            if f.exists():
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                print(f"[download] {f.name} {len(data)} bytes")
                return
        self.send_response(404)
        self.end_headers()


def main() -> int:
    global REPO, APP_ID
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--bind", default="0.0.0.0", help="设备要能连上，别用 127.0.0.1")
    ap.add_argument("--app-id", default=None, help="设了就只给该 app_id 下发")
    a = ap.parse_args()
    REPO = pathlib.Path(a.repo)
    APP_ID = a.app_id
    srv = ThreadingHTTPServer((a.bind, a.port), Handler)
    print(f"补丁服务端 http://{a.bind}:{a.port}  repo={REPO}")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
