#!/usr/bin/env python3
"""Repeat 40 valid tie cases on both tools with PID and file-hash binding."""

import hashlib
import json
import resource
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "scratchpad/g1_rc9_tie_20261019"
RESEARCH = Path("/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle")
KERNEL = RESEARCH / "out_verify/hello.dill"
BINARIES = {
    "ours": Path("/Users/Cruz/dart-3122/sdk/xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot"),
    "ref": RESEARCH / "bin/gen_snapshot.arm64",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def no_core():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main():
    cases = json.loads((RUN / "sweep40/results.json").read_text())
    directory = RUN / "bound"
    directory.mkdir(exist_ok=True)
    report = {
        "kernel_sha256": sha(KERNEL),
        "binaries_sha256": {side: sha(path) for side, path in BINARIES.items()},
        "runs": {},
    }
    for name in sorted(cases):
        voter = RUN / "sweep40" / f"{name}.bin"
        voter_hash = sha(voter)
        assert voter_hash == cases[name]["input_sha256"]
        case_dir = directory / name
        case_dir.mkdir(exist_ok=True)
        report["runs"][name] = {}
        for side, binary in BINARIES.items():
            elf = case_dir / f"{side}.so"
            tsv = case_dir / f"{side}.tsv"
            command = [
                str(binary), "--snapshot_kind=app-aot-elf", f"--elf={elf}",
                "--print_shorebird_info", f"--dd_slot_mapping={voter}",
                f"--print_dd_resolution_to={tsv}", str(KERNEL),
            ]
            started = time.time_ns()
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, preexec_fn=no_core)
            stdout, stderr = process.communicate()
            ended = time.time_ns()
            stdout_path = case_dir / f"{side}.stdout"
            stderr_path = case_dir / f"{side}.stderr"
            stdout_path.write_bytes(stdout)
            stderr_path.write_bytes(stderr)
            row = {
                "pid": process.pid, "started_ns": started, "ended_ns": ended,
                "command": command, "rc": process.returncode,
                "input_sha256_before": voter_hash,
                "input_sha256_after": sha(voter),
                "binary_sha256": sha(binary),
                "stdout_sha256": sha(stdout_path),
                "stderr_sha256": sha(stderr_path),
                "elf_sha256": sha(elf) if elf.exists() else None,
                "tsv_sha256": sha(tsv) if tsv.exists() else None,
            }
            report["runs"][name][side] = row
            (directory / "manifest.json").write_text(json.dumps(report, indent=2))
            if process.returncode != 0 or row["tsv_sha256"] is None:
                raise RuntimeError(f"{name}/{side}: rc={process.returncode}")
    print(json.dumps({"cases": len(report["runs"]),
                      "runs": sum(len(sides) for sides in report["runs"].values())}))


if __name__ == "__main__":
    main()
