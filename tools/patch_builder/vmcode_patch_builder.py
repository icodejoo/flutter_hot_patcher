"""
vmcode_patch_builder.py - Build a B-route vmcode patch.

Extracts IsolateSnapshotData from base and patched App binaries, generates
a zstd-wrapped bipatch diff (.vmdiff) consumable by fhp_vmcode_stage().

Usage:
    python3 vmcode_patch_builder.py \
        --base-app    path/to/baseline/App \
        --patch-app   path/to/patched/App \
        --patch-number 1 \
        --output-dir  patches/1.0+1/vmcode-v1/
"""
import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile

SHOREBIRD_PATCH = os.path.expanduser(
    "~/.shorebird/bin/cache/artifacts/patch/patch"
)

SYMBOLS = [
    "_kDartVmSnapshotData",
    "_kDartIsolateSnapshotData",
    "_kDartVmSnapshotInstructions",
    "_kDartIsolateSnapshotInstructions",
]

FAT_MAGIC    = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF


def slice_offset(data: bytes, arch: str = "arm64") -> int:
    magic = struct.unpack(">I", data[:4])[0]
    if magic not in (FAT_MAGIC, FAT_MAGIC_64):
        return 0
    nfat = struct.unpack(">I", data[4:8])[0]
    entry_size = 20 if magic == FAT_MAGIC else 32
    for i in range(nfat):
        base = 8 + i * entry_size
        cputype, _ = struct.unpack(">ii", data[base : base + 8])
        off = (
            struct.unpack(">I", data[base + 8 : base + 12])[0]
            if magic == FAT_MAGIC
            else struct.unpack(">Q", data[base + 8 : base + 16])[0]
        )
        if arch == "arm64" and cputype == 0x0100000C:
            return off
        if arch == "x86_64" and cputype == 0x01000007:
            return off
    raise SystemExit(f"arch {arch} not found in fat binary")


def symbol_offsets(path: str, arch: str = "arm64") -> dict:
    out = subprocess.run(
        ["nm", "-arch", arch, "-g", path],
        capture_output=True, text=True, check=True,
    ).stdout
    result = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in SYMBOLS:
            result[parts[2]] = int(parts[0], 16)
    missing = [s for s in SYMBOLS if s not in result]
    if missing:
        raise SystemExit(f"missing Dart snapshot symbols: {missing}")
    return result


def section_bounds(path: str, arch: str = "arm64"):
    out = subprocess.run(
        ["otool", "-arch", arch, "-l", path],
        capture_output=True, text=True, check=True,
    ).stdout
    sections = []
    sect = seg = size = off = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("sectname "):
            sect = line.split()[1]
        elif line.startswith("segname "):
            seg = line.split()[1]
        elif line.startswith("size ") and sect is not None:
            size = int(line.split()[1], 16)
        elif line.startswith("offset ") and sect is not None:
            off = int(line.split()[1])
            sections.append((f"{seg}.{sect}", off, size))
            sect = seg = size = off = None
    return sections


def vm_to_file_slide(path: str, arch: str = "arm64") -> int:
    """Return (vm_base - file_base) for the __TEXT segment so we can convert
    nm virtual addresses to file offsets: file_off = vm_addr - slide."""
    out = subprocess.run(
        ["otool", "-arch", arch, "-l", path],
        capture_output=True, text=True, check=True,
    ).stdout
    in_text = False
    vmaddr = fileoff = None
    for line in out.splitlines():
        line = line.strip()
        if "segname __TEXT" in line:
            in_text = True
            vmaddr = fileoff = None
        elif in_text:
            if line.startswith("vmaddr "):
                vmaddr = int(line.split()[1], 16)
            elif line.startswith("fileoff "):
                fileoff = int(line.split()[1])
            elif line.startswith("cmd ") or line.startswith("Section") or                  (vmaddr is not None and fileoff is not None):
                if vmaddr is not None and fileoff is not None:
                    return vmaddr - fileoff
                in_text = False
    return 0


def region_end(start: int, sections) -> int:
    for _, off, size in sections:
        if off <= start < off + size:
            return off + size
    raise SystemExit(f"offset {hex(start)} is not inside any section")


def extract_isolate_data(app_path: str, arch: str = "arm64") -> bytes:
    """Return raw bytes of the _kDartIsolateSnapshotData region."""
    raw = open(app_path, "rb").read()
    fat_base = slice_offset(raw, arch)
    syms = symbol_offsets(app_path, arch)
    sections = section_bounds(app_path, arch)

    # Convert nm virtual addresses to file offsets.
    # For dylibs (base addr 0) slide==0; for executables slide==vm_base-file_base.
    slide = vm_to_file_slide(app_path, arch)
    file_syms = {k: v - slide for k, v in syms.items()}

    ordered = sorted(file_syms.values())
    start = file_syms["_kDartIsolateSnapshotData"]
    nxt = next((o for o in ordered if o > start), None)
    end = region_end(start, sections)
    if nxt is not None and nxt < end:
        end = nxt
    length = end - start
    return raw[fat_base + start : fat_base + start + length]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def gen_diff(base_path: str, patch_path: str, out_path: str):
    """Run Shorebird patch tool → produces zstd(bipatch_stream)."""
    if not os.path.isfile(SHOREBIRD_PATCH):
        raise SystemExit(f"Shorebird patch tool not found: {SHOREBIRD_PATCH}")
    subprocess.run([SHOREBIRD_PATCH, base_path, patch_path, out_path], check=True)


def verify_instructions_identical(base_app: str, patch_app: str, arch: str = "arm64") -> bool:
    """Warn if instruction regions differ (data-only patch assumption)."""
    raw_b = open(base_app, "rb").read()
    raw_p = open(patch_app, "rb").read()
    base_b = slice_offset(raw_b, arch)
    base_p = slice_offset(raw_p, arch)
    syms_b = symbol_offsets(base_app, arch)
    syms_p = symbol_offsets(patch_app, arch)

    for sym in ("_kDartVmSnapshotInstructions", "_kDartIsolateSnapshotInstructions"):
        sb = syms_b[sym]; sp = syms_p[sym]
        try:
            lb = struct.unpack("<Q", raw_b[base_b + sb : base_b + sb + 8])[0]
            lp = struct.unpack("<Q", raw_p[base_p + sp : base_p + sp + 8])[0]
        except struct.error:
            # assembly-embedded format lacks size prefix; skip check
            print(f"[INFO] {sym}: size prefix not found (assembly-embedded format), skipping check")
            continue
        bb = raw_b[base_b + sb : base_b + sb + lb]
        bp = raw_p[base_p + sp : base_p + sp + lp]
        if bb != bp:
            print(f"[WARNING] {sym} differs — instruction change detected.")
            print("  iOS W^X blocks PROT_EXEC on app-container files.")
            print("  B-route Phase 1 only supports data-only patches (string/constant changes).")
            return False
    return True


def build_vmcode_patch(base_app, patch_app, patch_number, output_dir, force=False,
                       release_version="1.0+1", channel="stable"):
    os.makedirs(output_dir, exist_ok=True)

    print("[vmcode_builder] Verifying instruction regions...")
    data_only = verify_instructions_identical(base_app, patch_app)
    if not data_only and not force:
        ans = input("Instruction regions differ. Continue anyway? [y/N] ").strip().lower()
        if ans != "y":
            raise SystemExit("Aborted.")

    print("[vmcode_builder] Extracting IsolateSnapshotData...")
    base_iso  = extract_isolate_data(base_app)
    patch_iso = extract_isolate_data(patch_app)
    print(f"  base:  {len(base_iso)} bytes  sha256={sha256_bytes(base_iso)[:16]}...")
    print(f"  patch: {len(patch_iso)} bytes  sha256={sha256_bytes(patch_iso)[:16]}...")

    with tempfile.TemporaryDirectory() as tmp:
        base_path  = os.path.join(tmp, "base.bin")
        patch_path = os.path.join(tmp, "patch.bin")
        diff_tmp   = os.path.join(tmp, "isolate_data.vmdiff")

        open(base_path,  "wb").write(base_iso)
        open(patch_path, "wb").write(patch_iso)

        print("[vmcode_builder] Generating bipatch diff via Shorebird patch tool...")
        gen_diff(base_path, patch_path, diff_tmp)

        diff_bytes = open(diff_tmp, "rb").read()

    diff_out = os.path.join(output_dir, "isolate_data.vmdiff")
    open(diff_out, "wb").write(diff_bytes)
    ratio = len(diff_bytes) / max(len(patch_iso), 1) * 100
    print(f"  diff:  {len(diff_bytes)} bytes ({ratio:.1f}% of patched region)")

    manifest = {
        "format_version": "1",
        "patch_type":      "vmcode",
        "patch_number":    patch_number,
        "channel":         channel,
        "release_version": release_version,
        "isolate_data_size": len(base_iso),
        "base_sha256":     sha256_bytes(base_iso),
        "patch_sha256":    sha256_bytes(patch_iso),
        "diff_sha256":     sha256_bytes(diff_bytes),
        "diff_size":       len(diff_bytes),
    }
    manifest_path = os.path.join(output_dir, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"[vmcode_builder] Done → {output_dir}/")
    print(f"  manifest.json  isolate_data.vmdiff")
    return manifest


def main():
    p = argparse.ArgumentParser(description="Build a B-route vmcode patch")
    p.add_argument("--base-app",        required=True,  help="Path to baseline App (Mach-O)")
    p.add_argument("--patch-app",       required=True,  help="Path to patched App (Mach-O)")
    p.add_argument("--patch-number",    type=int, required=True)
    p.add_argument("--release-version", default="1.0+1")
    p.add_argument("--channel",         default="stable")
    p.add_argument("--output-dir",      required=True)
    p.add_argument("--force", action="store_true", help="跳过指令区域检查警告")
    args = p.parse_args()
    build_vmcode_patch(
        base_app=args.base_app,
        patch_app=args.patch_app,
        patch_number=args.patch_number,
        output_dir=args.output_dir,
        release_version=args.release_version,
        channel=args.channel,
        force=args.force,
    )


if __name__ == "__main__":
    main()
