#!/usr/bin/env python3
"""生成补丁签名用的 RSA 密钥对。

更新器要求（third_party/updater/library/src/cache/signing.rs:37）：
  算法      RSA_PKCS1_2048_8192_SHA256
  公钥      base64(DER SPKI)，写进 shorebird.yaml 的 patch_public_key
  签名对象  补丁解压后文件的 hex sha256 **字符串**
  签名      base64(PKCS#1 v1.5 SHA-256)
"""
import argparse, base64, pathlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="tools/broute/keys", help="输出目录")
    ap.add_argument("--bits", type=int, default=2048)
    a = ap.parse_args()

    d = pathlib.Path(a.out)
    d.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=a.bits)
    (d / "patch_private.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()))
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo)
    (d / "patch_public.pem").write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo))
    b64 = base64.b64encode(spki).decode()
    (d / "patch_public_key.b64").write_text(b64 + "\n")

    print(f"私钥  {d/'patch_private.pem'}  （勿提交）")
    print(f"公钥  {d/'patch_public.pem'}")
    print(f"\nshorebird.yaml 里加：\npatch_public_key: {b64}")


if __name__ == "__main__":
    main()
