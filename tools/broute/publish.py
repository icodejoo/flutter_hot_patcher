#!/usr/bin/env python3
"""把一个 .vmcode 发布成设备可下载的补丁（旧入口）。

实现在 cli.py 的 publish_vmcode()，这里只是保留旧的命令行形状。
新流程一步到位（自己构建 .vmcode、自增补丁号、读 base_url）：

    tools/fhpb patch --app-dir <工程> --repo <仓库> --private-key <pem>

本入口只在「已经有一个现成的 .vmcode、想手工塞进仓库」时才需要。
注意它要求该 release 已经由 `fhpb release` 归档过（需要 base.blob）。
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cli  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="补丁仓库目录（服务端读取它）")
    ap.add_argument("--vmcode", required=True, help="tools/build_app_patch.sh 产出的 out.vmcode")
    ap.add_argument("--release-version", required=True, help='如 "1.0.0+1"，须与 Info.plist 一致')
    ap.add_argument("--patch-number", type=int, required=True)
    ap.add_argument("--base-url", required=True, help="设备可达的服务端地址")
    ap.add_argument("--channel", default="stable")
    ap.add_argument("--private-key", help="RSA 私钥；省略则不签名")
    ap.add_argument("--note", default=None)
    ap.add_argument("--force", action="store_true", help="允许覆盖已发布的补丁号")
    ap.add_argument("--patch-tool", default=None)
    # 兼容旧命令行：base.blob 现在由 fhpb release 产出，这里不再需要 App 二进制
    ap.add_argument("--app-binary", help=argparse.SUPPRESS)
    ap.add_argument("--analyze-snapshot", help=argparse.SUPPRESS)
    a = ap.parse_args()

    entry = cli.publish_vmcode(
        pathlib.Path(a.repo), a.release_version, pathlib.Path(a.vmcode),
        number=a.patch_number, base_url=a.base_url, channel=a.channel,
        private_key=pathlib.Path(a.private_key) if a.private_key else None,
        note=a.note,
        patch_tool=cli.need(pathlib.Path(a.patch_tool or cli.DEFAULT_PATCH_TOOL), "patch 工具"),
        allow_overwrite=a.force)

    ratio = 100 * entry["size_compressed"] / entry["size_uncompressed"]
    print(f"[publish] patch #{entry['number']} -> {a.repo}/releases/"
          f"{a.release_version}/patches/{entry['number']}.bin")
    print(f"          压缩后 {entry['size_compressed']:,} B / "
          f"解压后 {entry['size_uncompressed']:,} B ({ratio:.1f}%)")
    print(f"          sha256 {entry['hash']}")
    print(f"          签名   {'有' if a.private_key else '无（未配 --private-key）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
