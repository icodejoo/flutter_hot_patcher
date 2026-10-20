#!/usr/bin/env python3
"""Bind final, non-instrumented RC9 binary outputs to archived reference files."""

import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "scratchpad/g1_rc9_keymap_20261019/membership_probe"
PREVIOUS = ROOT / "scratchpad/g1_rc9_keymap_20261019/post_fix_manifest.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = []
    for previous in json.loads(PREVIOUS.read_text()):
        name = previous["case"]
        command = previous["command"].copy()
        command[2] = f"--elf={OUT / (name + '_final.so')}"
        command[4] = f"--print_dd_resolution_to={OUT / (name + '_final.tsv')}"
        ref = (ROOT / f"scratchpad/g1_coverage_20261016/run_v2/theirs/{name}/dd"
               if name != "tie" else ROOT / "scratchpad/g1_rc9_tie_20261019/forward_ref")
        started = time.time_ns()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        ended = time.time_ns()
        (OUT / f"{name}_final.stdout").write_bytes(stdout)
        (OUT / f"{name}_final.stderr").write_bytes(stderr)
        row = {"case": name, "pid": process.pid, "started_ns": started,
               "ended_ns": ended, "command": command, "rc": process.returncode,
               "sha256": {"binary": sha(Path(command[0])), "kernel": sha(Path(command[-1])),
                          "voters": sha(Path(command[3].split("=", 1)[1])),
                          "stdout": sha(OUT / f"{name}_final.stdout"),
                          "stderr": sha(OUT / f"{name}_final.stderr"),
                          "elf": sha(OUT / f"{name}_final.so"),
                          "tsv": sha(OUT / f"{name}_final.tsv"),
                          "reference_stderr": sha(ref / "stderr.log") if name != "tie" else None,
                          "reference_tsv": sha(ref / "resolution.tsv")},
               "stderr_matches_reference": (OUT / f"{name}_final.stderr").read_bytes() == (ref / "stderr.log").read_bytes()
               if name != "tie" else None,
               "tsv_matches_reference": (OUT / f"{name}_final.tsv").read_bytes() == (ref / "resolution.tsv").read_bytes()}
        rows.append(row)
        print(name, process.returncode, row["stderr_matches_reference"],
              row["tsv_matches_reference"], flush=True)
        assert process.returncode == 0 and row["tsv_matches_reference"]
        assert row["stderr_matches_reference"] is not False
    (OUT / "final_manifest.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
