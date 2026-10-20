#!/usr/bin/env python3
"""Bind valid DD-voter tie inputs to both raw tool outcomes and local tests."""

import copy
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path("/Users/Cruz/dart-3122/sdk")
RESEARCH = Path("/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle")
RUN = ROOT / "scratchpad/g1_rc9_tie_20261019"
GEN = SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot"
ANALYZER = SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/analyze_snapshot"
REF = RESEARCH / "bin/gen_snapshot.arm64"
TESTS = SDK / "xcodebuild/DebugARM64/run_vm_tests"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def winner(path):
    rows = path.read_text().splitlines()
    assert rows[-1].startswith("0\tresolved\t")
    return rows[-1].split("\t")[-1]


def bound_run_ok(name, side, row, bound):
    case = RUN / "bound" / name
    voter = RUN / "sweep40" / f"{name}.bin"
    binary = GEN if side == "ours" else REF
    kernel = RESEARCH / "out_verify/hello.dill"
    command = [str(binary), "--snapshot_kind=app-aot-elf",
               f"--elf={case / f'{side}.so'}", "--print_shorebird_info",
               f"--dd_slot_mapping={voter}",
               f"--print_dd_resolution_to={case / f'{side}.tsv'}", str(kernel)]
    return (
        row["pid"] > 0 and row["started_ns"] <= row["ended_ns"]
        and row["command"] == command and row["rc"] == 0
        and row["input_sha256_before"] == row["input_sha256_after"] == sha(voter)
        and row["binary_sha256"] == bound["binaries_sha256"][side] == sha(binary)
        and row["stdout_sha256"] == sha(case / f"{side}.stdout")
        and row["stderr_sha256"] == sha(case / f"{side}.stderr")
        and row["elf_sha256"] == sha(case / f"{side}.so")
        and row["tsv_sha256"] == sha(case / f"{side}.tsv")
    )


def main():
    initial = json.loads((RUN / "input_manifest.json").read_text())
    first_runs = json.loads((RUN / "run_manifest.json").read_text())
    refs = json.loads((RUN / "sweep40/results.json").read_text())
    ours = json.loads((RUN / "sweep40/ours_sweep40.json").read_text())
    bound = json.loads((RUN / "bound/manifest.json").read_text())
    tests = json.loads((RUN / "unit_tests.json").read_text())
    source = RUN.parent / "g1_coverage_20261016/run_v2/voters/hello/voters.bin"
    assert sha(source) == initial["source_sha256"]
    binary_hashes_ok = (
        sha(GEN) == ours["binary_sha256"]
        and sha(REF) == first_runs["binaries_sha256"]["ref"]
        and sha(TESTS) == tests["binary_sha256"]
        and first_runs["binaries_sha256"]["ours"] != sha(GEN)
    )
    initial_checks = {}
    for name in ("forward", "reverse"):
        voter = RUN / f"{name}.voters.bin"
        ref_tsv = RUN / f"{name}_ref/resolution.tsv"
        ours_tsv = RUN / f"{name}_ours/resolution.tsv"
        initial_checks[name] = (
            sha(voter) == initial["inputs"][name]["sha256"]
            and sha(ref_tsv) == first_runs["runs"][f"{name}_ref"]["tsv_sha256"]
            and sha(ours_tsv) == first_runs["runs"][f"{name}_ours"]["tsv_sha256"]
            and winner(ref_tsv) != winner(ours_tsv)
        )

    sweep_checks = {}
    for name, recorded in refs.items():
        voter = RUN / "sweep40" / f"{name}.bin"
        ref_tsv = RUN / "sweep40" / f"{name}.tsv"
        ours_tsv = RUN / "sweep40" / f"{name}.ours.tsv"
        local = ours["cases"][name]
        sweep_checks[name] = (
            sha(voter) == recorded["input_sha256"] == local["input_sha256"]
            and local["rc"] == 0
            and winner(ref_tsv) == recorded["winner"]
            and winner(ours_tsv) == local["winner"] == recorded["winner"]
            and local["matches_reference"]
        )
    bound_checks = {}
    for name, sides in bound["runs"].items():
        per_side = {side: bound_run_ok(name, side, row, bound)
                    for side, row in sides.items()}
        bound_checks[name] = (
            set(per_side) == {"ours", "ref"} and all(per_side.values())
            and winner(RUN / "bound" / name / "ours.tsv") ==
                winner(RUN / "bound" / name / "ref.tsv") == refs[name]["winner"]
        )
    unit_checks = {
        name: entry["rc"] == 0 and entry["completed"]
              and f"Done: {name}" in (RUN / f"test_{name}.log").read_text()
        for name, entry in tests["tests"].items()
    }
    regression = {}
    for fixture in ("hello", "prog"):
        new = RUN / "regression" / f"{fixture}.tsv"
        ref = RUN.parent / "g1_rc9_20261016" / f"{fixture}_ref_v2.tsv"
        regression[fixture] = new.read_bytes() == ref.read_bytes()
    altered = copy.deepcopy(bound["runs"]["unique0"]["ours"])
    altered["tsv_sha256"] = "0" * 64
    control = not bound_run_ok("unique0", "ours", altered, bound)
    state = {
        "sdk_head": subprocess.check_output(
            ["git", "-C", str(SDK), "rev-parse", "HEAD"], text=True
        ).strip(),
        "sdk_patch_sha256": hashlib.sha256(subprocess.check_output(
            ["git", "-C", str(SDK), "diff"]
        )).hexdigest(),
        "gen_snapshot_sha256": sha(GEN),
        "analyze_snapshot_sha256": sha(ANALYZER),
        "reference_gen_snapshot_sha256": sha(REF),
        "run_vm_tests_sha256": sha(TESTS),
        "loop_pause_exists": (ROOT / ".loop/PAUSE").exists(),
    }
    report = {
        "source_state": state,
        "initial_two_voter_counterexample": initial_checks,
        "sweep40_matched": sum(sweep_checks.values()),
        "sweep40_total": len(sweep_checks),
        "sweep40_failed_cases": [name for name, ok in sweep_checks.items() if not ok],
        "bound_runs_checked": sum(len(sides) for sides in bound["runs"].values()),
        "bound_cases_matched": sum(bound_checks.values()),
        "bound_failed_cases": [name for name, ok in bound_checks.items() if not ok],
        "unit_tests": unit_checks,
        "single_voter_regression": regression,
        "negative_control_detected": control,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not (binary_hashes_ok and len(sweep_checks) == 40
            and all(initial_checks.values()) and all(sweep_checks.values())
            and len(bound_checks) == 40 and all(bound_checks.values())
            and len(unit_checks) == 5 and all(unit_checks.values())
            and all(regression.values()) and control and state["loop_pause_exists"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
