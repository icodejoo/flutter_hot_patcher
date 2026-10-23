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
    fhpb console   login / create-key / import：配置控制台 API、导入旧仓库

配置了控制台（fhpb console login，或环境变量 FHPB_SERVER + FHPB_API_KEY）后，
release / patch / list / rollback / verify 改走控制台 API，补丁号由服务端分配；
没配置时行为与以前完全一致（本地补丁仓库 + fhpb serve）。FHPB_MODE=local 可强制本地模式。

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
import getpass
import json
import os
import pathlib
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import uuid
from typing import NoReturn, Optional

import console_client
from console_client import Console, ConsoleError

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


DWARF_ARGS = ["--dwarf-stack-traces", "--resolve-dwarf-paths"]


def dwarf_mode(snapshot: pathlib.Path) -> Optional[bool]:
    """快照特性串里记录的 dwarf_stack_traces_mode：True / False / None（读不出）。

    `--split-debug-info` 构建的 App 带 `dwarf_stack_traces_mode`，
    普通构建带 `no-dwarf_stack_traces_mode`。基线与补丁必须一致：
    两者生成的机器码不同，链接表会把补丁函数连到错误的基线地址上。
    """
    data = snapshot.read_bytes()
    on, off = data.count(b" dwarf_stack_traces_mode "), data.count(b" no-dwarf_stack_traces_mode ")
    if on and not off:
        return True
    if off and not on:
        return False
    return None


# ---------------------------------------------------------------- 控制台模式（API）

# release 产物在服务端的登记方式：平台固定 ios，App.baseline 用真实架构，
# 其余伴随文件用 "fhpb:<名字>" 作 arch（服务端按 平台+arch 去重）。
SIDECAR_PREFIX = "fhpb:"
BASELINE_ARCH = "aarch64"
BASELINE_NAME = "App.baseline"
# 出补丁必需的伴随文件（base.aot 旧 release 可能没有，可选）
REQUIRED_SIDECARS = ("release.json", "app.dill", "base.blob")
OPTIONAL_SIDECARS = ("base.aot", "base.aot.symbols")
SYMBOLS_TAR = "symbols.tar"
FLUTTER_REVISION = SB_REV


def console_for() -> Optional[Console]:
    """已配置控制台就返回客户端，否则 None（走本地仓库模式）。"""
    cfg = console_client.resolve()
    return Console(*cfg) if cfg else None


def con_call(fn, *args, **kw):
    """调控制台 API，服务端错误转成 fhpb 的退出报错。"""
    try:
        return fn(*args, **kw)
    except ConsoleError as e:
        die(f"控制台: {e}")


def resolve_app_ids(a, repo: pathlib.Path, rv: Optional[str] = None) -> list:
    """确定要操作的 App：--app-id > --app-dir 的 shorebird.yaml > 本地仓库 release.json 里记的（去重）。"""
    if getattr(a, "app_id", None):
        return [a.app_id]
    if getattr(a, "app_dir", None):
        yid = read_yaml_field(pathlib.Path(a.app_dir) / "shorebird.yaml", "app_id")
        if yid:
            return [yid]
    ids = []
    for v in ([rv] if rv else list_releases(repo)):
        meta = load_json(release_dir(repo, v) / "release.json", {})
        if meta.get("app_id") and meta["app_id"] not in ids:
            ids.append(meta["app_id"])
    return ids


def resolve_app_id(a, repo: pathlib.Path, rv: Optional[str] = None) -> str:
    """同 resolve_app_ids，但要求结果唯一。"""
    ids = resolve_app_ids(a, repo, rv)
    if len(ids) != 1:
        die("拿不到唯一的 app_id：给 --app-id，或 --app-dir（读它的 shorebird.yaml）")
    return ids[0]


def pick_remote_release(con: Console, app_id: str, rv: Optional[str]) -> dict:
    """按版本号取服务端 release；没给版本且只有一个 release 时取它。"""
    if rv:
        rel = con_call(con.find_release, app_id, rv)
        if rel is None:
            die(f"服务端没有 release {rv}（app_id={app_id}；先跑 fhpb release）")
        return rel
    rels = con_call(con.releases, app_id)
    if len(rels) != 1:
        die("有多个 release，必须指定 --release-version" if rels else f"app_id={app_id} 还没有 release")
    return rels[0]


def release_upload_plan(rel: pathlib.Path, tmp: pathlib.Path) -> list:
    """要上传的 release 产物清单 [(arch, 文件路径)]；symbols 目录先打成 tar。"""
    plan = [(BASELINE_ARCH, rel / BASELINE_NAME)]
    for name in (*REQUIRED_SIDECARS, *OPTIONAL_SIDECARS):
        if (rel / name).exists():
            plan.append((SIDECAR_PREFIX + name, rel / name))
    if (rel / "symbols").is_dir():
        tar = tmp / SYMBOLS_TAR
        with tarfile.open(tar, "w") as t:
            t.add(rel / "symbols", arcname="symbols")
        plan.append((SIDECAR_PREFIX + SYMBOLS_TAR, tar))
    return plan


def live_remote_patches(con: Console, app_id: str, rid: int) -> list:
    """release 下还没回滚的补丁。"""
    return [p for p in con_call(con.patches, app_id, rid) if not p["is_rolled_back"]]


def publish_release_remote(con: Console, app_id: str, rv: str, rel: pathlib.Path, force: bool) -> None:
    """把归档好的基线上传到服务端：createRelease → createReleaseArtifact → 上传。

    force 时先回滚该 release 全部补丁，再 deleteReleaseArtifacts 重传。
    """
    r = con_call(con.find_release, app_id, rv)
    if r is None:
        r = con_call(con.create_release, app_id, rv, FLUTTER_REVISION)
    elif force:
        live = live_remote_patches(con, app_id, r["id"])
        for p in live:
            con_call(con.rollback, app_id, r["id"], p["id"])
        con_call(con.delete_release_artifacts, app_id, r["id"])
        if live:
            top = max(p["number"] for p in con_call(con.patches, app_id, r["id"]))
            print(f"[release] 已回滚旧补丁 {[p['number'] for p in live]}（基线已变）；"
                  f"新补丁将从 #{top + 1} 起编号")
    with tempfile.TemporaryDirectory(prefix="fhpb_up_") as td:
        for arch, path in release_upload_plan(rel, pathlib.Path(td)):
            size = path.stat().st_size
            art = con_call(con.create_release_artifact, app_id, r["id"], arch=arch, platform="ios",
                           hash=console_client.sha256_file(path), size=size, filename=path.name)
            con_call(con.upload, art["url"], path, size)
            print(f"[release] 已上传 {path.name} ({size:,} B) → 服务端 release {rv}")


def fetch_release_files(con: Console, app_id: str, rv: str, repo: pathlib.Path):
    """按 release 拉服务端产物到本地工作目录，返回 (release, 工作目录, release.json 内容)。

    产物按 sha256 缓存在 <repo>/.cache/，命中且校验通过就不再下载。
    """
    r = pick_remote_release(con, app_id, rv)
    arts = {x["arch"]: x for x in con_call(con.release_artifacts, app_id, r["id"])}
    work = repo / ".console" / app_id / r["version"]
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    cache = repo / ".cache"
    for name in (*REQUIRED_SIDECARS, *OPTIONAL_SIDECARS):
        art = arts.get(SIDECAR_PREFIX + name)
        if art is None:
            if name in REQUIRED_SIDECARS:
                die(f"服务端 release {r['version']} 的产物不全：缺 {name}（重新跑 fhpb release --force）")
            continue
        cached = cache / art["hash"]
        if not cached.exists() or console_client.sha256_file(cached) != art["hash"]:
            con_call(con.download, art["url"], cached, art["hash"])
        try:
            os.link(cached, work / name)
        except OSError:
            shutil.copyfile(cached, work / name)
    return r, work, load_json(work / "release.json", {})


def ensure_remote_channel(con: Console, app_id: str, name: str) -> dict:
    """取渠道，没有就建（本地模式允许任意渠道名，这里保持一致）。"""
    for ch in con_call(con.channels, app_id):
        if ch["name"] == name:
            return ch
    return con_call(con.create_channel, app_id, name)


def public_key_of_private(key_path: pathlib.Path) -> str:
    """从私钥推出 base64(DER SPKI) 公钥（没有别的信任根可用时的兜底）。"""
    from cryptography.hazmat.primitives import serialization
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    return base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def publish_vmcode_remote(con: Console, app_id: str, release: dict, vmcode: pathlib.Path,
                          base_blob: pathlib.Path, *, channel: str, private_key: Optional[pathlib.Path],
                          pub_b64: Optional[str], note: Optional[str], patch_tool: pathlib.Path,
                          metadata: dict, out_dir: pathlib.Path, platform: str = "ios",
                          arch: str = BASELINE_ARCH, number: Optional[int] = None) -> dict:
    """把 .vmcode 变成增量并发布到服务端，返回条目（含服务端分配的 number）。

    顺序：本地出增量 + 签名 → 本地自验 → createPatch → createPatchArtifact → 上传 → promote。
    自验不过就在碰服务端之前退出。补丁号只能由服务端分配，传 number 直接报错。
    """
    if number is not None:
        die("补丁号由服务端分配，不接受 --patch-number")
    delta = out_dir / "delta.bin"
    run([patch_tool, base_blob, vmcode, delta])
    # hash 是解压后文件（.vmcode）的 sha256，不是增量的
    h = console_client.sha256_file(vmcode)
    entry = {"hash": h, "size_compressed": delta.stat().st_size,
             "size_uncompressed": vmcode.stat().st_size, "channel": channel}
    if private_key:
        entry["hash_signature"] = sign_hash(h, private_key)
        # 与设备同规则自验（验签 + hash + 大小），不过不上传
        pub = pub_b64 or public_key_of_private(private_key)
        if verify_entry(entry, delta, pub, vmcode, f"{release['version']} 待发布") != 0:
            die("自验未通过，拒绝上传")
    ch = ensure_remote_channel(con, app_id, channel)
    p = con_call(con.create_patch, app_id, release["id"], metadata)
    sig = {"hash_signature": entry["hash_signature"]} if "hash_signature" in entry else {}
    art = con_call(con.create_patch_artifact, app_id, p["id"], arch=arch, platform=platform, hash=h,
                   size=entry["size_compressed"], **sig)
    con_call(con.upload, art["url"], delta, entry["size_compressed"])
    con_call(con.promote, app_id, p["id"], ch["id"])
    if note:
        con_call(con.set_notes, app_id, release["id"], p["id"], note)
    entry["number"] = p["number"]
    return entry


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

    # 先定 release 目录：--split-debug-info 的调试符号要直接落进归档。
    rv_pre = a.release_version or (None if a.build else detect_release_version(app_dir))
    symbols_tmp = None
    if a.build:
        flutter = need(SB_FLUTTER / "bin/flutter", "Shorebird 的 flutter")
        cmd = [str(flutter), "build", "ios", "--release"]
        if a.split_debug_info:
            # 先编到临时目录：release 版本号要等构建完从 Info.plist 读。
            symbols_tmp = pathlib.Path(tempfile.mkdtemp(prefix="fhpb_symbols_"))
            cmd.append(f"--split-debug-info={symbols_tmp}")
        print(f"[release] {' '.join(cmd[1:])} …")
        subprocess.run(cmd, cwd=app_dir, check=True)

    rv = rv_pre or detect_release_version(app_dir)
    rel = release_dir(repo, rv)
    if (rel / "release.json").exists() and not a.force:
        die(f"release {rv} 已存在。改版本号，或加 --force 覆盖。")

    # 控制台模式：先问清服务端状态，免得白白构建；破坏性动作（回滚、删产物）留到本地归档成功之后
    con = console_for()
    app_id = a.app_id or read_yaml_field(app_dir / "shorebird.yaml", "app_id")
    remote_rel = None
    if con:
        if not app_id:
            die("控制台模式需要 app_id：给 --app-id，或先 fhpb init 生成 shorebird.yaml")
        try:
            con.get_app(app_id)
        except ConsoleError as e:
            die(f"控制台: {e}\n  App 必须先存在于服务端：fhpb console import 导入旧仓库，"
                "或在控制台建 App 后用它的 app_id 重新 fhpb init --app-id。")
        remote_rel = con_call(con.find_release, app_id, rv)
        if remote_rel and not a.force and con_call(con.release_artifacts, app_id, remote_rel["id"]):
            die(f"服务端已有 release {rv}。改版本号，或加 --force 覆盖（上次上传中断也用 --force 重传）。")
        live = live_remote_patches(con, app_id, remote_rel["id"]) if remote_rel and a.force else []
        if live and not a.discard_patches:
            die(f"release {rv} 下已有补丁 {[p['number'] for p in live]}，"
                "而 --force 会重算基线，这些补丁的增量将全部失效。\n"
                "确认要作废它们请加 --discard-patches；否则请改用新的版本号。")

    app_bin = need(app_dir / "build/ios/iphoneos/Runner.app/Frameworks/App.framework/App",
                   "App 二进制")
    gen_snapshot = need(pathlib.Path(a.gen_snapshot or DEFAULT_GEN_SNAPSHOT), "gen_snapshot")

    # 构建模式以 App 自己的特性串为准，不以命令行为准：没加 --build 时
    # App 是谁、怎么编的我们不知道，只有它自己知道。
    split = dwarf_mode(app_bin)
    if split is None:
        die(f"读不出 {app_bin} 的 dwarf_stack_traces_mode，无法确定基线的构建模式")
    if a.split_debug_info and not split:
        die("给了 --split-debug-info，但 App 不是 --split-debug-info 构建的"
            "（特性串是 no-dwarf_stack_traces_mode）。用 --build 让 fhpb 来构建，"
            "或自己用 flutter build ios --release --split-debug-info=<目录> 重新构建。")
    if split:
        print("[release] 基线是 --split-debug-info 构建：格式排版改动不会进补丁；"
              "崩溃栈需用归档的 symbols/ 还原")

    # --force 会重算基线（App.baseline / app.dill / base.aot / base.blob），
    # 而已发布的增量是对着**旧** base.blob 算的 —— 留着它们，设备下载后
    # inflate 出来的字节对不上 hash，补丁永远装不上，且现场毫无提示。
    old_idx = {"patches": [], "rolled_back": []} if con else \
        load_json(rel / "index.json", {"patches": [], "rolled_back": []})
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
        dbg = [*DWARF_ARGS, f"--save-debugging-info={rel / 'base.aot.symbols'}"] if split else []
        r = subprocess.run([str(gen_snapshot), "--deterministic",
                            "--snapshot_kind=app-aot-elf", *dbg, f"--elf={base_aot}", str(cand)],
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

    # 重新生成的 base ELF 必须与发出去的 App 同一模式，否则链接表连错地址。
    if dwarf_mode(base_aot) != split:
        base_aot.unlink(missing_ok=True)
        die(f"重新生成的 base.aot 模式（dwarf={dwarf_mode(base_aot)}）与 App（dwarf={split}）不一致")

    shutil.copy2(app_bin, rel / "App.baseline")
    shutil.copy2(app_dill, rel / "app.dill")
    if symbols_tmp is not None:
        shutil.copytree(symbols_tmp, rel / "symbols", dirs_exist_ok=True)
        shutil.rmtree(symbols_tmp, ignore_errors=True)
    elif split:
        print("[warn] App 是 --split-debug-info 构建的，但不是 fhpb --build 编的："
              "请自行把那次构建的调试符号目录存好，线上崩溃栈要靠它还原。", file=sys.stderr)

    analyze = need(pathlib.Path(a.analyze_snapshot or DEFAULT_ANALYZE), "analyze_snapshot")
    base_blob = rel / "base.blob"
    print("[release] analyze_snapshot --dump_blobs → base.blob …")
    run([analyze, "--dump_blobs", f"--out={base_blob}", rel / "App.baseline"])

    write_json(rel / "release.json", {
        "app_id": app_id,
        "release_version": rv,
        "created_at": now_iso(),
        "platform": "ios",
        "arch": "aarch64",
        "app_baseline_sha256": console_client.sha256_file(rel / "App.baseline"),
        "app_dill_sha256": console_client.sha256_file(rel / "app.dill"),
        "app_dill_kernel_version": kernel_version(rel / "app.dill"),
        "base_blob_bytes": base_blob.stat().st_size,
        "split_debug_info": split,
    })
    idx = rel / "index.json"
    if not con and not idx.exists():
        write_json(idx, {"patches": [], "rolled_back": []})

    if con:
        publish_release_remote(con, app_id, rv, rel, a.force)

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
    h = console_client.sha256_file(vmcode)
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
    yaml_app_id = read_yaml_field(app_dir / "shorebird.yaml", "app_id")

    # 控制台模式：release 产物从服务端拉（按 sha256 缓存），工作目录替代本地仓库里的 release 目录
    con = console_for()
    remote_rel = None
    if con:
        app_id = a.app_id or yaml_app_id
        if not app_id:
            die("控制台模式需要 app_id：给 --app-id，或先 fhpb init 生成 shorebird.yaml")
        if a.app_id and yaml_app_id and a.app_id != yaml_app_id and not a.force:
            die(f"app_id 不匹配：工程是 {yaml_app_id}，--app-id 给的是 {a.app_id}。\n"
                "补丁会被发给错误的应用。确认无误请加 --force。")
        remote_rel, rel, meta = fetch_release_files(con, app_id, rv, repo)
        rv = remote_rel["version"]
    else:
        rel = release_dir(repo, rv)
        meta = load_json(need(rel / "release.json", f"release {rv}（先跑 fhpb release）"))

        # 补丁必须发给它自己那个 app。装错 app 的补丁 = 往设备推一份完全不同的
        # 快照，后果比装不上严重得多，所以这里硬拦。
        if meta.get("app_id") and yaml_app_id and yaml_app_id != meta["app_id"] and not a.force:
            die(f"app_id 不匹配：工程是 {yaml_app_id}，release {rv} 是 {meta['app_id']}。\n"
                "补丁会被发给错误的应用。确认无误请加 --force。")

    key = pathlib.Path(a.private_key).resolve() if a.private_key else None
    if key:
        need(key, "私钥")
    elif not a.unsigned:
        die("必须给 --private-key；确实要发未签名补丁请显式加 --unsigned")

    base_url = a.base_url
    if not base_url and not con:
        ycfg = app_dir / "shorebird.yaml"
        if ycfg.exists():
            for line in ycfg.read_text().splitlines():
                if line.startswith("base_url:"):
                    base_url = line.split(":", 1)[1].strip()
    if not base_url and not con:
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
    # 补丁必须与基线同一模式。旧 release.json 没有这个字段 = 普通构建。
    split = bool(meta.get("split_debug_info", False))
    env["FHP_SPLIT_DEBUG_INFO"] = "1" if split else "0"
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
    patch_aot = out_dir / "patch.aot"
    if patch_aot.exists() and dwarf_mode(patch_aot) != split:
        die(f"补丁 patch.aot 的模式（dwarf={dwarf_mode(patch_aot)}）与 release {rv}"
            f"（split_debug_info={split}）不一致，拒绝发布")
    patch_tool = need(pathlib.Path(a.patch_tool or DEFAULT_PATCH_TOOL), "patch 工具")

    if con:
        # 补丁号由服务端分配；元数据照 spec 的口子放进 metadata
        entry = publish_vmcode_remote(
            con, app_id, remote_rel, vmcode, rel / "base.blob", channel=a.channel, private_key=key,
            pub_b64=read_yaml_field(app_dir / "shorebird.yaml", "patch_public_key"), note=a.note,
            patch_tool=patch_tool, out_dir=out_dir, number=a.patch_number,
            platform=meta.get("platform", "ios"), arch=meta.get("arch", BASELINE_ARCH),
            metadata={"link%": link_pct, "split_debug_info": split, "release_version": rv,
                      "size_uncompressed": vmcode.stat().st_size, "build_host": platform.node()})
        number = entry["number"]
        where = f"服务端 {con.server}（补丁号由服务端分配）"
    else:
        idx = load_json(rel / "index.json", {"patches": [], "rolled_back": []})
        number = a.patch_number or next_patch_number(idx)
        entry = publish_vmcode(repo, rv, vmcode, number=number, base_url=base_url,
                               channel=a.channel, private_key=key, note=a.note,
                               patch_tool=patch_tool, allow_overwrite=a.force)
        if split and (out_dir / "patch.symbols").exists():
            shutil.copy2(out_dir / "patch.symbols", rel / "patches" / f"{number}.symbols")
        where = str(rel / "patches" / f"{number}.bin")

    ratio = 100 * entry["size_compressed"] / entry["size_uncompressed"]
    print(f"\n[patch] #{entry['number']} → {where}\n"
          f"        release  {rv}   channel {entry['channel']}\n"
          f"        link%    {link_pct}\n"
          f"        增量     {entry['size_compressed']:,} B / "
          f"{entry['size_uncompressed']:,} B ({ratio:.1f}%)\n"
          f"        sha256   {entry['hash']}\n"
          f"        签名     {'有' if key else '无'}")
    return 0


# ---------------------------------------------------------------- list


def print_release_patches(patches: list) -> None:
    """按统一格式打印一个 release 的补丁表。patches 元素需含 number/channel/rolled/size/created_at/note。"""
    live = [p for p in patches if not p["rolled"]]
    latest = live[-1]["number"] if live else None
    print(f"  {'补丁':<5}{'通道':<9}{'状态':<8}{'增量':>12}  创建时间")
    for p in patches:
        state = "已下线" if p["rolled"] else ("当前" if p["number"] == latest else "历史")
        print(f"  #{p['number']:<4}{p['channel']:<9}{state:<8}"
              f"{p['size']:>11,}B  {p['created_at']}" + (f"  {p['note']}" if p.get("note") else ""))


def remote_patch_rows(patches: list) -> list:
    """把服务端 ReleasePatch 列表转成 print_release_patches 要的行。"""
    rows = []
    for p in patches:
        art = p["artifacts"][0] if p["artifacts"] else {}
        rows.append({"number": p["number"], "channel": p.get("channel") or "(未晋升)",
                     "rolled": p["is_rolled_back"], "size": art.get("size", 0),
                     "created_at": art.get("created_at", "-"), "note": p.get("notes")})
    return rows


def cmd_list_remote(a, con: Console, repo: pathlib.Path) -> int:
    """控制台模式的 list：getReleases / getReleasePatches。"""
    app_ids = resolve_app_ids(a, repo, a.release_version)
    if not app_ids:
        die("拿不到 app_id：给 --app-id，或 --app-dir（读它的 shorebird.yaml）")
    shown = 0
    for app_id in app_ids:
        rels = con_call(con.releases, app_id)
        if a.release_version:
            rels = [r for r in rels if r["version"] == a.release_version]
        for r in sorted(rels, key=lambda r: r["version"]):
            shown += 1
            print(f"\nrelease {r['version']}   app_id={app_id}   建于 {r['created_at']}")
            rows = remote_patch_rows(con_call(con.patches, app_id, r["id"]))
            if not rows:
                print("  （无补丁）")
                continue
            print_release_patches(rows)
    if not shown:
        print(f"（服务端 app_id={'、'.join(app_ids)} 还没有 release）")
    return 0


def cmd_list(a) -> int:
    repo = pathlib.Path(a.repo).resolve()
    con = console_for()
    if con:
        return cmd_list_remote(a, con, repo)
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
        print_release_patches([
            {"number": p["number"], "channel": p.get("channel", "stable"),
             "rolled": p["number"] in rolled, "size": p.get("size_compressed", 0),
             "created_at": p.get("created_at", "-"), "note": p.get("note")}
            for p in idx["patches"]])
    return 0


# ---------------------------------------------------------------- rollback


def print_rollback_tail(verb: str, rolled: list, undo: bool, rows: list) -> None:
    """回滚/恢复后的说明。rows 是各补丁 {number, channel, rolled}，rolled 为当前全部下线号。"""
    if undo:
        print("服务端恢复下发它；未装的设备下次 check 即可取得。")
        return
    # 说清楚两段式：先卸载回基线，再在后续 check 里取到仍可用的最新补丁。
    # 不是「立刻落到上一个补丁」—— 中间会有一次运行在基线上。
    print(f"服务端立即停止下发它，并把 rolled_back={rolled} 带给设备。")
    print("已装该补丁的设备：下次 check 卸载它 → 先回到基线运行，"
          "再由后续 check 取得仍可用的最新补丁。")
    by_channel = {}
    for p in rows:
        if not p["rolled"]:
            by_channel[p["channel"]] = p["number"]
    if by_channel:
        print("各通道当前仍可下发：" +
              "、".join(f"{c} → #{n}" for c, n in sorted(by_channel.items())))
    else:
        print("已无可下发补丁，设备将停留在基线。")


def cmd_rollback_remote(a, con: Console, repo: pathlib.Path) -> int:
    """控制台模式的 rollback：POST rollback / rollforward。"""
    app_id = resolve_app_id(a, repo, a.release_version)
    rel = pick_remote_release(con, app_id, a.release_version)
    rv = rel["version"]
    patches = con_call(con.patches, app_id, rel["id"])
    target = next((p for p in patches if p["number"] == a.patch), None)
    if target is None:
        die(f"release {rv} 里没有补丁 #{a.patch}（现有：{[p['number'] for p in patches] or '无'}）")
    if a.undo:
        if not con_call(con.rollforward, app_id, rel["id"], target["id"]):
            print(f"补丁 #{a.patch} 本来就没下线，无需操作")
            return 0
        verb = "已恢复"
    else:
        if not con_call(con.rollback, app_id, rel["id"], target["id"]):
            print(f"补丁 #{a.patch} 已是下线状态")
            return 0
        verb = "已下线"
    print(f"补丁 #{a.patch} {verb}（release {rv}）")
    fresh = remote_patch_rows(con_call(con.patches, app_id, rel["id"]))
    print_rollback_tail(verb, [p["number"] for p in fresh if p["rolled"]], a.undo, fresh)
    return 0


def cmd_rollback(a) -> int:
    repo = pathlib.Path(a.repo).resolve()
    con = console_for()
    if con:
        return cmd_rollback_remote(a, con, repo)
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
    print_rollback_tail(verb, idx["rolled_back"], a.undo,
                        [{"number": p["number"], "channel": p.get("channel", "stable"),
                          "rolled": p["number"] in rolled} for p in idx["patches"]])
    return 0


# ---------------------------------------------------------------- verify


def find_public_key(cli_key: Optional[str], app_dir) -> Optional[str]:
    """公钥来源：命令行 > app 的 shorebird.yaml（端上信任根就是它）> 仓库自带的 keys 目录。"""
    if cli_key:
        return cli_key
    if app_dir:
        ycfg = pathlib.Path(app_dir) / "shorebird.yaml"
        if ycfg.exists():
            for line in ycfg.read_text().splitlines():
                if line.startswith("patch_public_key:"):
                    return line.split(":", 1)[1].strip()
    keyfile = REPO_ROOT / "tools/broute/keys/patch_public_key.b64"
    return keyfile.read_text().strip() if keyfile.exists() else None


def verify_entry(entry: dict, delta: Optional[pathlib.Path], pub_b64: Optional[str],
                 vmcode: Optional[pathlib.Path], label: str, delta_size: Optional[int] = None) -> int:
    """按设备侧规则复核一个补丁条目（增量存在与大小、验签、可选的 .vmcode hash），返回未通过项数。

    entry 需含 hash，可含 hash_signature / size_compressed。delta 为 None 时用 delta_size 比大小。
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.exceptions import InvalidSignature

    fails = 0

    def check(ok: bool, what: str, detail: str = "") -> None:
        nonlocal fails
        print(f"  {'✓' if ok else '✗'} {what}{('  ' + detail) if detail else ''}")
        if not ok:
            fails += 1

    print(f"校验 {label}")
    if delta is not None:
        check(delta.exists(), "增量文件存在", str(delta))
        if delta.exists():
            delta_size = delta.stat().st_size
    if delta_size is not None:
        check(delta_size == entry.get("size_compressed"),
              "增量大小与登记一致", f"{delta_size:,} B")

    sig = entry.get("hash_signature")
    if not sig:
        check(False, "补丁已签名", "没有 hash_signature")
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

    if vmcode:
        check(console_client.sha256_file(vmcode) == entry["hash"], "hash 匹配给定的 .vmcode")
    return fails


def cmd_verify_remote(a, con: Console, repo: pathlib.Path) -> int:
    """控制台模式的 verify：补丁产物的签名不在 API 里，所以走设备协议 check 取设备会收到的那一份来复核。"""
    app_id = resolve_app_id(a, repo, a.release_version)
    rel = pick_remote_release(con, app_id, a.release_version)
    patches = [p for p in con_call(con.patches, app_id, rel["id"]) if p["artifacts"]]
    number = a.patch or max((p["number"] for p in patches), default=None)
    if number is None:
        die(f"release {rel['version']} 下没有补丁")
    target = next((p for p in patches if p["number"] == number), None)
    if target is None:
        die(f"release {rel['version']} 里没有补丁 #{number}")
    art = target["artifacts"][0]
    ans = con_call(con.device_check, {
        "app_id": app_id, "release_version": rel["version"], "platform": art["platform"], "arch": art["arch"],
        "channel": target.get("channel") or "stable", "client_id": "fhpb-verify"})
    got = ans.get("patch") if ans.get("patch_available") else None
    if got is None or got["number"] != number:
        die(f"补丁 #{number} 不是通道 {target.get('channel') or '(未晋升)'} 当前下发的那个"
            "（已下线、被更新的补丁取代或未晋升），无法经设备路径复核")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="fhpb_verify_"))
    try:
        dest = tmp / f"{number}.bin"
        con_call(con.download, got["download_url"], dest)
        entry = {"hash": got["hash"], "hash_signature": got.get("hash_signature"),
                 "size_compressed": art["size"]}
        vm = pathlib.Path(a.vmcode) if a.vmcode else None
        fails = verify_entry(entry, dest, find_public_key(a.public_key, a.app_dir), vm,
                             f"release {rel['version']} 补丁 #{number}（服务端 {con.server}）")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'全部通过' if fails == 0 else str(fails) + ' 项未通过'}")
    print("注意：增量 inflate 还原只能在设备上验，本地无 inflate 实现。")
    return 0 if fails == 0 else 1


def cmd_verify(a) -> int:
    """按设备侧的校验规则复核一个已发布的补丁。

    覆盖设备会做的三件事里的两件：签名验签、hash 比对。
    第三件（inflate 增量还原出 .vmcode）需要 Shorebird 的 inflate 实现，
    本地没有对应工具，只能在设备上验 —— 见 docs/RUNBOOK_ROUTE_B.md 的验证边界。
    """
    repo = pathlib.Path(a.repo).resolve()
    con = console_for()
    if con:
        return cmd_verify_remote(a, con, repo)
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

    vm = need(pathlib.Path(a.vmcode), ".vmcode") if a.vmcode else None
    fails = verify_entry(entry, rel / "patches" / f"{number}.bin", find_public_key(a.public_key, a.app_dir),
                         vm, f"release {rv} 补丁 #{number}")
    print(f"\n{'全部通过' if fails == 0 else str(fails) + ' 项未通过'}")
    print("注意：增量 inflate 还原只能在设备上验，本地无 inflate 实现。")
    return 0 if fails == 0 else 1


# ---------------------------------------------------------------- console


def warn_plain_http(server: str) -> None:
    """明文 http 且不是本机回环时提醒：API key 会明文过网。"""
    u = urllib.parse.urlsplit(server)
    if u.scheme == "http" and u.hostname not in ("127.0.0.1", "localhost", "::1"):
        print("[warn] 服务地址是明文 http，API key 会在网络上明文传输；公网请用 https。", file=sys.stderr)


def cmd_console_login(a) -> int:
    """保存 server 地址与 API key（先调一次 API 验证能用，再落盘 0600）。"""
    server = a.server.rstrip("/")
    if not server.startswith(("http://", "https://")):
        die("--server 须以 http:// 或 https:// 开头")
    key = a.api_key or os.environ.get(console_client.KEY_ENV) or getpass.getpass("API key: ").strip()
    if not key.startswith(console_client.KEY_PREFIX):
        die(f"API key 应以 {console_client.KEY_PREFIX} 开头")
    keys = con_call(Console(server, key).whoami_keys)
    warn_plain_http(server)
    path = console_client.save_config(server, key)
    print(f"[console] key 可用（该账号现有 {len(keys)} 把 key），已保存到 {path}（权限 0600）")
    return 0


def cmd_console_create_key(a) -> int:
    """用当前凭据在服务端签发一把新 API key，明文只显示这一次，默认存为当前配置。

    第一把 key 要在服务器本机用 `python -m app create-key` 签发（没有任何 key 时没有鉴权可用）。
    """
    cfg = console_client.resolve()
    server = (a.server or (cfg[0] if cfg else None))
    key = a.api_key or (cfg[1] if cfg else None)
    if not (server and key):
        die("没有可用凭据：先 fhpb console login，或给 --server 与 --api-key。"
            "第一把 key 请在服务器本机 python -m app create-key 签发。")
    days = None if a.never_expires else a.expires_in_days
    res = con_call(Console(server, key).create_key, a.name, days)
    print(f"key id={res['id']} name={res['name']}，明文只显示这一次：\n{res['api_key']}")
    if not a.no_save:
        path = console_client.save_config(server, res["api_key"])
        print(f"[console] 已存为当前配置 {path}（旧 key 仍有效，不用时请在控制台吊销）")
    return 0


def cmd_console_import(a) -> int:
    """导入旧补丁仓库：直接调服务端的 `python -m app.importer`（导入后自证新旧答复逐字节相同）。

    不包成 API：导入要保留旧补丁号、回滚次序、高水位占位和原下载地址，
    这些公开 API 都表达不了；走同一份导入代码，自证逻辑也不会有第二份。
    """
    server_dir = a.server_dir or os.environ.get("FHPB_SERVER_DIR")
    if not server_dir:
        die("须给 --server-dir（服务端代码目录，含 app/ 包）或设环境变量 FHPB_SERVER_DIR")
    server_dir = need(pathlib.Path(server_dir).resolve(), "服务端代码目录")
    cmd = [a.python or sys.executable, "-m", "app.importer",
           "--repo", str(pathlib.Path(a.repo).resolve()), "--data-dir", str(pathlib.Path(a.data_dir).resolve())]
    if a.app_id:
        cmd += ["--app-id", a.app_id]
    return subprocess.call(cmd, cwd=server_dir)


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
    p.add_argument("--split-debug-info", action="store_true",
                   help="用 --split-debug-info 构建基线：只改格式排版不再产生补丁；"
                        "调试符号归档到 releases/<版本>/symbols，崩溃栈靠它还原")
    p.add_argument("--app-dill", default=None, help="指定基线 kernel，默认自动挑选并校验")
    p.add_argument("--analyze-snapshot", default=None)
    p.add_argument("--gen-snapshot", default=None)
    p.add_argument("--force", action="store_true", help="覆盖同名 release")
    p.add_argument("--discard-patches", action="store_true",
                   help="配合 --force：作废该 release 下已发布的补丁（基线变了它们必然失效）")
    p.add_argument("--app-id", default=None, help="控制台模式：指定 App，默认读 --app-dir 的 shorebird.yaml 或本地仓库记录")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("patch", help="生成、签名并发布一个补丁")
    p.add_argument("--app-dir", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--source-dir", default=None, help="含改动后 lib/ 的目录，默认同 --app-dir")
    p.add_argument("--release-version", default=None)
    p.add_argument("--patch-number", type=int, default=None, help="默认自增（控制台模式由服务端分配，不接受）")
    p.add_argument("--app-id", default=None, help="控制台模式：指定 App，默认读 --app-dir 的 shorebird.yaml 或本地仓库记录")
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
    p.add_argument("--app-dir", default=None, help="控制台模式：从它的 shorebird.yaml 取 app_id")
    p.add_argument("--app-id", default=None, help="控制台模式：指定 App，默认读 --app-dir 的 shorebird.yaml 或本地仓库记录")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("rollback", help="下线某个补丁")
    p.add_argument("--repo", required=True)
    p.add_argument("--patch", type=int, required=True)
    p.add_argument("--release-version", default=None)
    p.add_argument("--undo", action="store_true", help="撤销下线")
    p.add_argument("--app-dir", default=None, help="控制台模式：从它的 shorebird.yaml 取 app_id")
    p.add_argument("--app-id", default=None, help="控制台模式：指定 App，默认读 --app-dir 的 shorebird.yaml 或本地仓库记录")
    p.set_defaults(func=cmd_rollback)

    p = sub.add_parser("verify", help="按设备侧规则复核已发布的补丁")
    p.add_argument("--repo", required=True)
    p.add_argument("--release-version", default=None)
    p.add_argument("--patch", type=int, default=None, help="默认最新一个")
    p.add_argument("--app-dir", default=None, help="从它的 shorebird.yaml 取公钥")
    p.add_argument("--public-key", default=None, help="base64 DER SPKI")
    p.add_argument("--vmcode", default=None, help="比对 hash 用")
    p.add_argument("--app-id", default=None, help="控制台模式：指定 App，默认读 --app-dir 的 shorebird.yaml 或本地仓库记录")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("serve", help="起分发服务端")
    p.add_argument("--repo", required=True)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--bind", default="0.0.0.0")
    p.add_argument("--app-id", default=None)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("console", help="控制台：login / create-key / import")
    csub = p.add_subparsers(dest="console_cmd", required=True)
    c = csub.add_parser("login", help="保存 server 地址与 API key")
    c.add_argument("--server", required=True, help="控制台地址，如 https://hot.example.com")
    c.add_argument("--api-key", default=None, help="sb_api_ 开头；省略则读 FHPB_API_KEY 或交互输入")
    c.set_defaults(func=cmd_console_login)
    c = csub.add_parser("create-key", help="用当前凭据签发新 API key（明文只显示一次）")
    c.add_argument("--name", required=True)
    c.add_argument("--expires-in-days", type=int, default=365)
    c.add_argument("--never-expires", action="store_true")
    c.add_argument("--no-save", action="store_true", help="只打印，不存为当前配置")
    c.add_argument("--server", default=None)
    c.add_argument("--api-key", default=None)
    c.set_defaults(func=cmd_console_create_key)
    c = csub.add_parser("import", help="导入旧补丁仓库到服务端（调服务端 app.importer）")
    c.add_argument("--repo", required=True)
    c.add_argument("--data-dir", required=True, help="服务端数据目录")
    c.add_argument("--server-dir", default=None, help="服务端代码目录，默认读 FHPB_SERVER_DIR")
    c.add_argument("--python", default=None, help="跑服务端代码的 Python，默认当前解释器")
    c.add_argument("--app-id", default=None)
    c.set_defaults(func=cmd_console_import)

    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
