#!/usr/bin/env python3
"""Read-only byte attribution for archived RC10 linked/unlinked snapshots."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "scratchpad/g1_rc10_20261016"
PREVIOUS = ROOT / "docs/device_evidence/g1_rc10_alignment_20261019/verification.json"
SYMBOLS = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_snapshot(path):
    elf = path.read_bytes()
    region = next(item["bytes"] for item in module.symbols(elf)
                  if item["name"] == "_kDartIsolateSnapshotData")
    assert struct.unpack_from("<I", region)[0] == 0xDCDCF5F5
    length = struct.unpack_from("<q", region, 4)[0] + 4
    aligned = (length + 63) & ~63
    extra_length = struct.unpack_from("<I", region, aligned)[0]
    assert length < aligned + extra_length <= len(region)
    assert region[12:20] == b"\x03\x00\x00\x00\x00\x00\x00\x00"
    version = region[20:52]
    assert len(version) == 32 and all(byte in b"0123456789abcdef" for byte in version)
    end_features = region.index(0, 52)
    return {"elf_sha256": sha(elf), "region": region, "snapshot_length": length,
            "extra_length": extra_length, "extra": region[aligned:aligned + extra_length],
            "version_hash": version.decode(),
            "features": region[52:end_features].decode(),
            "payload": region[end_features:length],
            "payload_offset": end_features,
            "symbol_bytes": len(region),
            "symbol_padding_bytes": len(region) - aligned - extra_length}


def main():
    previous = json.loads(PREVIOUS.read_text())
    rows = {}
    for side in ("ours", "ref"):
        rows[side] = {}
        for stage in ("nolink", "linked"):
            filename = f"{side}_{'nolink_' if stage == 'nolink' else ''}verbose.so"
            path = RUN / filename
            row = read_snapshot(path)
            expected = previous["input_sha256"][str(path.relative_to(ROOT))]
            assert row["elf_sha256"] == expected
            assert row["snapshot_length"] == previous["measurements"][side][stage]["snapshot_bytes"]
            rows[side][stage] = row

    marker = " shorebird-native-entry-thr-offsets=2312,2320,2328"
    assert len(marker) == 50
    for stage in ("nolink", "linked"):
        ours, ref = rows["ours"][stage], rows["ref"][stage]
        assert ours["features"] == ref["features"] + marker
        assert ours["payload_offset"] == ref["payload_offset"] + 50
        assert ours["payload"] == ref["payload"]
        assert ours["snapshot_length"] == ref["snapshot_length"] + 50
    for side in ("ours", "ref"):
        before, after = rows[side]["nolink"], rows[side]["linked"]
        assert before["features"] == after["features"]
        assert before["version_hash"] == after["version_hash"]
        assert before["extra"] == after["extra"]
        assert len(after["payload"]) - len(before["payload"]) == 459
    assert rows["ours"]["linked"]["version_hash"] != rows["ref"]["linked"]["version_hash"]
    assert rows["ours"]["nolink"]["extra"] != rows["ref"]["nolink"]["extra"]
    assert len(rows["ours"]["linked"]["region"]) - len(rows["ours"]["nolink"]["region"]) == 512
    assert len(rows["ref"]["linked"]["region"]) - len(rows["ref"]["nolink"]["region"]) == 448

    # A changed payload byte must break the central equality claim.
    tampered = bytearray(rows["ref"]["linked"]["payload"])
    tampered[500] ^= 1
    negative_control = bytes(tampered) != rows["ours"]["linked"]["payload"]
    assert negative_control

    result = {
        "ok": True,
        "input_sha256": {f"{side}_{stage}": rows[side][stage]["elf_sha256"]
                         for side in ("ours", "ref") for stage in ("nolink", "linked")},
        "snapshot": {side: {stage: {"bytes": rows[side][stage]["snapshot_length"],
                                     "header_bytes": rows[side][stage]["payload_offset"],
                                     "payload_bytes": len(rows[side][stage]["payload"]),
                                     "payload_sha256": sha(rows[side][stage]["payload"]),
                                     "extra_bytes": rows[side][stage]["extra_length"],
                                     "extra_sha256": sha(rows[side][stage]["extra"]),
                                     "symbol_bytes": rows[side][stage]["symbol_bytes"]}
                             for stage in ("nolink", "linked")}
                     for side in ("ours", "ref")},
        "cross_side_payload_equal_before_and_after": True,
        "per_side_extra_unchanged": True,
        "payload_growth_each_side": 459,
        "feature_string_marker_bytes": 50,
        "negative_control_detected": negative_control,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
