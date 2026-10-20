#!/usr/bin/env python3
"""Probe first/second DD key-map membership with valid, grouped target votes."""

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "scratchpad/g1_rc9_keymap_20261019/membership_probe"
SDK = Path("/Users/Cruz/dart-3122/sdk")
RESEARCH = Path("/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle")
BINARIES = {
    "ours": SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot",
    "ref": RESEARCH / "bin/gen_snapshot.arm64",
}
KERNELS = {"hello": RESEARCH / "out_verify/hello.dill", "prog": RESEARCH / "out_disas/prog.dill"}
# An absent caller prevents any candidate from becoming a slot winner.
# This forces every target to be scored without linking uncompiled Code.
ANCHORS = {"hello": (0xDEADBEEF, 0, 0, 0, 0),
           "prog": (0xDEADBEEF, 0, 0, 0, 0)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unsigned(value):
    assert value >= 0
    data = bytearray()
    while value >= 128:
        data.append(value & 127)
        value >>= 7
    data.append(value | 128)
    return data


def read_maps(name):
    blocks = (OUT / f"{name}.keys").read_text().split("BEGIN ")[1:]
    assert len(blocks) == 2
    result = []
    for block in blocks:
        lines = block.splitlines()
        entries = {tuple(map(int, line.split()[:5])): int(line.split()[5]) for line in lines[1:]}
        assert len(entries) == int(lines[0])
        result.append(entries)
    return result


def write_voters(path, anchor, targets):
    data = bytearray.fromhex("557ecadd02000000")
    data += unsigned(len(targets))
    for slot, target in enumerate(targets):
        data += unsigned(slot)
        data += unsigned(1)
        for key in (anchor, target):
            for field in key:
                data += unsigned(field)
    path.write_bytes(data)


def main():
    results = []
    for name in ("hello", "prog"):
        first, second = read_maps(name)
        groups = {
            "first_all": sorted(first),
            "first_functions": sorted(k for k in first if k[3] != 255),
            "first_alloc": sorted(k for k in first if k[3] == 255),
            "first_method_extractors": sorted(k for k in first if k[3] == 10),
            "first_other_functions": sorted(k for k in first if k[3] != 10),
            "second_only": sorted(second.keys() - first.keys()),
            "second_all": sorted(second),
        }
        for group, keys in groups.items():
            if not keys:
                continue
            path = OUT / f"{name}_{group}.voters.bin"
            write_voters(path, ANCHORS[name], keys)
            for side, binary in BINARIES.items():
                prefix = OUT / f"{name}_{group}_{side}"
                command = [str(binary), "--snapshot_kind=app-aot-elf",
                           f"--elf={prefix}.so", f"--dd_slot_mapping={path}",
                           f"--print_dd_resolution_to={prefix}.tsv", str(KERNELS[name])]
                started = time.time_ns()
                process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           env={k: v for k, v in os.environ.items() if k != "G1_KEYMAP_DUMP"})
                stdout, stderr = process.communicate()
                ended = time.time_ns()
                Path(f"{prefix}.stdout").write_bytes(stdout)
                Path(f"{prefix}.stderr").write_bytes(stderr)
                lines = [line for line in stderr.decode(errors="replace").splitlines()
                         if "DD resolution:" in line]
                counts = [dict(zip(("target_missing", "target_ambiguous", "caller_missing", "caller_ambiguous"),
                                   map(int, re.search(r"tgt_miss=(\d+) tgt_ambig=(\d+) caller_miss=(\d+) caller_ambig=(\d+)", line).groups())))
                          for line in lines]
                row = {"case": name, "group": group, "side": side, "key_count": len(keys),
                       "pid": process.pid, "started_ns": started, "ended_ns": ended,
                       "command": command, "rc": process.returncode,
                       "sha256": {"binary": sha(binary), "kernel": sha(KERNELS[name]),
                                  "voters": sha(path), "stdout": sha(Path(f"{prefix}.stdout")),
                                  "stderr": sha(Path(f"{prefix}.stderr")),
                                  "elf": sha(Path(f"{prefix}.so")) if Path(f"{prefix}.so").exists() else None,
                                  "tsv": sha(Path(f"{prefix}.tsv")) if Path(f"{prefix}.tsv").exists() else None},
                       "counts": counts}
                results.append(row)
                (OUT / "grouped_manifest.json").write_text(json.dumps(results, indent=2) + "\n")
                print(name, group, side, len(keys), process.returncode, counts, flush=True)
                if process.returncode != 0 or len(counts) != 2:
                    raise RuntimeError(f"probe failed: {name} {group} {side}")


if __name__ == "__main__":
    main()
