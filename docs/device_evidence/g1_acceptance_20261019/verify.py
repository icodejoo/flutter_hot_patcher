#!/usr/bin/env python3
"""Aggregate the archived G1 denominator and current read-only checks."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path("/Users/Cruz/dart-3122/sdk")
EVIDENCE = ROOT / "docs/device_evidence"
CHECKS = [
    "g1_rc8_20261016",
    "g1_followup_20261016",
    "g1_rc11_20261016",
    "g1_aot_derived_20261019",
    "g1_aot_payload_20261019",
    "g1_rc10_alignment_20261019",
    "g1_rc9_membership_20261019",
    "g1_rc10_payload_20261019",
    "g1_jit_layout_swap_20261019",
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    coverage_file = EVIDENCE / "g1_coverage_20261016/audit/report.json"
    classified_file = EVIDENCE / "g1_rootcause_20261016/classification.json"
    coverage = json.loads(coverage_file.read_text())
    classified = json.loads(classified_file.read_text())
    assert coverage["registered_reference_count"] == 92
    assert coverage["exercised_reference_count"] == 92
    assert coverage["fixture_option_combinations"] == 276
    assert coverage["covered_fixture_option_combinations"] == 276
    assert coverage["missing_exercise"] == []
    assert len(classified["cells"]) == 122 and classified["failed"] == []
    assert all(f"RC{i}" in classified["root_causes"] for i in range(1, 13))
    assert all(check["ok"] for check in classified["checks"])

    results = {}
    for name in CHECKS:
        script = EVIDENCE / name / "verify.py"
        process = subprocess.run(["python3", str(script)], cwd=ROOT,
                                 capture_output=True, text=True)
        if process.returncode != 0:
            raise RuntimeError(f"{name} failed: {process.stderr[-500:]}")
        json.loads(process.stdout)
        results[name] = {"rc": process.returncode,
                         "script_sha256": sha(script.read_bytes()),
                         "result_sha256": sha(process.stdout.encode())}

    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SDK).decode().strip()
    patch = subprocess.check_output(["git", "diff"], cwd=SDK)
    subprocess.run(["git", "diff", "--check"], cwd=SDK, check=True,
                   capture_output=True)
    assert head == "8367f9e0ca624cb8d2cc02ce2f38d677a3f1bdf0"
    assert sha(patch) == "0088c7f7b7904539729549e962518188a44be70ad4480d8df022de9e6d6a0a48"
    assert (ROOT / ".loop/PAUSE").exists()

    result = {"status": "PASS_WITH_EXPLAINED_DIFFERENCES",
              "registered_options": 92, "fixture_option_runs": 276,
              "classified_original_differences": 122,
              "sdk_head": head, "sdk_patch_sha256": sha(patch),
              "coverage_sha256": sha(coverage_file.read_bytes()),
              "classification_sha256": sha(classified_file.read_bytes()),
              "read_only_checks": results, "loop_pause_preserved": True}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
