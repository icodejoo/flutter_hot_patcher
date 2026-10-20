#!/usr/bin/env python3
"""Bind current signed-tool AOT output to the archived G1 matrix."""

import hashlib
import importlib.util
import json
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path("/Users/Cruz/dart-3122/sdk")
OLD = ROOT / "scratchpad/g1_g4_20261016/matrix_final"
CURRENT = ROOT / "scratchpad/g1_current_20261019"
STATE = ROOT / "docs/device_evidence/g1_rc9_tie_20261019/verification.json"
SYMBOLS = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def snapshot_symbols(path):
    return {entry["name"]: entry["bytes"] for entry in module.symbols(path.read_bytes())}


def version_only(current, archived):
    if len(current) != len(archived):
        return False, []
    changed = [i for i, (a, b) in enumerate(zip(current, archived)) if a != b]
    return bool(changed) and all(20 <= i < 52 for i in changed), changed


def main():
    state = read_json(STATE)["source_state"]
    provenance = read_json(CURRENT / "provenance.json")
    current_patch = hashlib.sha256(subprocess.check_output(
        ["git", "-C", str(SDK), "diff"]
    )).hexdigest()
    binaries_ok = (
        provenance["sdk_head"] == state["sdk_head"]
        and current_patch == state["sdk_patch_sha256"]
        and provenance["gen_snapshot_sha256"] == state["gen_snapshot_sha256"]
        and provenance["analyze_snapshot_sha256"] == state["analyze_snapshot_sha256"]
        == sha(SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/analyze_snapshot")
    )
    results = {}
    for fixture in ("hello", "prog", "base_dd"):
        directory = CURRENT / fixture
        old_prefix = OLD / f"as.{fixture}.ours"
        current_elf = directory / "app.so"
        old_elf = OLD / f"gs.{fixture}.ours.so"
        records = provenance["fixtures"][fixture]
        outputs = {
            "gen_elf": current_elf, "gen_assembly": directory / "app.S",
            "shorebird": directory / "shorebird.json", "dump_blobs": directory / "blobs.bin",
            "dump_object_pool_link_data": directory / "pool.bin",
            "disassemble": directory / "disassemble.json",
            "dd_table_data": directory / "dd_table_data.json",
        }
        provenance_ok = all(sha(path) == records[name]["output_sha256"]
                            for name, path in outputs.items())
        current, archived = snapshot_symbols(current_elf), snapshot_symbols(old_elf)
        regions = {}
        for name in (
            "_kDartVmSnapshotData", "_kDartIsolateSnapshotData",
            "_kDartVmSnapshotInstructions", "_kDartIsolateSnapshotInstructions",
        ):
            if name.endswith("Data"):
                ok, changed = version_only(current[name], archived[name])
            else:
                ok, changed = current[name] == archived[name], []
            regions[name] = {"ok": ok, "changed_bytes": len(changed),
                             "change_range": [min(changed), max(changed)] if changed else []}

        pool_equal = (directory / "pool.bin").read_bytes() == Path(
            str(old_prefix) + ".dump_object_pool_link_data"
        ).read_bytes()
        # The dump uses logical data length, not the padded ELF symbol length.
        vm_logical = struct.unpack_from("<q", current["_kDartVmSnapshotData"], 4)[0] + 4
        vm_extra_at = (vm_logical + 63) & ~63
        vm_logical += struct.unpack_from("<I", current["_kDartVmSnapshotData"], vm_extra_at)[0]
        current_blob = (directory / "blobs.bin").read_bytes()
        old_blob = Path(str(old_prefix) + ".dump_blobs").read_bytes()
        blob_changed = [i for i, (a, b) in enumerate(zip(current_blob, old_blob)) if a != b]
        blob_ok = len(current_blob) == len(old_blob) and bool(blob_changed) and all(
            20 <= i < 52 or vm_logical + 20 <= i < vm_logical + 52
            for i in blob_changed
        )

        json_results = {}
        for kind, old_path in (
            ("shorebird", Path(str(old_prefix) + ".shorebird")),
            ("dd_table_data", OLD / "m21/ours" / fixture / "dd_table_data/out.json"),
        ):
            new = read_json(outputs[kind])
            old = read_json(old_path)
            changed_keys = {key for key in new["snapshot_data"]
                            if new["snapshot_data"][key] != old["snapshot_data"][key]}
            same_other = all(new[key] == old[key] for key in new if key != "snapshot_data")
            json_results[kind] = {
                "ok": same_other and changed_keys == {"snapshot_version", "vm_data_hash"},
                "metadata_changed": sorted(changed_keys),
            }
        new_disassembly = read_json(directory / "disassemble.json")
        old_disassembly = read_json(Path(str(old_prefix) + ".disassemble"))
        disassembly_ok = (
            new_disassembly["objects"] == old_disassembly["objects"]
            and new_disassembly["metadata"] == old_disassembly["metadata"]
            and set(new_disassembly["snapshot_data"]) == set(old_disassembly["snapshot_data"])
        )

        new_lines = (directory / "app.S").read_text().splitlines()
        old_lines = (OLD / "m21/ours" / fixture / "assembly/app.S").read_text().splitlines()
        changed_lines = [i for i, (a, b) in enumerate(zip(new_lines, old_lines)) if a != b]
        assembly_ok = (
            len(new_lines) == len(old_lines) and len(changed_lines) == 10
            and all(new_lines[i].startswith(".quad 0x") and old_lines[i].startswith(".quad 0x")
                    for i in changed_lines)
            and changed_lines[:5] == list(range(changed_lines[0], changed_lines[0] + 5))
            and changed_lines[5:] == list(range(changed_lines[5], changed_lines[5] + 5))
        )
        results[fixture] = {
            "ok": provenance_ok and all(v["ok"] for v in regions.values())
                  and pool_equal and blob_ok and all(v["ok"] for v in json_results.values())
                  and disassembly_ok and assembly_ok,
            "provenance_ok": provenance_ok, "regions": regions,
            "pool_link_byte_identical": pool_equal,
            "blob_only_version_hash_changed": blob_ok,
            "blob_changed_bytes": len(blob_changed),
            "json": json_results, "disassemble_objects_identical": disassembly_ok,
            "assembly_version_quad_lines_only": assembly_ok,
            "assembly_changed_line_numbers": [i + 1 for i in changed_lines],
            "elf_sha256": sha(current_elf), "archived_elf_sha256": sha(old_elf),
        }
    altered = bytearray((CURRENT / "hello/app.so").read_bytes())
    altered[0] ^= 1
    negative_control = hashlib.sha256(altered).hexdigest() != provenance[
        "fixtures"]["hello"]["gen_elf"]["output_sha256"]
    output = {"binaries_ok": binaries_ok, "fixtures": results,
              "negative_control_provenance_mutation_detected": negative_control}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not binaries_ok or not negative_control or not all(v["ok"] for v in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
