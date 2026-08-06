#!/usr/bin/env python3
"""Extract the four Dart AOT snapshot regions from a Mach-O `App` binary and
concatenate them into a single "diff base" blob.

This is our own, dependency-free replacement for Shorebird's closed
`analyze_snapshot --dump_blobs`. It does NOT try to be byte-identical with
Shorebird's output; it only has to be *deterministic* and produce the same
bytes on the host (when generating a patch) and on the device (when applying
one).

Region order matches Shorebird's dump_blobs (empirically verified):
    1. kDartVmSnapshotData
    2. kDartIsolateSnapshotData
    3. kDartVmSnapshotInstructions
    4. kDartIsolateSnapshotInstructions

Region sizing rules:
  * instructions regions are self-describing: the first 8 bytes of the image
    are its little-endian byte length.
  * data regions are *not* self-describing, so we take the span from the
    symbol to the start of the next region / end of its section (i.e. we keep
    the alignment padding). That is fine for diffing as long as both sides use
    the same rule.

Usage:
    python3 extract_blobs.py <path/to/App> <path/to/out.blob> [--json]
"""

from __future__ import annotations

import json
import struct
import subprocess
import sys

SYMBOLS = [
    "_kDartVmSnapshotData",
    "_kDartIsolateSnapshotData",
    "_kDartVmSnapshotInstructions",
    "_kDartIsolateSnapshotInstructions",
]

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
MH_MAGIC_64 = 0xFEEDFACF


def slice_offset(data: bytes, arch: str = "arm64") -> int:
    """Return the file offset of the requested arch slice (0 for thin files)."""
    magic = struct.unpack(">I", data[:4])[0]
    if magic not in (FAT_MAGIC, FAT_MAGIC_64):
        return 0
    nfat = struct.unpack(">I", data[4:8])[0]
    entry_size = 20 if magic == FAT_MAGIC else 32
    for i in range(nfat):
        base = 8 + i * entry_size
        cputype, cpusub = struct.unpack(">ii", data[base : base + 8])
        if magic == FAT_MAGIC:
            off = struct.unpack(">I", data[base + 8 : base + 12])[0]
        else:
            off = struct.unpack(">Q", data[base + 8 : base + 16])[0]
        # CPU_TYPE_ARM64 == 0x0100000C
        if arch == "arm64" and cputype == 0x0100000C:
            return off
        if arch == "x86_64" and cputype == 0x01000007:
            return off
    raise SystemExit(f"arch {arch} not found in fat binary")


def symbol_offsets(path: str, arch: str = "arm64") -> dict[str, int]:
    out = subprocess.run(
        ["nm", "-arch", arch, "-g", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    result: dict[str, int] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] in SYMBOLS:
            result[parts[2]] = int(parts[0], 16)
    missing = [s for s in SYMBOLS if s not in result]
    if missing:
        raise SystemExit(f"missing Dart snapshot symbols: {missing}")
    return result


def section_bounds(path: str, arch: str = "arm64") -> list[tuple[str, int, int]]:
    """Return [(segname.sectname, fileoff, size)] from otool -l."""
    out = subprocess.run(
        ["otool", "-arch", arch, "-l", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    sections: list[tuple[str, int, int]] = []
    sect = seg = None
    size = off = None
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


def region_end(start: int, sections: list[tuple[str, int, int]]) -> int:
    """End (exclusive, slice-relative) of the section containing `start`."""
    for _, off, size in sections:
        if off <= start < off + size:
            return off + size
    raise SystemExit(f"offset {hex(start)} is not inside any section")


def extract(path: str, arch: str = "arm64"):
    raw = open(path, "rb").read()
    base = slice_offset(raw, arch)
    syms = symbol_offsets(path, arch)
    sections = section_bounds(path, arch)

    # Sorted symbol offsets let us find each region's neighbour.
    ordered = sorted(syms.values())

    regions = []
    for name in SYMBOLS:
        start = syms[name]
        if name.endswith("Instructions"):
            # self-describing length in the first 8 bytes of the image
            length = struct.unpack("<Q", raw[base + start : base + start + 8])[0]
        else:
            nxt = next((o for o in ordered if o > start), None)
            end = region_end(start, sections)
            if nxt is not None and nxt < end:
                end = nxt
            length = end - start
        regions.append((name, start, length))
    return raw, base, regions


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    app, out = argv[1], argv[2]
    arch = "arm64"
    raw, base, regions = extract(app, arch)

    blob = bytearray()
    manifest = []
    for name, start, length in regions:
        manifest.append(
            {
                "symbol": name,
                "file_offset": base + start,
                "blob_offset": len(blob),
                "length": length,
            }
        )
        blob += raw[base + start : base + start + length]

    with open(out, "wb") as f:
        f.write(blob)

    if "--json" in argv:
        print(json.dumps({"blob_size": len(blob), "regions": manifest}, indent=2))
    else:
        for m in manifest:
            print(
                f"{m['symbol']:<38} blob@0x{m['blob_offset']:08x} "
                f"len={m['length']} (0x{m['length']:x})"
            )
        print(f"wrote {out} ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
