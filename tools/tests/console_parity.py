#!/usr/bin/env python3
"""新旧补丁服务逐字节对拍：同一组请求分别打给旧 server.py 与新控制台服务，比状态码、Content-Type、响应体。

用法: console_parity.py --old http://127.0.0.1:8793 --new http://127.0.0.1:8794 --repo <旧仓库> [--app-id APP1]

请求分两组：
  core        设备协议：check（含旧字段、缺省渠道、错 app_id、已回滚、高水位、增量缺失）+ 补丁下载成功路径
              （路径取 download_url 里的原样写法，版本号里的 + 不编码）。必须逐字节相同，不同则退出码 1
  peripheral  非成功路径与旧服务自己的非协议行为（缺文件的 404 体、%2B 写法、坏 JSON、未知路径、events 回执）。
              差异只如实列出，不计入失败；设备不会走到这些路径（check 不会下发缺文件的补丁）
"""
import argparse
import http.client
import json
import pathlib
import sys
import urllib.parse

# 渠道取值：仓库里出现的 + 缺省 + 没人用的
EXTRA_CHANNELS = ["beta", "staging", "nightly"]
CURRENT_EXTRA = [0, 99]


def ask(base: str, method: str, path: str, body: bytes = b"", ctype: str = "application/json"):
    """发一个请求，返回 (状态码, Content-Type, 响应体字节)。"""
    u = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(u.netloc, timeout=10)
    try:
        hdr = {"Content-Type": ctype} if body else {}
        conn.request(method, path, body=body or None, headers=hdr)
        r = conn.getresponse()
        return r.status, (r.getheader("Content-Type") or "").split(";")[0], r.read()
    finally:
        conn.close()


def load_repo(repo: pathlib.Path) -> dict:
    """读旧仓库：{版本: index.json}。"""
    out = {}
    for d in sorted((repo / "releases").iterdir()):
        if (d / "release.json").exists():
            idx = d / "index.json"
            out[d.name] = json.loads(idx.read_text()) if idx.exists() else {"patches": []}
    return out


def core_requests(repo: dict, app_id: str, repo_dir: pathlib.Path) -> list:
    """生成 core 组：(说明, 方法, 路径, 体字节)。"""
    reqs = []

    def check(label, **kw):
        """登记一个 check 请求。"""
        reqs.append((label, "POST", "/api/v1/patches/check", json.dumps(kw).encode()))

    base = {"platform": "ios", "arch": "aarch64", "client_id": "parity"}
    for ver, idx in list(repo.items()) + [("9.9.9+9", {"patches": []})]:
        nums = [p["number"] for p in idx.get("patches", [])]
        chans = sorted({p.get("channel", "stable") for p in idx.get("patches", [])} | {"stable"}
                       | set(EXTRA_CHANNELS))
        currents = [None, *CURRENT_EXTRA, *nums, (max(nums) + 1 if nums else 1)]
        for ch in [None, *chans]:
            for cur in currents:
                kw = dict(base, app_id=app_id, release_version=ver)
                if ch is not None:
                    kw["channel"] = ch
                if cur is not None:
                    kw["current_patch_number"] = cur
                check(f"{ver} ch={ch} cur={cur}", **kw)
        # 旧客户端字段 patch_number
        for cur in nums[:3]:
            check(f"{ver} legacy patch_number={cur}", **dict(base, app_id=app_id, release_version=ver,
                                                              channel="stable", patch_number=cur))
        # 其它平台/架构
        check(f"{ver} android", **dict(base, app_id=app_id, release_version=ver, platform="android", arch="arm64"))
    # 不匹配 / 缺失 app_id
    ver0 = next(iter(repo))
    check("wrong app_id", **dict(base, app_id="NOT-" + app_id, release_version=ver0))
    check("missing app_id", **dict(base, release_version=ver0))
    check("empty app_id", **dict(base, app_id="", release_version=ver0))
    check("missing release_version", **dict(base, app_id=app_id))
    # 补丁下载成功路径：只取增量文件真实存在的条目，路径与 download_url 一致
    for ver, idx in repo.items():
        for p in idx.get("patches", []):
            if (repo_dir / "releases" / ver / "patches" / f"{p['number']}.bin").exists():
                reqs.append((f"download {ver} #{p['number']}", "GET", f"/patches/{ver}/{p['number']}.bin", b""))
    return reqs


def peripheral_requests(repo: dict, repo_dir: pathlib.Path) -> list:
    """peripheral 组：非成功路径与旧服务的非协议行为。"""
    ver0 = next(iter(repo))
    extra = [("download missing release", "GET", f"/patches/{ver0}/999.bin", b""),
             ("download %2B-encoded", "GET", f"/patches/{urllib.parse.quote(ver0)}/1.bin", b"")]
    for ver, idx in repo.items():
        for p in idx.get("patches", []):
            if not (repo_dir / "releases" / ver / "patches" / f"{p['number']}.bin").exists():
                extra.append((f"download {ver} #{p['number']} (增量文件缺失)", "GET",
                              f"/patches/{ver}/{p['number']}.bin", b""))
    return extra + [
        ("bad json", "POST", "/api/v1/patches/check", b"{not json"),
        ("unknown path", "GET", "/nope", b""),
        ("unknown post", "POST", "/nope", b"{}"),
        ("events", "POST", "/api/v1/patches/events", json.dumps({"event": {"type": "__patch_install__"}}).encode()),
    ]


def run_group(name: str, reqs: list, old: str, new: str) -> list:
    """跑一组，返回差异列表 [(说明, 旧, 新)]，并打印汇总。"""
    diffs = []
    for label, method, path, body in reqs:
        o, n = ask(old, method, path, body), ask(new, method, path, body)
        if o != n:
            diffs.append((label, o, n))
    print(f"[{name}] {len(reqs)} 个请求，不一致 {len(diffs)} 个")
    return diffs


def show(diffs: list) -> None:
    """逐条打印差异原文。"""
    for label, o, n in diffs:
        print(f"  DIFF {label}\n    旧: status={o[0]} type={o[1]!r} body={o[2][:300]!r}\n"
              f"    新: status={n[0]} type={n[1]!r} body={n[2][:300]!r}")


def main() -> int:
    """入口：core 有差异退出码 1。"""
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--app-id", default="APP1")
    a = ap.parse_args()
    repo_dir = pathlib.Path(a.repo)
    repo = load_repo(repo_dir)
    print(f"旧仓库 {len(repo)} 个 release: " + ", ".join(
        f"{v}(补丁 {[p['number'] for p in i.get('patches', [])]}, 回滚 {i.get('rolled_back', [])}, hw {i.get('high_water', 0)})"
        for v, i in repo.items()))
    core = run_group("core", core_requests(repo, a.app_id, repo_dir), a.old, a.new)
    show(core)
    per = run_group("peripheral", peripheral_requests(repo, repo_dir), a.old, a.new)
    show(per)
    print("RESULT:", "core 逐字节相同" if not core else f"core 有 {len(core)} 处差异")
    return 1 if core else 0


if __name__ == "__main__":
    sys.exit(main())
