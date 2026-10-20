#!/usr/bin/env python3
"""Explain RC10's 64-byte ELF symbol growth gap from archived snapshots."""

import hashlib
import importlib.util
import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUN = ROOT / "scratchpad/g1_rc10_20261016"
SYMBOLS = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
PRIOR = ROOT / "docs/device_evidence/g1_followup_20261016/verification.json"
spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def dimensions(path):
    data = path.read_bytes()
    regions = {item["name"]: item["bytes"] for item in module.symbols(data)}
    region = regions["_kDartIsolateSnapshotData"]
    assert struct.unpack_from("<I", region)[0] == 0xDCDCF5F5
    snapshot = struct.unpack_from("<q", region, 4)[0] + 4
    aligned = (snapshot + 63) & ~63
    extra = struct.unpack_from("<I", region, aligned)[0]
    logical = snapshot + extra
    symbol = len(region)
    assert 0 < snapshot <= logical <= symbol
    return {
        "snapshot_bytes": snapshot,
        "extra_bytes": extra,
        "logical_bytes": logical,
        "symbol_bytes": symbol,
        "symbol_padding_bytes": symbol - logical,
    }, hashlib.sha256(data).hexdigest()


def validate(rows):
    growth = {}
    for side in ("ours", "ref"):
        before, after = rows[side]["nolink"], rows[side]["linked"]
        growth[side] = {
            key: after[key] - before[key]
            for key in ("snapshot_bytes", "extra_bytes", "logical_bytes",
                        "symbol_bytes", "symbol_padding_bytes")
        }
        assert growth[side]["symbol_bytes"] == (
            growth[side]["logical_bytes"] + growth[side]["symbol_padding_bytes"]
        )
    ok = (
        growth["ours"]["snapshot_bytes"] == growth["ref"]["snapshot_bytes"] == 459
        and growth["ours"]["extra_bytes"] == growth["ref"]["extra_bytes"] == 0
        and growth["ours"]["logical_bytes"] == growth["ref"]["logical_bytes"] == 459
        and growth["ours"]["symbol_bytes"] == 512
        and growth["ref"]["symbol_bytes"] == 448
        and growth["ours"]["symbol_padding_bytes"] == 53
        and growth["ref"]["symbol_padding_bytes"] == -11
        and rows["ours"]["nolink"]["logical_bytes"] -
            rows["ref"]["nolink"]["logical_bytes"] == 50
        and rows["ours"]["linked"]["logical_bytes"] -
            rows["ref"]["linked"]["logical_bytes"] == 50
    )
    return ok, growth


def main():
    rows, hashes = {}, {}
    for side in ("ours", "ref"):
        rows[side] = {}
        for stage, filename in (("nolink", f"{side}_nolink_verbose.so"),
                                ("linked", f"{side}_verbose.so")):
            path = RUN / filename
            rows[side][stage], hashes[str(path.relative_to(ROOT))] = dimensions(path)
    ok, growth = validate(rows)
    prior = json.loads(PRIOR.read_text())
    hashes[str(PRIOR.relative_to(ROOT))] = hashlib.sha256(PRIOR.read_bytes()).hexdigest()
    prior_ok = prior["passed"] and all(prior["checks"][key] for key in (
        "RC10/dispatch_targets", "RC10/link_metadata", "RC10/ours_code_unchanged",
        "RC10/ref_code_unchanged", "RC10/encoding_delta_localized"
    ))
    altered = json.loads(json.dumps(rows))
    altered["ref"]["linked"]["snapshot_bytes"] += 1
    negative_control = not validate(altered)[0]
    output = {
        "source": "archived 2026-10-16 RC10 fixtures; no new binary run",
        "ok": ok and prior_ok, "measurements": rows, "growth": growth,
        "prior_semantic_checks_passed": prior_ok,
        "negative_control_detected": negative_control,
        "input_sha256": hashes,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not output["ok"] or not negative_control:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
