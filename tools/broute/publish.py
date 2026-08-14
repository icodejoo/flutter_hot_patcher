#!/usr/bin/env python3
"""把一个 .vmcode 发布成设备可下载的补丁。

产出（全部落在 --repo 指向的目录）：
  releases/<release_version>/base.blob        基线快照 blob（增量的基准）
  releases/<release_version>/patches/<n>.bin  zstd 压缩的 bipatch 增量
  releases/<release_version>/index.json       服务端据此应答 /api/v1/patches/check

设备侧对应逻辑（third_party/updater）：
  下载 -> inflate(增量, base=file_provider 提供的 4 段拼接 blob) -> 校验 sha256
  若 shorebird.yaml 配了 patch_public_key，还会校验 hash 的 RSA 签名
"""
import argparse, base64, hashlib, json, pathlib, subprocess, sys


def sha256_hex(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_hash(hash_hex: str, key_path: pathlib.Path) -> str:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    # 签名对象是 hex hash 的字符串字节，与 signing.rs 的 message.as_bytes() 一致
    sig = key.sign(hash_hex.encode(), padding.PKCS1v15(), hashes.SHA256())
    return base64.b64encode(sig).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="补丁仓库目录（服务端读取它）")
    ap.add_argument("--app-binary", required=True, help="Runner.app/Frameworks/App.framework/App")
    ap.add_argument("--vmcode", required=True, help="tools/build_app_patch.sh 产出的 out.vmcode")
    ap.add_argument("--release-version", required=True, help='如 "1.0.0+1"，须与 Info.plist 一致')
    ap.add_argument("--patch-number", type=int, required=True)
    ap.add_argument("--base-url", required=True, help="设备可达的服务端地址")
    ap.add_argument("--private-key", help="RSA 私钥；省略则不签名")
    ap.add_argument("--analyze-snapshot", default=None)
    ap.add_argument("--patch-tool", default=None)
    a = ap.parse_args()

    sb = pathlib.Path.home() / ".shorebird/bin/cache"
    rev = "c15ef6379403a0a55531a058bdb2c8e55bc05c98"
    analyze = pathlib.Path(a.analyze_snapshot or
        sb / f"flutter/{rev}/bin/cache/artifacts/engine/ios-release/analyze_snapshot_arm64")
    patch_tool = pathlib.Path(a.patch_tool or sb / "artifacts/patch/patch")
    for t in (analyze, patch_tool):
        if not t.exists():
            print(f"MISSING: {t}", file=sys.stderr)
            return 1

    repo = pathlib.Path(a.repo)
    rel = repo / "releases" / a.release_version
    (rel / "patches").mkdir(parents=True, exist_ok=True)

    # 1) base blob —— 必须与设备端 file_provider 提供的 4 段拼接一致
    base_blob = rel / "base.blob"
    if not base_blob.exists():
        subprocess.run([str(analyze), "--dump_blobs", f"--out={base_blob}", a.app_binary],
                       check=True, capture_output=True)
        print(f"[publish] base.blob {base_blob.stat().st_size} bytes")

    # 2) 增量（zstd 压缩的 bipatch）
    delta = rel / "patches" / f"{a.patch_number}.bin"
    subprocess.run([str(patch_tool), str(base_blob), a.vmcode, str(delta)],
                   check=True, capture_output=True)

    # 3) hash 是**解压后**文件的 sha256，即 .vmcode 本身
    vmcode = pathlib.Path(a.vmcode)
    h = sha256_hex(vmcode)
    entry = {
        "number": a.patch_number,
        "hash": h,
        "download_url": f"{a.base_url.rstrip('/')}/patches/{a.release_version}/{a.patch_number}.bin",
        "size_compressed": delta.stat().st_size,
        "size_uncompressed": vmcode.stat().st_size,
    }
    if a.private_key:
        entry["hash_signature"] = sign_hash(h, pathlib.Path(a.private_key))

    idx_path = rel / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else {"patches": [], "rolled_back": []}
    idx["patches"] = [p for p in idx["patches"] if p["number"] != a.patch_number] + [entry]
    idx["patches"].sort(key=lambda p: p["number"])
    idx_path.write_text(json.dumps(idx, indent=2))

    ratio = 100 * entry["size_compressed"] / entry["size_uncompressed"]
    print(f"[publish] patch #{a.patch_number} -> {delta}")
    print(f"          压缩后 {entry['size_compressed']:,} B / 解压后 {entry['size_uncompressed']:,} B ({ratio:.1f}%)")
    print(f"          sha256 {h}")
    print(f"          签名   {'有' if a.private_key else '无（未配 --private-key）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
