#!/usr/bin/env python3
"""fhpb — Route-B 热修复全流程 CLI。

对标 Shorebird 的生命周期，但全链路自建：

    fhpb init      配置 app_id / 签名密钥 / shorebird.yaml
    fhpb release   归档一个基线版本（后续补丁都以它为基准）
    fhpb patch     改完源码后生成、签名并发布一个补丁
    fhpb list      查看 release 与补丁状态
    fhpb rollback  下线某个补丁（设备下次 check 时卸载）
    fhpb rotate-key 换签名私钥（旧钥归档；必须重新发版才生效）
    fhpb serve     起分发服务端

补丁仓库布局（--repo）：

    releases/<release_version>/
        release.json      基线元数据（app_id / 构建时间 / 各产物 sha256）
        App.baseline      归档的 App.framework/App
        app.dill          归档的基线 kernel —— 补丁必须对着它编
        base.blob         analyze_snapshot --dump_blobs，增量的基准
        patches/<n>.bin   zstd 压缩的 bipatch 增量
        patches/<n>.json  该补丁的元数据
        index.json        服务端据此应答 /api/v1/patches/check

设备侧协议依据 third_party/updater/library/src/{network.rs,cache/signing.rs}。
"""
import argparse
import base64
import datetime
import hashlib
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
import uuid
from typing import NoReturn, Optional

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SB_REV = "c15ef6379403a0a55531a058bdb2c8e55bc05c98"
SB_ROOT = pathlib.Path.home() / ".shorebird/bin/cache"
SB_FLUTTER = SB_ROOT / "flutter" / SB_REV
DEFAULT_ANALYZE = SB_FLUTTER / "bin/cache/artifacts/engine/ios-release/analyze_snapshot_arm64"
DEFAULT_GEN_SNAPSHOT = SB_FLUTTER / "bin/cache/artifacts/engine/ios-release/gen_snapshot_arm64"
DEFAULT_PATCH_TOOL = SB_ROOT / "artifacts/patch/patch"


# ---------------------------------------------------------------- 基础工具


def die(msg: str) -> NoReturn:
    print(f"fhpb: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256_hex(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def run(cmd, **kw):
    """跑一条命令，失败时把 stderr 原样吐出来再退出。"""
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode != 0:
        sys.stderr.write(r.stdout)
        sys.stderr.write(r.stderr)
        die(f"命令失败（exit {r.returncode}）: {' '.join(str(c) for c in cmd)}")
    return r


def need(path: pathlib.Path, what: str) -> pathlib.Path:
    if not path.exists():
        die(f"找不到{what}: {path}")
    return path


def release_dir(repo: pathlib.Path, rv: str) -> pathlib.Path:
    return repo / "releases" / rv


def load_json(p: pathlib.Path, default=None):
    return json.loads(p.read_text()) if p.exists() else default


def write_json(p: pathlib.Path, obj) -> None:
    """原子写：服务端可能正在读同一个 index.json，不能让它读到半截。"""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, p)


def list_releases(repo: pathlib.Path):
    d = repo / "releases"
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / "release.json").exists())


def detect_release_version(app_dir: pathlib.Path) -> str:
    """从构建产物的 Info.plist 读出 release_version。

    必须与设备上报的一致，否则服务端匹配不上 —— 设备侧取的就是这两个字段。
    """
    plist = app_dir / "build/ios/iphoneos/Runner.app/Info.plist"
    if not plist.exists():
        die(f"找不到 {plist}（先跑一次 release 构建）")
    with plist.open("rb") as f:
        d = plistlib.load(f)
    short, build = d.get("CFBundleShortVersionString"), d.get("CFBundleVersion")
    if not short or not build:
        die(f"{plist} 缺 CFBundleShortVersionString / CFBundleVersion")
    return f"{short}+{build}"


def kernel_version(dill: pathlib.Path) -> int:
    """读 kernel 二进制格式版本（magic 之后的 4 字节，大端）。"""
    with dill.open("rb") as f:
        head = f.read(8)
    return int.from_bytes(head[4:8], "big") if len(head) == 8 else -1


def find_app_dills(app_dir: pathlib.Path):
    """按新到旧列出所有候选 app.dill。

    一个工程可能被多套工具链构建过（例如 X1 与 Shorebird），
    .dart_tool/flutter_build 下会同时留下 kernel 版本不同的 app.dill。
    只取 mtime 最新的那个会静默归档到错的一份，所以这里全部返回，
    由 release 逐个用 gen_snapshot 验，取第一个能用的。
    """
    hits = list((app_dir / ".dart_tool/flutter_build").rglob("app.dill"))
    if not hits:
        die("找不到 app.dill（先跑一次 release 构建）")
    return sorted(hits, key=lambda p: p.stat().st_mtime, reverse=True)


# ---------------------------------------------------------------- init


def gen_keypair(out: pathlib.Path) -> str:
    """生成 RSA 密钥对，返回 base64(DER SPKI) 公钥。

    算法由更新器写死（cache/signing.rs:37）：RSA_PKCS1_2048_8192_SHA256。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    out.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (out / "patch_private.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()))
    (out / "patch_public.pem").write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    spki = key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    b64 = base64.b64encode(spki).decode()
    (out / "patch_public_key.b64").write_text(b64 + "\n")
    os.chmod(out / "patch_private.pem", 0o600)
    return b64


def public_key_b64(keys: pathlib.Path) -> str:
    """从已有密钥目录取出 base64 SPKI 公钥。"""
    cached = keys / "patch_public_key.b64"
    if cached.exists():
        return cached.read_text().strip()
    from cryptography.hazmat.primitives import serialization
    pub = need(keys / "patch_public.pem", "公钥")
    k = serialization.load_pem_public_key(pub.read_bytes())
    return base64.b64encode(k.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def ensure_pubspec_asset(pubspec: pathlib.Path) -> bool:
    """把 shorebird.yaml 挂进 flutter assets。已挂过返回 False。

    没挂 asset 的话更新器起不来，日志是
    `Failed to find shorebird.yaml, not starting updater`。
    """
    if not pubspec.exists():
        return False
    text = pubspec.read_text()
    if "shorebird.yaml" in text:
        return False
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.rstrip() == "flutter:":
            # 找该块里已有的 assets:
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
                if lines[j].strip() == "assets:":
                    lines.insert(j + 1, "    - shorebird.yaml")
                    pubspec.write_text("\n".join(lines) + "\n")
                    return True
                j += 1
            lines.insert(i + 1, "  assets:\n    - shorebird.yaml")
            pubspec.write_text("\n".join(lines) + "\n")
            return True
    return False


def cmd_init(a) -> int:
    app_dir = pathlib.Path(a.app_dir).resolve()
    need(app_dir, "工程目录")
    keys = pathlib.Path(a.keys).resolve()

    if (keys / "patch_private.pem").exists():
        pub = public_key_b64(keys)
        print(f"[init] 复用已有密钥 {keys}")
    else:
        pub = gen_keypair(keys)
        print(f"[init] 已生成密钥 {keys}（patch_private.pem 不要提交）")

    # app_id 是设备取补丁的身份。换掉它 = 线上所有设备立刻失联，
    # 所以 --force（意思是「覆盖这个 yaml」）绝不能顺带重新随机一个。
    # 只有显式 --app-id 才换。
    yaml_path = app_dir / "shorebird.yaml"
    existing_app_id = read_yaml_field(yaml_path, "app_id")
    app_id = a.app_id or existing_app_id or str(uuid.uuid4())
    if existing_app_id and a.app_id and a.app_id != existing_app_id:
        print(f"[warn] app_id 由 {existing_app_id} 改为 {a.app_id}；"
              "已安装的设备将再也收不到补丁。", file=sys.stderr)
    elif existing_app_id:
        print(f"[init] 沿用已有 app_id={existing_app_id}")

    channel_line = f"channel: {a.channel}\n" if a.channel else ""
    yaml_path.write_text(
        "# Route-B 更新器配置。不含机密，应提交到版本库。\n"
        f"app_id: {app_id}\n"
        f"base_url: {a.base_url}\n"
        "auto_update: true\n"
        + channel_line +
        f"patch_public_key: {pub}\n")
    print(f"[init] 已写 {yaml_path}")

    if ensure_pubspec_asset(app_dir / "pubspec.yaml"):
        print("[init] 已把 shorebird.yaml 挂进 pubspec.yaml 的 flutter assets")
    else:
        print("[init] 请确认 pubspec.yaml 里有：\n"
              "         flutter:\n           assets:\n             - shorebird.yaml")

    print(f"\napp_id           {app_id}\n"
          f"base_url         {a.base_url}\n"
          f"patch_public_key {pub[:32]}…\n\n"
          f"下一步：fhpb release --app-dir {app_dir} --repo <补丁仓库>")
    return 0


def cmd_rotate_key(a) -> int:
    """换一把新的签名私钥。

    `init` 是**幂等**的：已有密钥就复用，所以它换不了钥。换钥是独立动作，
    因为后果比 init 重得多 —— 公钥编译在包里，换钥必须重新发版。
    """
    app_dir = pathlib.Path(a.app_dir).resolve() if a.app_dir else None
    keys = pathlib.Path(a.keys).resolve()
    old_priv = keys / "patch_private.pem"

    if old_priv.exists():
        # 旧钥不能直接删：还在网上的老版本包内嵌的是旧公钥，
        # 要继续给它们发补丁就得用旧钥签。归档而不是丢弃。
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        retired = keys / "retired" / stamp
        retired.mkdir(parents=True, exist_ok=True)
        for name in ("patch_private.pem", "patch_public.pem", "patch_public_key.b64"):
            if (keys / name).exists():
                shutil.move(str(keys / name), str(retired / name))
        print(f"[rotate] 旧密钥已归档到 {retired}")
    else:
        print(f"[rotate] {keys} 下没有现存密钥，直接生成新的")

    pub = gen_keypair(keys)
    print(f"[rotate] 已生成新密钥 {keys}")

    if app_dir:
        yaml_path = need(app_dir / "shorebird.yaml", "shorebird.yaml")
        lines = yaml_path.read_text().splitlines()
        out, replaced = [], False
        for line in lines:
            if line.startswith("patch_public_key:"):
                out.append(f"patch_public_key: {pub}")
                replaced = True
            else:
                out.append(line)
        if not replaced:
            out.append(f"patch_public_key: {pub}")
        yaml_path.write_text("\n".join(out) + "\n")
        # app_id 必须原封不动，否则等于把设备也一起换掉了
        print(f"[rotate] 已更新 {yaml_path} 的 patch_public_key"
              f"（app_id={read_yaml_field(yaml_path, 'app_id')} 未改动）")

    print(f"\n新公钥 {pub[:40]}…\n\n"
          "接下来必须做（顺序不能反）：\n"
          "  1. 用新的 shorebird.yaml 重新构建并**发布一个新版本**到商店 —— \n"
          "     公钥是编译进包的，不重新发版新钥不会生效\n"
          "  2. 对新版本跑 fhpb release，之后的补丁用新私钥签\n"
          "  3. 老版本的设备内嵌的还是旧公钥：要么用归档的旧私钥继续签，\n"
          "     要么停止给老版本发补丁（旧钥若已泄露，应当停止）\n")
    return 0


# ---------------------------------------------------------------- release


def cmd_release(a) -> int:
    app_dir = pathlib.Path(a.app_dir).resolve()
    repo = pathlib.Path(a.repo).resolve()
    need(app_dir, "工程目录")

    if a.build:
        flutter = need(SB_FLUTTER / "bin/flutter", "Shorebird 的 flutter")
        print("[release] flutter build ios --release …")
        subprocess.run([str(flutter), "build", "ios", "--release"], cwd=app_dir, check=True)

    rv = a.release_version or detect_release_version(app_dir)
    rel = release_dir(repo, rv)
    if (rel / "release.json").exists() and not a.force:
        die(f"release {rv} 已存在。改版本号，或加 --force 覆盖。")

    app_bin = need(app_dir / "build/ios/iphoneos/Runner.app/Frameworks/App.framework/App",
                   "App 二进制")
    gen_snapshot = need(pathlib.Path(a.gen_snapshot or DEFAULT_GEN_SNAPSHOT), "gen_snapshot")

    # --force 会重算基线（App.baseline / app.dill / base.aot / base.blob），
    # 而已发布的增量是对着**旧** base.blob 算的 —— 留着它们，设备下载后
    # inflate 出来的字节对不上 hash，补丁永远装不上，且现场毫无提示。
    old_idx = load_json(rel / "index.json", {"patches": [], "rolled_back": []})
    if old_idx["patches"]:
        if not a.discard_patches:
            die(f"release {rv} 下已有补丁 {[p['number'] for p in old_idx['patches']]}，"
                "而 --force 会重算基线，这些补丁的增量将全部失效。\n"
                "确认要作废它们请加 --discard-patches；否则请改用新的版本号。")
        retired = max(p["number"] for p in old_idx["patches"])
        shutil.rmtree(rel / "patches", ignore_errors=True)
        # 保留高水位：新补丁必须用更大的编号，否则装了旧 #N 的设备
        # 会认为自己已是最新，永远收不到新补丁。
        write_json(rel / "index.json",
                   {"patches": [], "rolled_back": [],
                    "high_water": max(retired, old_idx.get("high_water", 0))})
        print(f"[release] 已作废旧补丁 {[p['number'] for p in old_idx['patches']]}（基线已变）；"
              f"新补丁将从 #{max(retired, old_idx.get('high_water', 0)) + 1} 起编号")

    (rel / "patches").mkdir(parents=True, exist_ok=True)

    # 归档 kernel：补丁必须对着**同一份** app.dill 编，否则 cid / 符号对不上。
    # 这里当场用 gen_snapshot 验一遍 —— 工程被多套工具链构建过时，
    # .dart_tool 下会留着 kernel 版本不同的 app.dill，选错在发补丁那天才炸。
    candidates = [pathlib.Path(a.app_dill)] if a.app_dill else find_app_dills(app_dir)
    base_aot = rel / "base.aot"
    app_dill = None
    errors = []
    for cand in candidates:
        print(f"[release] 校验 {cand}（kernel v{kernel_version(cand)}）…")
        r = subprocess.run([str(gen_snapshot), "--deterministic",
                            "--snapshot_kind=app-aot-elf", f"--elf={base_aot}", str(cand)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            app_dill = cand
            break
        errors.append(f"  {cand}: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['?']}")
    if app_dill is None:
        base_aot.unlink(missing_ok=True)
        die("没有一个 app.dill 能被 gen_snapshot 接受，说明工程的构建产物与该工具链不同源。\n"
            "请用发布用的 SDK 重新构建一次 release，再跑 fhpb release。\n"
            + "\n".join(errors))

    shutil.copy2(app_bin, rel / "App.baseline")
    shutil.copy2(app_dill, rel / "app.dill")

    analyze = need(pathlib.Path(a.analyze_snapshot or DEFAULT_ANALYZE), "analyze_snapshot")
    base_blob = rel / "base.blob"
    print("[release] analyze_snapshot --dump_blobs → base.blob …")
    run([analyze, "--dump_blobs", f"--out={base_blob}", rel / "App.baseline"])

    app_id = None
    ycfg = app_dir / "shorebird.yaml"
    if ycfg.exists():
        for line in ycfg.read_text().splitlines():
            if line.startswith("app_id:"):
                app_id = line.split(":", 1)[1].strip()

    write_json(rel / "release.json", {
        "app_id": app_id,
        "release_version": rv,
        "created_at": now_iso(),
        "platform": "ios",
        "arch": "aarch64",
        "app_baseline_sha256": sha256_hex(rel / "App.baseline"),
        "app_dill_sha256": sha256_hex(rel / "app.dill"),
        "app_dill_kernel_version": kernel_version(rel / "app.dill"),
        "base_blob_bytes": base_blob.stat().st_size,
    })
    idx = rel / "index.json"
    if not idx.exists():
        write_json(idx, {"patches": [], "rolled_back": []})

    print(f"\n[release] {rv} 已归档到 {rel}\n"
          f"          App.baseline {app_bin.stat().st_size:,} B\n"
          f"          base.blob    {base_blob.stat().st_size:,} B\n"
          f"          app.dill     {app_dill.stat().st_size:,} B\n\n"
          f"下一步：改源码后跑 fhpb patch --app-dir {app_dir} --repo {repo}")
    return 0


# ---------------------------------------------------------------- patch


def sign_hash(hash_hex: str, key_path: pathlib.Path) -> str:
    """对 hex hash **字符串**签名 —— 与 signing.rs:37 的 message.as_bytes() 一致。"""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    return base64.b64encode(
        key.sign(hash_hex.encode(), padding.PKCS1v15(), hashes.SHA256())).decode()


def next_patch_number(idx: dict) -> int:
    """下一个补丁号。

    绝不复用已经发出去过的编号 —— 设备判「是否需要下载」用的是
    `current_patch_number >= latest`，复用编号会让已装旧 #N 的设备认为
    自己已是最新，从而一直跑在基于旧基线的补丁上。所以作废补丁时把最高
    编号记进 high_water，之后只增不减。
    """
    used = max((p["number"] for p in idx["patches"]), default=0)
    return max(used, idx.get("high_water", 0)) + 1


def publish_vmcode(repo: pathlib.Path, rv: str, vmcode: pathlib.Path, *,
                   number: int, base_url: str, channel: str,
                   private_key: Optional[pathlib.Path], note: Optional[str],
                   patch_tool: pathlib.Path, allow_overwrite: bool = False) -> dict:
    """把一个 .vmcode 变成可下发的增量条目，并写进 index.json。"""
    rel = release_dir(repo, rv)
    base_blob = need(rel / "base.blob", "base.blob（先跑 fhpb release）")

    # 覆盖一个已发布的编号，会让已经装了它的设备停在旧内容上（它们看
    # current >= latest 就不再下载），新旧设备就此分叉。这条检查放在这里
    # 而不是命令层，是为了让 publish.py 那个旧入口也拦得住。
    existing = load_json(rel / "index.json", {"patches": [], "rolled_back": []})
    if not allow_overwrite and any(p["number"] == number for p in existing["patches"]):
        die(f"补丁 #{number} 已存在。覆盖会让已安装它的设备与新设备内容不一致；"
            "确需覆盖请加 --force，通常应当直接发下一个编号。")
    delta = rel / "patches" / f"{number}.bin"
    delta.parent.mkdir(parents=True, exist_ok=True)
    run([patch_tool, base_blob, vmcode, delta])

    # hash 是**解压后**文件的 sha256，即 .vmcode 本身，不是增量。
    h = sha256_hex(vmcode)
    entry = {
        "number": number,
        "hash": h,
        "download_url": f"{base_url.rstrip('/')}/patches/{rv}/{number}.bin",
        "channel": channel,
        "size_compressed": delta.stat().st_size,
        "size_uncompressed": vmcode.stat().st_size,
        "created_at": now_iso(),
    }
    if note:
        entry["note"] = note
    if private_key:
        entry["hash_signature"] = sign_hash(h, private_key)

    idx_path = rel / "index.json"
    idx = load_json(idx_path, {"patches": [], "rolled_back": []})
    idx["patches"] = [p for p in idx["patches"] if p["number"] != number] + [entry]
    idx["patches"].sort(key=lambda p: p["number"])
    idx["high_water"] = max(idx.get("high_water", 0), number)
    write_json(idx_path, idx)
    write_json(rel / "patches" / f"{number}.json", entry)
    return entry


def read_yaml_field(path: pathlib.Path, field: str):
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        if line.startswith(field + ":"):
            return line.split(":", 1)[1].strip()
    return None


def cmd_patch(a) -> int:
    app_dir = pathlib.Path(a.app_dir).resolve()
    repo = pathlib.Path(a.repo).resolve()
    rv = a.release_version or detect_release_version(app_dir)
    rel = release_dir(repo, rv)
    meta = load_json(need(rel / "release.json", f"release {rv}（先跑 fhpb release）"))

    # 补丁必须发给它自己那个 app。装错 app 的补丁 = 往设备推一份完全不同的
    # 快照，后果比装不上严重得多，所以这里硬拦。
    app_id = read_yaml_field(app_dir / "shorebird.yaml", "app_id")
    if meta.get("app_id") and app_id and app_id != meta["app_id"] and not a.force:
        die(f"app_id 不匹配：工程是 {app_id}，release {rv} 是 {meta['app_id']}。\n"
            "补丁会被发给错误的应用。确认无误请加 --force。")

    key = pathlib.Path(a.private_key).resolve() if a.private_key else None
    if key:
        need(key, "私钥")
    elif not a.unsigned:
        die("必须给 --private-key；确实要发未签名补丁请显式加 --unsigned")

    base_url = a.base_url
    if not base_url:
        ycfg = app_dir / "shorebird.yaml"
        if ycfg.exists():
            for line in ycfg.read_text().splitlines():
                if line.startswith("base_url:"):
                    base_url = line.split(":", 1)[1].strip()
    if not base_url:
        die("拿不到 base_url：给 --base-url，或在 shorebird.yaml 里配好")

    # channel 来自 app 自己的 shorebird.yaml，是**构建期**属性
    # （config.rs:145 读 yaml，缺省 "stable"）。发到一个没有任何在网设备
    # 处于其中的通道，结果是补丁谁也收不到，且没有任何报错。
    if a.channel != "stable":
        app_channel = read_yaml_field(app_dir / "shorebird.yaml", "channel") or "stable"
        if app_channel != a.channel:
            print(f"[warn] 发到通道 {a.channel!r}，但本工程 shorebird.yaml 的 channel 是 "
                  f"{app_channel!r}。设备的通道在构建时就固定了，只有以 "
                  f"channel: {a.channel} 构建并安装的设备才会收到这个补丁。",
                  file=sys.stderr)

    out_dir = pathlib.Path(a.out_dir).resolve() if a.out_dir else repo / ".build" / rv
    out_dir.mkdir(parents=True, exist_ok=True)

    # 对着归档的 app.dill / base.aot 编，保证与该 release 严格同源。
    env = dict(os.environ, FHP_BASE_DILL=str(rel / "app.dill"))
    if (rel / "base.aot").exists():
        env["FHP_BASE_AOT"] = str(rel / "base.aot")
    print(f"[patch] 构建 .vmcode（基线 {rv}）…")
    # FHP_BUILD_SCRIPT 只用于测试注入桩件；生产路径走仓库里的那份。
    build_script = os.environ.get("FHP_BUILD_SCRIPT",
                                  str(REPO_ROOT / "tools/build_app_patch.sh"))
    r = subprocess.run(["bash", build_script,
                        str(app_dir), str(a.source_dir or app_dir), str(out_dir)],
                       env=env, text=True, capture_output=True)
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        die("build_app_patch.sh 失败")
    # 真实输出是 "link%:        100.00%" —— 带尾随 % 号，解析时要去掉
    link_pct = next((ln.split(":", 1)[1].strip().rstrip("%")
                     for ln in r.stdout.splitlines() if ln.startswith("link%:")), None)

    # link% 塌方是补丁与基线不同源的已知信号（实测：编译参数漏了几个 →
    # 2.62%）。这种补丁装上去等于换掉大半个快照，必须在发布前拦住，
    # 而不是印一行数字就放行。正常改几个函数应当仍在 100% 附近。
    if link_pct is None:
        die("解析不到 link%，无法判断补丁是否与基线同源，拒绝发布")
    try:
        link_val = float(link_pct)
    except ValueError:
        die(f"link% 解析失败：{link_pct!r}")
    if link_val < a.min_link_pct:
        die(f"link% {link_val:.2f}% 低于门限 {a.min_link_pct:.2f}%。\n"
            "补丁与基线很可能不同源（编译参数不一致、或对错了 release）。\n"
            "带插件/dynamic interface 的工程见 docs/RUNBOOK_ROUTE_B.md 的 FHP_PATCH_DILL。\n"
            "确认这就是预期结果请用 --min-link-pct 显式放低门限。")

    vmcode = need(out_dir / "out.vmcode", "out.vmcode")
    idx = load_json(rel / "index.json", {"patches": [], "rolled_back": []})
    number = a.patch_number or next_patch_number(idx)

    entry = publish_vmcode(repo, rv, vmcode, number=number, base_url=base_url,
                           channel=a.channel, private_key=key, note=a.note,
                           patch_tool=need(pathlib.Path(a.patch_tool or DEFAULT_PATCH_TOOL),
                                           "patch 工具"),
                           allow_overwrite=a.force)

    ratio = 100 * entry["size_compressed"] / entry["size_uncompressed"]
    print(f"\n[patch] #{entry['number']} → {rel/'patches'/f'{number}.bin'}\n"
          f"        release  {rv}   channel {entry['channel']}\n"
          f"        link%    {link_pct}\n"
          f"        增量     {entry['size_compressed']:,} B / "
          f"{entry['size_uncompressed']:,} B ({ratio:.1f}%)\n"
          f"        sha256   {entry['hash']}\n"
          f"        签名     {'有' if key else '无'}")
    return 0


# ---------------------------------------------------------------- list


def cmd_list(a) -> int:
    repo = pathlib.Path(a.repo).resolve()
    versions = [a.release_version] if a.release_version else list_releases(repo)
    if not versions:
        print(f"（{repo} 里还没有 release）")
        return 0

    for rv in versions:
        rel = release_dir(repo, rv)
        meta = load_json(rel / "release.json")
        if meta is None:
            continue
        idx = load_json(rel / "index.json", {"patches": [], "rolled_back": []})
        rolled = set(idx.get("rolled_back", []))
        print(f"\nrelease {rv}   app_id={meta.get('app_id') or '(未记录)'}   "
              f"建于 {meta.get('created_at')}")
        if not idx["patches"]:
            print("  （无补丁）")
            continue
        live = [p for p in idx["patches"] if p["number"] not in rolled]
        latest = live[-1]["number"] if live else None
        print(f"  {'补丁':<5}{'通道':<9}{'状态':<8}{'增量':>12}  创建时间")
        for p in idx["patches"]:
            state = "已下线" if p["number"] in rolled else ("当前" if p["number"] == latest else "历史")
            print(f"  #{p['number']:<4}{p.get('channel','stable'):<9}{state:<8}"
                  f"{p.get('size_compressed',0):>11,}B  {p.get('created_at','-')}"
                  + (f"  {p['note']}" if p.get("note") else ""))
    return 0


# ---------------------------------------------------------------- rollback


def cmd_rollback(a) -> int:
    repo = pathlib.Path(a.repo).resolve()
    rv = a.release_version
    if not rv:
        versions = list_releases(repo)
        if len(versions) != 1:
            die("有多个 release，必须指定 --release-version")
        rv = versions[0]
    idx_path = need(release_dir(repo, rv) / "index.json", f"release {rv} 的 index.json")
    idx = load_json(idx_path)
    known = {p["number"] for p in idx["patches"]}
    if a.patch not in known:
        die(f"release {rv} 里没有补丁 #{a.patch}（现有：{sorted(known) or '无'}）")

    rolled = set(idx.get("rolled_back", []))
    if a.undo:
        if a.patch not in rolled:
            print(f"补丁 #{a.patch} 本来就没下线，无需操作")
            return 0
        rolled.discard(a.patch)
        verb = "已恢复"
    else:
        if a.patch in rolled:
            print(f"补丁 #{a.patch} 已是下线状态")
            return 0
        rolled.add(a.patch)
        verb = "已下线"

    idx["rolled_back"] = sorted(rolled)
    write_json(idx_path, idx)

    print(f"补丁 #{a.patch} {verb}（release {rv}）")
    if a.undo:
        print("服务端恢复下发它；未装的设备下次 check 即可取得。")
        return 0

    # 说清楚两段式：先卸载回基线，再在后续 check 里取到仍可用的最新补丁。
    # 不是「立刻落到上一个补丁」—— 中间会有一次运行在基线上。
    print(f"服务端立即停止下发它，并把 rolled_back={idx['rolled_back']} 带给设备。")
    print("已装该补丁的设备：下次 check 卸载它 → 先回到基线运行，"
          "再由后续 check 取得仍可用的最新补丁。")
    by_channel = {}
    for p in idx["patches"]:
        if p["number"] not in rolled:
            by_channel[p.get("channel", "stable")] = p["number"]
    if by_channel:
        print("各通道当前仍可下发：" +
              "、".join(f"{c} → #{n}" for c, n in sorted(by_channel.items())))
    else:
        print("已无可下发补丁，设备将停留在基线。")
    return 0


# ---------------------------------------------------------------- verify


def cmd_verify(a) -> int:
    """按设备侧的校验规则复核一个已发布的补丁。

    覆盖设备会做的三件事里的两件：签名验签、hash 比对。
    第三件（inflate 增量还原出 .vmcode）需要 Shorebird 的 inflate 实现，
    本地没有对应工具，只能在设备上验 —— 见 docs/RUNBOOK_ROUTE_B.md 的验证边界。
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature

    repo = pathlib.Path(a.repo).resolve()
    rv = a.release_version
    if not rv:
        versions = list_releases(repo)
        if len(versions) != 1:
            die("有多个 release，必须指定 --release-version")
        rv = versions[0]
    rel = release_dir(repo, rv)
    idx = load_json(need(rel / "index.json", "index.json"))
    number = a.patch or max((p["number"] for p in idx["patches"]), default=None)
    if number is None:
        die(f"release {rv} 下没有补丁")
    entry = next((p for p in idx["patches"] if p["number"] == number), None)
    if entry is None:
        die(f"release {rv} 里没有补丁 #{number}")

    fails = 0

    def check(ok: bool, label: str, detail: str = "") -> None:
        nonlocal fails
        print(f"  {'✓' if ok else '✗'} {label}{('  ' + detail) if detail else ''}")
        if not ok:
            fails += 1

    print(f"校验 release {rv} 补丁 #{number}")

    delta = rel / "patches" / f"{number}.bin"
    check(delta.exists(), "增量文件存在", str(delta))
    if delta.exists():
        check(delta.stat().st_size == entry.get("size_compressed"),
              "增量大小与 index.json 一致",
              f"{delta.stat().st_size:,} B")

    # 公钥：优先命令行，其次 app 的 shorebird.yaml —— 端上信任根就是它。
    pub_b64 = a.public_key
    if not pub_b64 and a.app_dir:
        ycfg = pathlib.Path(a.app_dir) / "shorebird.yaml"
        if ycfg.exists():
            for line in ycfg.read_text().splitlines():
                if line.startswith("patch_public_key:"):
                    pub_b64 = line.split(":", 1)[1].strip()
    if not pub_b64:
        keyfile = REPO_ROOT / "tools/broute/keys/patch_public_key.b64"
        if keyfile.exists():
            pub_b64 = keyfile.read_text().strip()

    sig = entry.get("hash_signature")
    if not sig:
        check(False, "补丁已签名", "index.json 里没有 hash_signature")
    elif not pub_b64:
        check(False, "拿到公钥", "给 --public-key 或 --app-dir")
    else:
        key = serialization.load_der_public_key(base64.b64decode(pub_b64))
        try:
            key.verify(base64.b64decode(sig), entry["hash"].encode(),
                       padding.PKCS1v15(), hashes.SHA256())
            check(True, "签名验签通过", "RSA_PKCS1_2048_8192_SHA256 over hex hash")
        except InvalidSignature:
            check(False, "签名验签通过", "公钥与签名私钥不配对")

    if a.vmcode:
        vm = need(pathlib.Path(a.vmcode), ".vmcode")
        check(sha256_hex(vm) == entry["hash"], "hash 匹配给定的 .vmcode")

    print(f"\n{'全部通过' if fails == 0 else str(fails) + ' 项未通过'}")
    print("注意：增量 inflate 还原只能在设备上验，本地无 inflate 实现。")
    return 0 if fails == 0 else 1


# ---------------------------------------------------------------- serve


def cmd_serve(a) -> int:
    cmd = [sys.executable, str(REPO_ROOT / "tools/broute/server.py"),
           "--repo", a.repo, "--port", str(a.port), "--bind", a.bind]
    if a.app_id:
        cmd += ["--app-id", a.app_id]
    return subprocess.call(cmd)


# ---------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(prog="fhpb", description="Route-B 热修复全流程")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="配置 app_id / 密钥 / shorebird.yaml")
    p.add_argument("--app-dir", required=True)
    p.add_argument("--base-url", required=True, help="设备可达的分发地址")
    p.add_argument("--keys", default=str(REPO_ROOT / "tools/broute/keys"))
    p.add_argument("--app-id", default=None, help="默认随机生成")
    p.add_argument("--channel", default=None,
                   help="写入 shorebird.yaml 的更新通道；构建期固定，缺省 stable")
    p.add_argument("--force", action="store_true", help="覆盖已有 shorebird.yaml")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("rotate-key", help="换一把新的签名私钥（旧钥归档）")
    p.add_argument("--app-dir", default=None, help="同时更新它的 shorebird.yaml")
    p.add_argument("--keys", default=str(REPO_ROOT / "tools/broute/keys"))
    p.set_defaults(func=cmd_rotate_key)

    p = sub.add_parser("release", help="归档一个基线版本")
    p.add_argument("--app-dir", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--release-version", default=None, help="默认从 Info.plist 读")
    p.add_argument("--build", action="store_true", help="先跑 flutter build ios --release")
    p.add_argument("--app-dill", default=None, help="指定基线 kernel，默认自动挑选并校验")
    p.add_argument("--analyze-snapshot", default=None)
    p.add_argument("--gen-snapshot", default=None)
    p.add_argument("--force", action="store_true", help="覆盖同名 release")
    p.add_argument("--discard-patches", action="store_true",
                   help="配合 --force：作废该 release 下已发布的补丁（基线变了它们必然失效）")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("patch", help="生成、签名并发布一个补丁")
    p.add_argument("--app-dir", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--source-dir", default=None, help="含改动后 lib/ 的目录，默认同 --app-dir")
    p.add_argument("--release-version", default=None)
    p.add_argument("--patch-number", type=int, default=None, help="默认自增")
    p.add_argument("--channel", default="stable")
    p.add_argument("--private-key", default=None)
    p.add_argument("--unsigned", action="store_true", help="显式发未签名补丁")
    p.add_argument("--base-url", default=None, help="默认读 shorebird.yaml")
    p.add_argument("--note", default=None, help="备注，随 fhpb list 显示")
    p.add_argument("--out-dir", default=None)
    p.add_argument("--patch-tool", default=None)
    p.add_argument("--min-link-pct", type=float, default=90.0,
                   help="link%% 低于此值拒绝发布，默认 90（正常应接近 100）")
    p.add_argument("--force", action="store_true",
                   help="跳过 app_id 匹配与补丁号覆盖检查")
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("list", help="查看 release 与补丁状态")
    p.add_argument("--repo", required=True)
    p.add_argument("--release-version", default=None)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("rollback", help="下线某个补丁")
    p.add_argument("--repo", required=True)
    p.add_argument("--patch", type=int, required=True)
    p.add_argument("--release-version", default=None)
    p.add_argument("--undo", action="store_true", help="撤销下线")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("verify", help="按设备侧规则复核已发布的补丁")
    p.add_argument("--repo", required=True)
    p.add_argument("--release-version", default=None)
    p.add_argument("--patch", type=int, default=None, help="默认最新一个")
    p.add_argument("--app-dir", default=None, help="从它的 shorebird.yaml 取公钥")
    p.add_argument("--public-key", default=None, help="base64 DER SPKI")
    p.add_argument("--vmcode", default=None, help="比对 hash 用")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve", help="起分发服务端")
    p.add_argument("--repo", required=True)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--app-id", default=None)
    p.set_defaults(func=cmd_serve)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
