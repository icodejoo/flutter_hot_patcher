#!/usr/bin/env python3
"""Recheck all archived RC9 tie cases after moving the first DD pass."""

import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INPUT = ROOT / "scratchpad/g1_rc9_tie_20261019/sweep40"
OUT = ROOT / "scratchpad/g1_rc9_keymap_20261019/membership_probe/sweep40_final"
GEN = Path("/Users/Cruz/dart-3122/sdk/xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot")
KERNEL = Path("/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle/out_verify/hello.dill")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for voter in sorted(INPUT.glob("*.bin")):
        name = voter.stem
        prefix = OUT / name
        cmd = [str(GEN), "--snapshot_kind=app-aot-elf", f"--elf={prefix}.so",
               f"--dd_slot_mapping={voter}", f"--print_dd_resolution_to={prefix}.tsv",
               str(KERNEL)]
        started = time.time_ns()
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        ended = time.time_ns()
        Path(f"{prefix}.stdout").write_bytes(stdout)
        Path(f"{prefix}.stderr").write_bytes(stderr)
        row = {"case": name, "pid": p.pid, "started_ns": started, "ended_ns": ended,
               "command": cmd, "rc": p.returncode,
               "sha256": {"binary": sha(GEN), "kernel": sha(KERNEL), "voters": sha(voter),
                          "elf": sha(Path(f"{prefix}.so")), "tsv": sha(Path(f"{prefix}.tsv")),
                          "stdout": sha(Path(f"{prefix}.stdout")),
                          "stderr": sha(Path(f"{prefix}.stderr")),
                          "reference_tsv": sha(INPUT / f"{name}.tsv"),
                          "reference_stderr": sha(INPUT / f"{name}.stderr")},
               "tsv_equal": Path(f"{prefix}.tsv").read_bytes() == (INPUT / f"{name}.tsv").read_bytes(),
               "stderr_equal": Path(f"{prefix}.stderr").read_bytes() == (INPUT / f"{name}.stderr").read_bytes()}
        rows.append(row)
        if p.returncode != 0 or not row["tsv_equal"] or not row["stderr_equal"]:
            print(name, p.returncode, row["tsv_equal"], row["stderr_equal"], flush=True)
            raise RuntimeError(f"RC9 final tie sweep mismatch: {name}")
    (OUT / "manifest.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(len(rows), "cases matched reference TSV and stderr")


if __name__ == "__main__":
    main()
