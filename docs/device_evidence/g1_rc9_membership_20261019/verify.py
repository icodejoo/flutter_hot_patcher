#!/usr/bin/env python3
"""Read-only verification of RC9 membership probes and final AOT runs."""

import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "scratchpad/g1_rc9_keymap_20261019/membership_probe"
EXPECTED = {"hello": (2878, 2983, 18, 87), "prog": (5253, 5623, 140, 230)}
CHECKS = []
spec = importlib.util.spec_from_file_location(
    "g1_symbols", ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py")
symbols_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symbols_module)


def check(condition, label):
    if not condition:
        raise AssertionError(label)
    CHECKS.append(label)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_unsigned(data, pos):
    value = shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 127) << shift
        if byte & 128:
            return value, pos
        shift += 7
    raise ValueError("truncated unsigned")


def voter_targets(path):
    data = path.read_bytes()
    check(data[:8] == bytes.fromhex("557ecadd02000000"), f"{path.name} header")
    count, pos = read_unsigned(data, 8)
    targets = []
    for slot in range(count):
        actual_slot, pos = read_unsigned(data, pos)
        voters, pos = read_unsigned(data, pos)
        check((actual_slot, voters) == (slot, 1), f"{path.name} slot {slot}")
        caller = []
        target = []
        for key in (caller, target):
            for _ in range(5):
                value, pos = read_unsigned(data, pos)
                key.append(value)
        check(tuple(caller) == (0xDEADBEEF, 0, 0, 0, 0), f"{path.name} caller {slot}")
        targets.append(tuple(target))
    check(pos == len(data), f"{path.name} consumed")
    return targets


def maps(name):
    data = (OUT / f"{name}.keys").read_text().split("BEGIN ")[1:]
    check(len(data) == 2, f"{name} key-map passes")
    result = []
    for i, block in enumerate(data):
        lines = block.splitlines()
        keys = {tuple(map(int, line.split()[:5])) for line in lines[1:]}
        check(len(keys) == int(lines[0]), f"{name} key-map size {i}")
        result.append(keys)
    return result


def main():
    grouped = json.loads((OUT / "grouped_manifest.json").read_text())
    final = json.loads((OUT / "final_manifest.json").read_text())
    check(len(grouped) == 24, "24 grouped runs")
    check(len(final) == 3, "three final runs")
    by_group = {(r["case"], r["group"], r["side"]): r for r in grouped}
    for name, (first_count, second_count, extractors, added) in EXPECTED.items():
        first, second = maps(name)
        check(len(first) == first_count + extractors, f"{name} original first count")
        check(len(second) == second_count, f"{name} second count")
        check(len(second - first) == added, f"{name} later keys")
        check(sum(k[3] == 10 for k in first) == extractors,
              f"{name} MethodExtractor count")
        groups = {"first_all": sorted(first), "first_functions": sorted(first),
                  "first_method_extractors": sorted(k for k in first if k[3] == 10),
                  "first_other_functions": sorted(k for k in first if k[3] != 10),
                  "second_only": sorted(second - first), "second_all": sorted(second)}
        for group, keys in groups.items():
            path = OUT / f"{name}_{group}.voters.bin"
            check(voter_targets(path) == keys, f"{name} {group} voters match key dump")
            paired = []
            for side in ("ours", "ref"):
                row = by_group[(name, group, side)]
                prefix = OUT / f"{name}_{group}_{side}"
                check(row["rc"] == 0 and row["key_count"] == len(keys),
                      f"{name} {group} {side} outcome")
                paths = {"binary": Path(row["command"][0]), "kernel": Path(row["command"][-1]),
                         "voters": path, "stdout": Path(f"{prefix}.stdout"),
                         "stderr": Path(f"{prefix}.stderr"), "elf": Path(f"{prefix}.so"),
                         "tsv": Path(f"{prefix}.tsv")}
                for field, artifact in paths.items():
                    actual_hash = sha(artifact) if artifact.exists() else None
                    check(actual_hash == row["sha256"][field],
                          f"{name} {group} {side} {field} hash")
                lines = [x for x in paths["stderr"].read_text().splitlines()
                         if "DD resolution:" in x]
                check(len(lines) == 2, f"{name} {group} {side} two passes")
                reported = [dict(zip(("target_missing", "target_ambiguous", "caller_missing", "caller_ambiguous"),
                                     map(int, re.search(r"tgt_miss=(\d+) tgt_ambig=(\d+) caller_miss=(\d+) caller_ambig=(\d+)", line).groups())))
                            for line in lines]
                check(reported == row["counts"], f"{name} {group} {side} tallies")
                for pass_index, counts in enumerate(reported):
                    check(sum(counts.values()) == len(keys),
                          f"{name} {group} {side} pass {pass_index} scores all keys")
                paired.append(reported)
            check(paired[0] == paired[1], f"{name} {group} both sides agree")
        first_report = by_group[(name, "first_all", "ref")]["counts"][0]
        check(first_report["target_missing"] == extractors and
              first_report["caller_missing"] == first_count,
              f"{name} first map excludes precisely extractors")
        check(by_group[(name, "second_all", "ref")]["counts"][1]["target_missing"] == 0,
              f"{name} second map contains every probed key")
    for row in final:
        name = row["case"]
        prefix = OUT / f"{name}_final"
        paths = {"binary": Path(row["command"][0]), "kernel": Path(row["command"][-1]),
                 "voters": Path(row["command"][3].split("=", 1)[1]),
                 "stdout": Path(f"{prefix}.stdout"), "stderr": Path(f"{prefix}.stderr"),
                 "elf": Path(f"{prefix}.so"), "tsv": Path(f"{prefix}.tsv")}
        check(row["rc"] == 0, f"{name} final rc")
        for field, artifact in paths.items():
            check(sha(artifact) == row["sha256"][field], f"{name} final {field} hash")
        reference = (ROOT / f"scratchpad/g1_coverage_20261016/run_v2/theirs/{name}/dd"
                     if name != "tie" else ROOT / "scratchpad/g1_rc9_tie_20261019/forward_ref")
        check(paths["tsv"].read_bytes() == (reference / "resolution.tsv").read_bytes(),
              f"{name} final TSV equals reference")
        if name != "tie":
            check(paths["stderr"].read_bytes() == (reference / "stderr.log").read_bytes(),
                  f"{name} final stderr equals reference")
        previous_elf = ROOT / f"scratchpad/g1_rc9_keymap_20261019/{name}_after.so"
        prior_symbols = [(item["name"], item["bytes"])
                         for item in symbols_module.symbols(previous_elf.read_bytes())]
        final_symbols = [(item["name"], item["bytes"])
                         for item in symbols_module.symbols(paths["elf"].read_bytes())]
        check(final_symbols == prior_symbols,
              f"{name} all AOT symbol bytes unchanged by first-pass relocation")
    sweep = OUT / "sweep40_final"
    sweep_rows = json.loads((sweep / "manifest.json").read_text())
    check(len(sweep_rows) == 40, "40 post-relocation tie cases")
    for row in sweep_rows:
        name = row["case"]
        prefix = sweep / name
        original = ROOT / "scratchpad/g1_rc9_tie_20261019/sweep40"
        paths = {"binary": Path(row["command"][0]), "kernel": Path(row["command"][-1]),
                 "voters": original / f"{name}.bin", "elf": Path(f"{prefix}.so"),
                 "tsv": Path(f"{prefix}.tsv"), "stdout": Path(f"{prefix}.stdout"),
                 "stderr": Path(f"{prefix}.stderr"),
                 "reference_tsv": original / f"{name}.tsv",
                 "reference_stderr": original / f"{name}.stderr"}
        check(row["rc"] == 0 and row["pid"] > 0, f"{name} final tie run")
        for field, path in paths.items():
            check(sha(path) == row["sha256"][field], f"{name} final tie {field} hash")
        for field in ("tsv", "stderr"):
            check(paths[field].read_bytes() == paths[f"reference_{field}"].read_bytes(),
                  f"{name} final tie {field} equals reference")
    print(json.dumps({"checks": len(CHECKS), "status": "pass"}, indent=2))


if __name__ == "__main__":
    main()
