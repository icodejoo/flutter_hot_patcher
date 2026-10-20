#!/usr/bin/env python3
"""Decompose the archived G1 baseline AOT data symbols without rewriting files."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "scratchpad/g1_g4_20261016/matrix_final"
SYMBOLS = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
TOKEN = b" shorebird-native-entry-thr-offsets=2312,2320,2328"
NAMES = ("_kDartVmSnapshotData", "_kDartIsolateSnapshotData")
spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def read(path, hashes):
    data = path.read_bytes()
    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return data


def parts(region):
    assert struct.unpack_from("<I", region)[0] == 0xDCDCF5F5
    snapshot_length = struct.unpack_from("<q", region, 4)[0] + 4
    image_start = (snapshot_length + 63) & ~63
    image_size = struct.unpack_from("<Q", region, image_start)[0]
    assert image_start + image_size == len(region)
    return region[:snapshot_length], region[image_start:], image_start - snapshot_length


def image_differences(ours, theirs):
    if len(ours) != len(theirs) or len(ours) % 8:
        return None
    changed = []
    for offset in range(0, len(ours), 8):
        left = struct.unpack_from("<Q", ours, offset)[0]
        right = struct.unpack_from("<Q", theirs, offset)[0]
        if left != right:
            changed.append((offset, left, right))
    if not changed or changed[0][0] != 64:
        return None
    first = changed[0]
    if first[1] & 0xFFFFFFFF != first[2] & 0xFFFFFFFF:
        return None
    if first[1] >> 32 == first[2] >> 32:
        return None
    if not all(left - right == 4 for _, left, right in changed[1:]):
        return None
    return changed


def one_byte_string_hash(image):
    """Recompute StringHasher for the first RO-data OneByteString object."""
    tags = struct.unpack_from("<Q", image, 64)[0]
    class_id = (tags >> 12) & ((1 << 20) - 1)
    assert class_id == 94  # kOneByteStringCid in this SDK's ClassId enum.
    length = struct.unpack_from("<I", image, 72)[0] >> 1  # compressed Smi
    assert 0 < length <= len(image) - 80
    value = 0
    for byte in image[80:80 + length]:
        value = (value + byte) & 0xFFFFFFFF
        value = (value + (value << 10)) & 0xFFFFFFFF
        value ^= value >> 6
    value = (value + (value << 3)) & 0xFFFFFFFF
    value ^= value >> 11
    value = (value + (value << 15)) & 0xFFFFFFFF
    value &= (1 << 30) - 1
    value = value or 1
    return length, tags >> 32, value


def main():
    hashes, findings = {}, {}
    for fixture in ("hello", "prog", "base_dd"):
        files = {side: MATRIX / f"gs.{fixture}.{side}.so" for side in ("ours", "theirs")}
        syms = {side: {entry["name"]: entry for entry in module.symbols(read(path, hashes))}
                for side, path in files.items()}
        jsons = {side: json.loads(read(
            MATRIX / f"as.{fixture}.{side}.shorebird", hashes
        )) for side in ("ours", "theirs")}
        offset_changes = [a["offset"] - b["offset"] for a, b in zip(
            jsons["ours"]["functions"], jsons["theirs"]["functions"
            ])]
        isolate_shifted = sum(change == 4 for change in offset_changes)
        expected_isolate = 187 if fixture == "prog" else 220
        vm = syms["ours"]["_kDartVmSnapshotInstructions"]
        resume = syms["ours"]["stub Resume"]
        vm_after_resume = sum(
            entry["name"].startswith("stub ")
            and vm["value"] <= entry["value"] < vm["value"] + vm["size"]
            and entry["value"] > resume["value"]
            for entry in syms["ours"].values()
        )
        fixture_ok = (
            all(change in (0, 4) for change in offset_changes)
            and isolate_shifted == expected_isolate and vm_after_resume == 158
        )
        dimensions = {}
        for name in NAMES:
            a = syms["ours"][name]["bytes"]
            b = syms["theirs"][name]["bytes"]
            our_snapshot, our_image, our_pad = parts(a)
            their_snapshot, their_image, their_pad = parts(b)
            position = our_snapshot.find(TOKEN)
            normalized = bytearray(our_snapshot[:position] +
                                   our_snapshot[position + len(TOKEN):])
            normalized[4:12] = their_snapshot[4:12]  # serialized length
            normalized[20:52] = their_snapshot[20:52]  # snapshot version hash
            changed = image_differences(our_image, their_image)
            our_string = one_byte_string_hash(our_image)
            their_string = one_byte_string_hash(their_image)
            expected = 158 if name == NAMES[0] else expected_isolate
            ok = (
                position == 194 and their_snapshot.find(TOKEN) == -1
                and len(TOKEN) == 50 and normalized == their_snapshot
                and len(our_snapshot) - len(their_snapshot) == 50
                and our_pad - their_pad == 14
                and len(our_image) == len(their_image)
                and len(a) - len(b) == 64
                and changed is not None and len(changed) - 1 == expected
                and our_string[1] == our_string[2]
                and their_string[1] == their_string[2]
                and our_string[0] == their_string[0]
            )
            fixture_ok &= ok
            dimensions[name] = {
                "ok": ok,
                "snapshot_lengths": [len(our_snapshot), len(their_snapshot)],
                "features_token_offset": position,
                "snapshot_equal_after_length_hash_token_normalization":
                    normalized == their_snapshot,
                "alignment_padding": [our_pad, their_pad],
                "image_lengths": [len(our_image), len(their_image)],
                "first_one_byte_string": {
                    "header_word_offset": 64, "length": our_string[0],
                    "ours_cached_hash": our_string[1],
                    "ours_recomputed_hash": our_string[2],
                    "theirs_cached_hash": their_string[1],
                    "theirs_recomputed_hash": their_string[2],
                },
                "offset_words_plus_four": len(changed) - 1 if changed else None,
            }
        findings[fixture] = {
            "ok": fixture_ok, "vm_stubs_after_resume": vm_after_resume,
            "isolate_functions_shifted_plus_four": isolate_shifted,
            "regions": dimensions,
        }
    # In-memory negative controls: byte change outside the known token and
    # +8 in one image word must break the exact snapshot/image predicates.
    sample = module.symbols((MATRIX / "gs.hello.ours.so").read_bytes())
    sample_region = next(entry["bytes"] for entry in sample if entry["name"] == NAMES[0])
    snapshot, image, _ = parts(sample_region)
    altered_snapshot = bytearray(snapshot)
    altered_snapshot[500] ^= 1
    altered_image = bytearray(image)
    changed_word = struct.unpack_from("<Q", altered_image, 336)[0]
    struct.pack_into("<Q", altered_image, 336, changed_word + 4)
    reference = next(entry["bytes"] for entry in module.symbols(
        (MATRIX / "gs.hello.theirs.so").read_bytes()) if entry["name"] == NAMES[0])
    ref_snapshot, ref_image, _ = parts(reference)
    p = snapshot.find(TOKEN)
    adjusted = bytearray(altered_snapshot[:p] + altered_snapshot[p + len(TOKEN):])
    adjusted[4:12], adjusted[20:52] = ref_snapshot[4:12], ref_snapshot[20:52]
    controls = {
        "snapshot_mutation_detected": adjusted != ref_snapshot,
        "image_word_mutation_detected": image_differences(altered_image, ref_image) is None,
    }
    output = {"source": "2026-10-16 archived AOT fixtures", "fixtures": findings,
              "negative_controls": controls, "input_sha256": hashes}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not all(row["ok"] for row in findings.values()) or not all(controls.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
