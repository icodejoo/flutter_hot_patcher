#!/usr/bin/env python3
"""Check linked AOT pool accesses against independent, saved oracle output."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN = ROOT / "scratchpad/g1_rc8_20261016"
ORACLE = ROOT / "scratchpad/g1_rootcause_20261016/pool/theirs_op.json"
CLASSIFIER = ROOT / "docs/device_evidence/g1_rootcause_20261016/classify.py"

spec = importlib.util.spec_from_file_location("g1_classify", CLASSIFIER)
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load():
    names = ("nolink_pool", "op_pool", "patch_nolink_pool", "patch_op_pool")
    return {name: json.loads((RUN / f"{name}.json").read_text()) for name in names}


def assess(pools):
    old_pool = {e["offset"]: e["code"] for e in pools["nolink_pool"]["entries"]}
    new_pool = {e["offset"]: e["code"] for e in pools["op_pool"]["entries"]}
    linked = classifier.symbols((RUN / "op.so").read_bytes())
    plain = classifier.symbols((RUN / "nolink.so").read_bytes())
    paired, unpaired = classifier.pair(linked, plain)
    accesses = []
    for new, old in paired:
        if (new["name"].startswith("_kDart") or new["size"] != old["size"]):
            continue
        for position in range(0, new["size"], 4):
            new_word, = struct.unpack_from("<I", new["bytes"], position)
            old_word, = struct.unpack_from("<I", old["bytes"], position)
            mask = 0xffc003e0
            pool_load = 0xf9400000 | (27 << 5)
            if (new_word != old_word and
                    new_word & mask == pool_load and old_word & mask == pool_load):
                accesses.append((((old_word >> 10) & 0xfff) * 8,
                                 ((new_word >> 10) & 0xfff) * 8))

    preserved = sum(old_pool.get(old) == new_pool.get(new)
                    for old, new in accesses)
    moved_values = sum(value != new_pool.get(offset)
                       for offset, value in old_pool.items())
    oracle = json.loads(ORACLE.read_text())
    differences = []
    for ours, theirs in zip(pools["op_pool"]["entries"], oracle["entries"]):
        if ours != theirs:
            differences.append((ours["index"], ours["code"], theirs["code"]))
    address = re.compile(r"0x[0-9a-f]+ \(unknown\)")
    allowed_address_indices = [650, 655, 657, 659, 676, 1117]
    only_process_addresses = (
        [i for i, _, _ in differences] == allowed_address_indices and
        all(address.fullmatch(a) and address.fullmatch(b)
            for _, a, b in differences))

    identity_a = pools["patch_nolink_pool"]
    identity_b = pools["patch_op_pool"]
    identity_differences = [i for i, (a, b) in enumerate(
        zip(identity_a["entries"], identity_b["entries"])) if a != b]
    checks = {
        "all_640_renumbered_loads_preserve_value":
            len(accesses) == 640 and preserved == 640 and not unpaired,
        "pool_reordered_like_reference":
            moved_values == 630 and pools["op_pool"]["object_pool_size"] == 1424 and
            only_process_addresses,
        "nonidentity_report_matches_reference":
            "Sorted ObjectPool, moved 660 of 1424 entries." in (RUN / "op.log").read_text(),
        "identity_mapping_preserves_pool":
            identity_a["object_pool_size"] == identity_b["object_pool_size"] == 1421 and
            identity_a["code_infos"] == identity_b["code_infos"] and
            identity_differences == allowed_address_indices and
            all(address.fullmatch(identity_a["entries"][i]["code"]) and
                address.fullmatch(identity_b["entries"][i]["code"])
                for i in identity_differences),
        "identity_report_matches_reference":
            "Sorted ObjectPool, moved 0 of 1421 entries." in (RUN / "patch_op.log").read_text(),
    }
    return {
        "checks": checks,
        "renumbered_loads": len(accesses),
        "preserved_loads": preserved,
        "changed_pool_positions": moved_values,
        "oracle_differences": differences,
        "identity_different_positions": identity_differences,
        "first_destination_offset": accesses[0][1],
    }


def main():
    pools = load()
    result = assess(pools)
    negative = {}
    changed = copy.deepcopy(pools)
    destination = result["first_destination_offset"]
    changed["op_pool"]["entries"][(destination - 16) // 8]["code"] = "corrupted"
    negative["changed_linked_pool_value"] = not all(assess(changed)["checks"].values())
    changed = copy.deepcopy(pools)
    changed["op_pool"]["entries"][0]["code"] = "corrupted"
    negative["changed_oracle_comparison"] = not all(assess(changed)["checks"].values())
    changed = copy.deepcopy(pools)
    changed["patch_op_pool"]["entries"][0]["code"] = "corrupted"
    negative["changed_identity_pool"] = not all(assess(changed)["checks"].values())
    result["negative_controls"] = negative
    result["sha256"] = {str(path.relative_to(ROOT)): sha256(path) for path in
                        [*(RUN / f"{name}.json" for name in pools),
                         *(RUN / f"{name}.so" for name in
                           ("nolink", "op", "patch_nolink", "patch_op")),
                         RUN / "op.log", RUN / "patch_op.log", ORACLE]}
    result.pop("first_destination_offset")
    result["passed"] = all(result["checks"].values()) and all(negative.values())
    (HERE / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "checks": result["checks"],
                      "negative_controls": negative}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
