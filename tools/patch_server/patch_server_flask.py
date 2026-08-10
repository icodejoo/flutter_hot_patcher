"""
patch_server_flask.py - flask 版补丁分发服务器
（替代 patch_server.py 中使用的 http.server，避免 Python 3.14/macOS 的 ENOTCONN bug）
"""
import argparse, json, os
from flask import Flask, request, jsonify, send_file, abort

PATCHES_DIR = "./patches"
DEFAULT_CHANNEL = "stable"
_rolled_back = {}

app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = False


def _shorebird_check(release_version, platform, channel, current_patch_number, host, proto="http"):
    no_patch = {"patch_available": False, "patch": None, "rolled_back_patch_numbers": []}
    release_version = release_version.replace(" ", "+")
    rv_dir = os.path.join(PATCHES_DIR, release_version)
    if not os.path.isdir(rv_dir):
        return no_patch

    rolled_back = _rolled_back.get(release_version, [])
    best = None
    best_number = current_patch_number

    for bundle_name in os.listdir(rv_dir):
        manifest_path = os.path.join(rv_dir, bundle_name, "manifest.json")
        if not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                m = json.load(f)
            patch_number = m.get("patch_number", m.get("patch_version", 0))
            if patch_number <= current_patch_number:
                continue
            if m.get("channel", DEFAULT_CHANNEL) != channel:
                continue
            if patch_number in rolled_back:
                continue
            if patch_number > best_number:
                best_number = patch_number
                best = (bundle_name, m)
        except Exception as e:
            print(f"[server] WARNING: {manifest_path}: {e}")

    if not best:
        return {**no_patch, "rolled_back_patch_numbers": rolled_back}

    bundle_name, manifest = best
    patch_type = manifest.get("patch_type", "bytecode")
    if patch_type == "vmcode":
        download_url = f"{proto}://{host}/patches/{release_version}/{bundle_name}/isolate_data.vmdiff"
    else:
        download_url = f"{proto}://{host}/patches/{release_version}/{bundle_name}/bundle.zst"

    patch_info = {
        "number": best_number,
        "download_url": download_url,
        "hash": manifest.get("hash", ""),
        "patch_type": patch_type,
    }
    if patch_type == "vmcode":
        patch_info["isolate_data_size"] = manifest.get("isolate_data_size", 0)

    return {
        "patch_available": True,
        "patch": patch_info,
        "rolled_back_patch_numbers": rolled_back,
    }


@app.route("/api/v1/patches/check", methods=["POST"])
def patches_check():
    req = request.get_json(force=True)
    host = request.headers.get("Host", "localhost")
    proto = request.headers.get("X-Forwarded-Proto", "http")
    result = _shorebird_check(
        req.get("release_version", ""),
        req.get("platform", "ios"),
        req.get("channel", DEFAULT_CHANNEL),
        req.get("current_patch_number", 0),
        host, proto,
    )
    print(f"[server] check: rv={req.get('release_version')} → patch_available={result['patch_available']}")
    return jsonify(result)


@app.route("/api/v1/events", methods=["POST"])
def events():
    try:
        evts = request.get_json(force=True)
        for e in (evts if isinstance(evts, list) else [evts]):
            print(f"[event] {e}")
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/v1/channels", methods=["GET"])
def channels():
    return jsonify({"channels": ["stable", "beta"]})


@app.route("/patches/<path:filepath>", methods=["GET"])
def serve_patch_file(filepath):
    full = os.path.join(PATCHES_DIR, filepath)
    if not os.path.exists(full):
        abort(404)
    return send_file(full)


@app.route("/telemetry", methods=["POST"])
def telemetry():
    try:
        data = request.get_json(force=True)
        print(f"[telemetry] {data}")
    except Exception:
        pass
    return jsonify({"ok": True})


def main():
    global PATCHES_DIR
    p = argparse.ArgumentParser()
    p.add_argument("--patches-dir", default="./patches")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="0.0.0.0")
    args = p.parse_args()
    PATCHES_DIR = os.path.abspath(args.patches_dir)
    os.makedirs(PATCHES_DIR, exist_ok=True)
    print(f"[server] Flask patch server on {args.host}:{args.port}")
    print(f"[server] Patches dir: {PATCHES_DIR}")
    from werkzeug.serving import WSGIRequestHandler, make_server

    class FixedHandler(WSGIRequestHandler):
        protocol_version = "HTTP/1.0"

        def handle_one_request(self):
            try:
                super().handle_one_request()
            except OSError:
                pass

        def handle(self):
            try:
                super().handle()
            except OSError:
                pass

    import socket as _sock
    # 同时监听 IPv4 和 IPv6
    class DualStackServer(make_server.__self__.__class__ if hasattr(make_server, '__self__') else object):
        pass

    server = make_server(args.host, args.port, app, request_handler=FixedHandler)
    # 升级为双栈
    server.socket.close()
    sock = _sock.socket(_sock.AF_INET6, _sock.SOCK_STREAM)
    sock.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
    sock.setsockopt(_sock.IPPROTO_IPV6, _sock.IPV6_V6ONLY, 0)  # 双栈
    sock.bind(("::", args.port))
    sock.listen(128)
    server.socket = sock
    server.server_address = sock.getsockname()
    server.serve_forever()


if __name__ == "__main__":
    main()
