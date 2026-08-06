"""
patch_builder.py - Assemble and sign a flutter_hot_patcher patch bundle.
"""
import argparse, hashlib, io, json, os, shutil, tarfile
import zstandard
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

ZSTD_MAGIC = "fd2fb528"

def canonical_bytes(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")

def _sha256_file(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()

def _create_bundle_tar_zst(bundle_dir, output_dir):
    zst_path = os.path.join(output_dir, "bundle.zst")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        tar.add(bundle_dir, arcname="bundle")
    cctx = zstandard.ZstdCompressor(level=3)
    compressed = cctx.compress(buf.getvalue())
    with open(zst_path, "wb") as f:
        f.write(compressed)
    return zst_path

def build_bundle(linker_output_dir, bytecode_path, private_key_path,
                 patch_id, app_version, platform, output_dir,
                 channel="stable", patch_number=1, pointers_json_path=None):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.join(output_dir, "bytecode"), exist_ok=True)

    with open(os.path.join(linker_output_dir, "manifest.json")) as f:
        linker_manifest = json.load(f)

    dill_dest = os.path.join(output_dir, "bytecode", "patch.dill")
    shutil.copy2(bytecode_path, dill_dest)

    entry_table_dest = os.path.join(output_dir, "entry_table.bin")
    shutil.copy2(os.path.join(linker_output_dir, "entry_table.bin"), entry_table_dest)

    cid_map_dest = os.path.join(output_dir, "cid_map.bin")
    shutil.copy2(os.path.join(linker_output_dir, "cid_map.bin"), cid_map_dest)

    with open(private_key_path, "rb") as f:
        private_key = load_pem_private_key(f.read(), None)

    artifacts = [
        {"path": "bytecode/patch.dill", "sha256": _sha256_file(dill_dest), "size": os.path.getsize(dill_dest)},
        {"path": "entry_table.bin", "sha256": _sha256_file(entry_table_dest), "size": os.path.getsize(entry_table_dest)},
        {"path": "cid_map.bin", "sha256": _sha256_file(cid_map_dest), "size": os.path.getsize(cid_map_dest)},
    ]

    if pointers_json_path and os.path.exists(pointers_json_path):
        pointers_dest = os.path.join(output_dir, "pointers.json")
        shutil.copy2(pointers_json_path, pointers_dest)
        artifacts.append({"path": "pointers.json", "sha256": _sha256_file(pointers_dest), "size": os.path.getsize(pointers_dest)})

    manifest = {
        "format_version": linker_manifest.get("format_version", "1"),
        "dart_sdk_commit": linker_manifest.get("dart_sdk_commit", "unknown"),
        "baseline_sha256": linker_manifest.get("baseline_sha256", ""),
        "changed_functions": linker_manifest.get("changed_functions", []),
        "icf_affected": linker_manifest.get("icf_affected", []),
        "affected_closure": linker_manifest.get("affected_closure", []),
        "class_hierarchy_changed": linker_manifest.get("class_hierarchy_changed", False),
        "class_hierarchy": linker_manifest.get("class_hierarchy", {}),
        "patch_id": patch_id,
        "patch_version": 1,
        "patch_number": patch_number,
        "channel": channel,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "payload_type": "bytecode",
        "target_build_fingerprint": app_version,
        "sig_anchor_key_id": f"anchor-{patch_id}",
        "sig_alg": "ed25519",
        "cert_chain": [],
        "artifacts": artifacts,
        "vmcode_reserved": None,
        "zstd_magic": "fd2fb528",
    }

    manifest_dest = os.path.join(output_dir, "manifest.json")
    with open(manifest_dest, "w") as f:
        json.dump(manifest, f, indent=2)

    sig = private_key.sign(canonical_bytes(manifest))
    with open(os.path.join(output_dir, "manifest.sig"), "wb") as f:
        f.write(sig)

    _create_bundle_tar_zst(output_dir, output_dir)

    print(f"[patch_builder] Bundle written to {output_dir}/")

def main():
    p = argparse.ArgumentParser(description="Build and sign a patch bundle")
    p.add_argument("--manifest", required=True)
    p.add_argument("--bytecode", required=True)
    p.add_argument("--private-key", required=True)
    p.add_argument("--patch-id", required=True)
    p.add_argument("--patch-number", type=int, required=True)
    p.add_argument("--app-version", required=True)
    p.add_argument("--platform", choices=["ios", "android"], default="ios")
    p.add_argument("--channel", default="stable")
    p.add_argument("--pointers-json", default=None)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    build_bundle(
        linker_output_dir=args.manifest,
        bytecode_path=args.bytecode,
        private_key_path=args.private_key,
        patch_id=args.patch_id,
        app_version=args.app_version,
        platform=args.platform,
        output_dir=args.output_dir,
        channel=args.channel,
        patch_number=args.patch_number,
        pointers_json_path=args.pointers_json,
    )

if __name__ == "__main__":
    main()
