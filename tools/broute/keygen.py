#!/usr/bin/env python3
"""生成补丁签名用的 RSA 密钥对。

实现在 cli.py 的 gen_keypair()，这里只是保留旧入口。新流程直接用：
    tools/fhpb init --app-dir <工程> --base-url <url>

更新器要求（third_party/updater/library/src/cache/signing.rs:37）：
  算法      RSA_PKCS1_2048_8192_SHA256
  公钥      base64(DER SPKI)，写进 shorebird.yaml 的 patch_public_key
  签名对象  补丁解压后文件的 hex sha256 **字符串**
  签名      base64(PKCS#1 v1.5 SHA-256)
"""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from cli import gen_keypair  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tools/broute/keys", help="输出目录")
    a = ap.parse_args()

    d = pathlib.Path(a.out)
    b64 = gen_keypair(d)

    print(f"私钥  {d/'patch_private.pem'}  （勿提交）")
    print(f"公钥  {d/'patch_public.pem'}")
    print(f"\nshorebird.yaml 里加：\npatch_public_key: {b64}")


if __name__ == "__main__":
    main()
