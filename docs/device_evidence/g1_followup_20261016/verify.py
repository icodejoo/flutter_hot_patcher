#!/usr/bin/env python3
"""Read-only verification of G1 RC7, RC9, and RC10 follow-up artifacts."""

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RUN7 = ROOT / "scratchpad/g1_rc7_20261016"
RUN9 = ROOT / "scratchpad/g1_rc9_20261016"
RUN10 = ROOT / "scratchpad/g1_rc10_20261016"
MATRIX = ROOT / "scratchpad/g1_g4_20261016/matrix_final/m21"
CLASSIFIER = ROOT / "docs/device_evidence/g1_rootcause_20261016/classify.py"
spec = importlib.util.spec_from_file_location("g1_classify", CLASSIFIER)
classifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(classifier)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dispatch_targets(path):
    profile = json.loads(path.read_text())
    nodes, edges, strings = (profile[k] for k in ("nodes", "edges", "strings"))
    node_types = profile["snapshot"]["meta"]["node_types"][0]
    node_width = len(profile["snapshot"]["meta"]["node_fields"])
    edge_width = len(profile["snapshot"]["meta"]["edge_fields"])
    first_edge = 0
    array_index = None
    for i in range(len(nodes) // node_width):
        node = nodes[i * node_width:(i + 1) * node_width]
        if strings[node[1]] == "dispatch_table":
            assert node[4] == 1
            edge = edges[first_edge * edge_width:(first_edge + 1) * edge_width]
            array_index = edge[2] // node_width
            first_edge += 1
            break
        first_edge += node[4]
    assert array_index is not None
    array = nodes[array_index * node_width:(array_index + 1) * node_width]
    assert node_types[array[0]] == "Array"
    result = []
    for i in range(array[4]):
        edge = edges[(first_edge + i) * edge_width:
                     (first_edge + i + 1) * edge_width]
        target = nodes[edge[2]:edge[2] + node_width]
        result.append((node_types[target[0]], strings[target[1]], target[3]))
    return result


def snapshot_symbol_size(path, name):
    symbols = {entry["name"]: entry for entry in classifier.symbols(path.read_bytes())}
    return symbols[name]["size"]


def main():
    used = set()

    def read(path):
        used.add(path)
        return path.read_bytes()

    checks = {}
    details = {}

    for fixture in ("hello", "prog", "base_dd"):
        ours = RUN7 / f"{fixture}_ours.map.json"
        ref = RUN7 / f"{fixture}_ref.map.json"
        supplied = MATRIX / "theirs" / fixture / "save_obfuscation_map/map.json"
        ours_map, ref_map, input_map = read(ours), read(ref), read(supplied)
        ours_json = json.loads(read(RUN7 / f"{fixture}_ours.shorebird.json"))
        ref_json = json.loads(read(RUN7 / f"{fixture}_ref.shorebird.json"))
        ours_names = [f["name"] for f in ours_json["functions"]]
        ref_names = [f["name"] for f in ref_json["functions"]]
        ours_so, ref_so = (RUN7 / f"{fixture}_{side}.so" for side in ("ours", "ref"))
        used.update((ours_so, ref_so))
        checks[f"RC7/{fixture}"] = (
            ours_map == ref_map and ours_map != input_map and
            ours_names == ref_names and len(ours_names) > 1000 and
            ours_so.stat().st_size == ref_so.stat().st_size)
        details[f"RC7/{fixture}"] = {
            "map_bytes": len(ours_map), "function_names": len(ours_names),
            "map_sha256": digest(ours),
        }

    for fixture in ("hello", "prog"):
        ours_tsv = RUN9 / f"{fixture}_ours_v2.tsv"
        ref_tsv = RUN9 / f"{fixture}_ref_v2.tsv"
        ours_so = RUN9 / f"{fixture}_ours_v2.so"
        ref_so = RUN9 / f"{fixture}_ref_v2.so"
        ours_log = RUN9 / f"{fixture}_ours_v2.log"
        ref_log = RUN9 / f"{fixture}_ref_v2.log"
        used.update((ours_so, ref_so))
        ours_lines = read(ours_log).decode().splitlines()
        ref_lines = read(ref_log).decode().splitlines()
        checks[f"RC9/{fixture}"] = (
            read(ours_tsv) == read(ref_tsv) and
            ours_so.stat().st_size == ref_so.stat().st_size and
            ours_lines[-1] == ref_lines[-1] and
            ours_lines[-1].startswith("DD table:"))
        details[f"RC9/{fixture}"] = {
            "table_report": ours_lines[-1], "elf_bytes": ours_so.stat().st_size,
            "tsv_sha256": digest(ours_tsv),
        }
    empty_ours = RUN9 / "empty_final_ours.so"
    empty_ref = RUN9 / "empty_ref.so"
    used.update((empty_ours, empty_ref, RUN9 / "empty_final_ours.log",
                 RUN9 / "empty_ref.log"))
    checks["RC9/empty"] = (
        empty_ours.stat().st_size == empty_ref.stat().st_size and
        not (RUN9 / "empty_final_ours.tsv").exists() and
        not (RUN9 / "empty_ref.tsv").exists() and
        "DD table:" not in (RUN9 / "empty_final_ours.log").read_text())

    target_lists = {}
    for side in ("ours", "ref"):
        for option in ("nolink", "ft"):
            path = RUN10 / f"{side}_{option}.profile.json"
            used.add(path)
            target_lists[f"{side}_{option}"] = dispatch_targets(path)
    baseline = target_lists["ours_nolink"]
    checks["RC10/dispatch_targets"] = (
        len(baseline) == 10347 and
        all(value == baseline for value in target_lists.values()))
    details["RC10/dispatch_targets"] = {
        "entries": len(baseline),
        "semantic_sha256": hashlib.sha256(json.dumps(baseline).encode()).hexdigest(),
    }
    field_files = [RUN10 / f"{side}.fields.json" for side in ("ours", "ref")]
    fields = [json.loads(read(path)) for path in field_files]
    field_sets = [Counter((f["id"], f["hash"]) for f in value["fields"])
                  for value in fields]
    dt_files = [RUN10 / f"{side}_{option}.dt"
                for side in ("ours", "ref") for option in ("nolink", "ft")]
    dt_data = [read(path) for path in dt_files]
    checks["RC10/link_metadata"] = (
        fields[0]["max_field_id"] == fields[1]["max_field_id"] == 244 and
        field_sets[0] == field_sets[1] and len(fields[0]["fields"]) == 622 and
        all(data == dt_data[0] for data in dt_data))

    growth = {}
    for side in ("ours", "ref"):
        plain = RUN10 / f"{side}_nolink_verbose.so"
        linked = RUN10 / f"{side}_verbose.so"
        used.update((plain, linked))
        plain_sections = classifier.elf_sections(plain.read_bytes())
        linked_sections = classifier.elf_sections(linked.read_bytes())
        growth[side] = (snapshot_symbol_size(linked, "_kDartIsolateSnapshotData") -
                        snapshot_symbol_size(plain, "_kDartIsolateSnapshotData"))
        checks[f"RC10/{side}_code_unchanged"] = (
            plain_sections[".text"] == linked_sections[".text"])
    checks["RC10/encoding_delta_localized"] = growth == {"ours": 512, "ref": 448}
    details["RC10/encoding_delta_localized"] = growth

    changed_targets = {name: list(values) for name, values in target_lists.items()}
    changed_targets["ours_ft"][10] = ("Code", "corrupted", 0)
    changed_map = bytearray(read(RUN7 / "hello_ours.map.json"))
    changed_map[10] ^= 1
    changed_table = bytearray(read(RUN9 / "hello_ours_v2.tsv"))
    changed_table[10] ^= 1
    negative_controls = {
        "mutated_dispatch_target":
            not all(value == baseline for value in changed_targets.values()),
        "mutated_obfuscation_map":
            not (bytes(changed_map) == read(RUN7 / "hello_ref.map.json") and
                 bytes(changed_map) !=
                 read(MATRIX / "theirs/hello/save_obfuscation_map/map.json")),
        "mutated_dd_table":
            bytes(changed_table) != read(RUN9 / "hello_ref_v2.tsv"),
    }
    report = {
        "passed": all(checks.values()) and all(negative_controls.values()),
        "checks": checks, "details": details,
        "negative_controls": negative_controls,
        "sha256": {str(path.relative_to(ROOT)): digest(path) for path in sorted(used)},
    }
    (HERE / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "checks": checks,
                      "negative_controls": negative_controls}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
