#!/usr/bin/env python3
"""Read-only checks for three G1 AOT-derived output families.

The inputs are the archived 2026-10-16 matrix artifacts. This script does not
run either snapshot tool or change the SDK.
"""

import argparse
import copy
import hashlib
import importlib.util
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "scratchpad/g1_g4_20261016/matrix_final"
SYMBOLS_PATH = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
FIXTURES = ("hello", "prog", "base_dd")
SIDES = ("ours", "theirs")
NAMES = (
    "_kDartVmSnapshotData",
    "_kDartIsolateSnapshotData",
    "_kDartVmSnapshotInstructions",
    "_kDartIsolateSnapshotInstructions",
)

spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS_PATH)
symbol_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(symbol_module)


def read_bytes(path, hashes):
    data = path.read_bytes()
    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return data


def read_json(path, hashes):
    return json.loads(read_bytes(path, hashes))


def differences(a, b, path=""):
    """Return every differing leaf, retaining both values for exact matching."""
    if type(a) is not type(b):
        return [(path, a, b)]
    if isinstance(a, dict):
        out = []
        for key in sorted(a.keys() | b.keys()):
            if key not in a or key not in b:
                out.append((path + "/" + key, a.get(key), b.get(key)))
            else:
                out.extend(differences(a[key], b[key], path + "/" + key))
        return out
    if isinstance(a, list):
        out = []
        if len(a) != len(b):
            out.append((path + "/length", len(a), len(b)))
        for index, (left, right) in enumerate(zip(a, b)):
            out.extend(differences(left, right, path + "/" + str(index)))
        return out
    return [(path, a, b)] if a != b else []


def region_size(name, data):
    if name.endswith("Data"):
        assert struct.unpack_from("<I", data)[0] == 0xDCDCF5F5
        snapshot_size = struct.unpack_from("<q", data, 4)[0] + 4
        aligned = (snapshot_size + 63) & ~63
        extra_size = struct.unpack_from("<I", data, aligned)[0]
        size = snapshot_size + extra_size
    else:
        size = struct.unpack_from("<Q", data)[0]
    assert 0 < size <= len(data)
    return size


def object_pool_link_data(data):
    """Decode link_info.cc's unsigned/signed 7-bit varints and four-field rows."""
    cursor = 0

    def varint(marker=128):
        nonlocal cursor
        value = shift = 0
        while cursor < len(data):
            byte = data[cursor]
            cursor += 1
            if byte > 127:
                return value | ((byte - marker) << shift)
            value |= byte << shift
            shift += 7
        raise ValueError("truncated varint")

    def string():
        length = varint()
        if length > len(data) - cursor:
            raise ValueError("truncated string")
        return "".join(chr(varint(192)) for _ in range(length))

    def vector():
        length = varint()
        if length > len(data) - cursor:
            raise ValueError("truncated vector")
        return [varint() for _ in range(length)]

    count = varint()
    if count > len(data) // 4:
        raise ValueError("invalid row count")
    rows = [(string(), string(), vector(), vector()) for _ in range(count)]
    pairs = vector()
    pool_size = varint()
    if cursor != len(data):
        raise ValueError("trailing bytes")
    return rows, pairs, pool_size


def trailing_image_padding(symbols, function_name, image_name):
    """Bytes after a real function until the end of its instruction image."""
    function = symbols[function_name]
    image = symbols[image_name]
    offset = function["value"] + function["size"] - image["value"]
    assert 0 <= offset <= len(image["bytes"])
    return image["bytes"][offset:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--negative-controls", action="store_true")
    args = parser.parse_args()
    hashes = {}
    results = {}
    cached = {}
    for fixture in FIXTURES:
        docs = {}
        for side in SIDES:
            prefix = MATRIX / f"as.{fixture}.{side}"
            docs[side] = {
                "dd": read_json(MATRIX / "m21" / side / fixture / "dd_table_data/out.json", hashes),
                "shorebird": read_json(Path(str(prefix) + ".shorebird"), hashes),
                "disassemble": read_json(Path(str(prefix) + ".disassemble"), hashes),
                "blob": read_bytes(Path(str(prefix) + ".dump_blobs"), hashes),
                "pool_link": read_bytes(Path(str(prefix) + ".dump_object_pool_link_data"), hashes),
            }
            elf = read_bytes(Path(str(prefix) + ".so"), hashes)
            docs[side]["symbols"] = {
                item["name"]: item for item in symbol_module.symbols(elf)
            }

        left, right = docs["ours"], docs["theirs"]
        dd_diffs = differences(left["dd"], right["dd"])
        shorebird_diffs = differences(left["shorebird"], right["shorebird"])
        dd_ok = (
            left["dd"]["dd_table"] == right["dd"]["dd_table"]
            and len(left["dd"]["dd_table"]) > 0
            and dd_diffs == shorebird_diffs
        )

        regions = {}
        blob_ok = True
        for side in SIDES:
            parts = []
            for name in NAMES:
                data = docs[side]["symbols"][name]["bytes"]
                parts.append(data[:region_size(name, data)])
            regions[side] = [len(part) for part in parts]
            blob_ok &= b"".join(parts) == docs[side]["blob"]

        pool = {side: object_pool_link_data(docs[side]["pool_link"])
                for side in SIDES}
        pool_ok = True
        for side in SIDES:
            rows = pool[side][0]
            functions = docs[side]["shorebird"]["functions"]
            pool_ok &= len(rows) == len(functions)
            pool_ok &= all(
                row == tuple(function[key] for key in
                             ("self_hash", "op_subgraph_hash", "self_pp", "subgraph_pp"))
                for row, function in zip(rows, functions)
            )
        pool_ok &= pool["ours"][1:] == pool["theirs"][1:]
        pool_ok &= all(
            our[2:] == their[2:]
            for our, their in zip(pool["ours"][0], pool["theirs"][0])
        )
        pool_changes = [
            sum(our[index] != their[index] for our, their in
                zip(pool["ours"][0], pool["theirs"][0]))
            for index in range(4)
        ]

        a, b = left["disassemble"], right["disassemble"]
        object_diffs = differences(a["objects"], b["objects"])
        offsets = [item for item in object_diffs if item[0].endswith("/offset")]
        sizes = [item for item in object_diffs if item[0].endswith("/size")]
        other = [item for item in object_diffs if item not in offsets and item not in sizes]
        size_details = []
        for path, our_size, their_size in sizes:
            index = int(path.split("/")[1])
            item = a["objects"][index]
            size_details.append({
                "name": item.get("name"), "ours": our_size, "theirs": their_size
            })
        expected_sizes = {
            "_iso_stub_ResumeStub": (196, 192),
            "Resume": (196, 192),
            "GetCStackPointer": (20, 8),
        }
        if fixture != "prog":
            expected_sizes["Map._fromKeyValues"] = (448, 436)
        sizes_ok = {
            entry["name"]: (entry["ours"], entry["theirs"])
            for entry in size_details
        } == expected_sizes
        padding = {}
        for display, actual, image in (
            ("GetCStackPointer", "stub GetCStackPointer", "_kDartVmSnapshotInstructions"),
            ("Map._fromKeyValues", "new Map._fromKeyValues", "_kDartIsolateSnapshotInstructions"),
        ):
            if display not in expected_sizes:
                continue
            values = {}
            for side in SIDES:
                symbols = docs[side]["symbols"]
                function = symbols[actual]
                region = symbols[image]
                end = region["value"] + region["size"]
                inferred = end - function["value"]
                trailing = trailing_image_padding(symbols, actual, image)
                values[side] = {
                    "symbol_size": function["size"],
                    "code_size_to_image_end": inferred,
                    "trailing_bytes": trailing.hex(),
                }
                expected = expected_sizes[display][0 if side == "ours" else 1]
                sizes_ok &= inferred == expected and function["size"] == expected - len(trailing)
                sizes_ok &= trailing == b"\x00\x00\x20\xd4" * (len(trailing) // 4)
            padding[display] = values
        address_fields = all(
            isinstance(v, str) and v.startswith("0x")
            for side in SIDES for v in docs[side]["disassemble"]["snapshot_data"].values()
        )
        disassemble_ok = (
            a["metadata"] == b["metadata"]
            and len(a["objects"]) == len(b["objects"])
            and not other
            and sizes_ok and address_fields
            and all(x - y == 4 for _, x, y in offsets)
            and all(a["objects"][int(p.split("/")[1])].get("type") == "Code"
                    for p, _, _ in offsets + sizes)
        )
        results[fixture] = {
            "dd_table_data": {
                "ok": dd_ok, "table_entries": len(left["dd"]["dd_table"]),
                "cross_side_differences": len(dd_diffs),
                "same_differences_as_shorebird": dd_diffs == shorebird_diffs,
            },
            "dump_blobs": {"ok": blob_ok, "region_lengths": regions},
            "dump_object_pool_link_data": {
                "ok": pool_ok, "code_rows": len(pool["ours"][0]),
                "field_change_counts": dict(zip(
                    ("self_hash", "op_subgraph_hash", "self_pp", "subgraph_pp"),
                    pool_changes)),
                "pair_constraints": len(pool["ours"][1]),
                "pool_size": pool["ours"][2],
            },
            "disassemble_inventory": {
                "ok": disassemble_ok, "offsets_plus_four": len(offsets),
                "size_differences": size_details,
                "image_end_padding": padding,
                "other_object_differences": len(other),
                "snapshot_data_is_process_addresses": address_fields,
            },
        }
        cached[fixture] = docs

    controls = {}
    if args.negative_controls:
        fixture = "hello"
        d = cached[fixture]
        altered_dd = copy.deepcopy(d["theirs"]["dd"])
        altered_dd["dd_table"][0] = {"negative_control": True}
        controls["dd_table_mutation_detected"] = (
            d["ours"]["dd"]["dd_table"] != altered_dd["dd_table"]
        )
        expected_blob = b"".join(
            d["ours"]["symbols"][name]["bytes"][:region_size(
                name, d["ours"]["symbols"][name]["bytes"]
            )] for name in NAMES
        )
        altered_blob = bytearray(d["ours"]["blob"])
        altered_blob[-1] ^= 1
        controls["blob_mutation_detected"] = bytes(altered_blob) != expected_blob
        altered_pool = copy.deepcopy(object_pool_link_data(d["ours"]["pool_link"])[0])
        altered_pool[0] = ("wrong hash", *altered_pool[0][1:])
        controls["pool_hash_mutation_detected"] = altered_pool[0][0] != (
            d["ours"]["shorebird"]["functions"][0]["self_hash"]
        )
        altered_disassembly = copy.deepcopy(d["ours"]["disassemble"])
        altered_disassembly["objects"][2]["offset"] += 8
        controls["offset_mutation_detected"] = any(
            x - y != 4 for p, x, y in differences(
                altered_disassembly["objects"], d["theirs"]["disassemble"]["objects"]
            ) if p.endswith("/offset")
        )

    report = {"source": "2026-10-16 archived matrix; no new binary run",
              "fixtures": results, "input_sha256": hashes, "negative_controls": controls}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not all(all(entry["ok"] for entry in result.values()) for result in results.values()) or not all(controls.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
