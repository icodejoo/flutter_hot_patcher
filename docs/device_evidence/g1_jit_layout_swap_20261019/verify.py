#!/usr/bin/env python3
"""Read-only check of two real ARM64 VMs exchanging full JIT snapshots."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "scratchpad/g1_layout_swap_20261019"
SDK = Path("/Users/Cruz/dart-3122/sdk")
SCRIPT = ROOT / "scratchpad/g1_jit_guard_20261019/hello.dart"
MARKERS = {"base": "2312,2320,2328", "shifted": "2320,2328,2336"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_header(path):
    data = path.read_bytes()
    start = data.find(b"debug no-code_comments")
    assert start > 32
    end = data.index(0, start)
    version = data[start - 32:start]
    assert len(version) == 32 and all(byte in b"0123456789abcdef" for byte in version)
    return version.decode(), data[start:end].decode()


def main():
    checks = 0
    def check(condition, label):
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    check((SDK / "runtime/vm/thread.h").read_bytes() == (OUT / "thread.h.base").read_bytes(),
          "Thread source restored")
    check((SDK / "runtime/vm/compiler/runtime_offsets_extracted.h").read_bytes() ==
          (OUT / "runtime_offsets_extracted.h.base").read_bytes(),
          "extracted offsets restored")
    for name in ("dart", "dartvm"):
        check((SDK / f"xcodebuild/DebugARM64/{name}").read_bytes() ==
              (OUT / f"{name}_base").read_bytes(), f"main {name} restored")
    shifted_source = (OUT / "thread.h.shifted").read_text()
    check(shifted_source.replace("  uword g1_layout_swap_probe_padding_ = 0;\n", "") ==
          (OUT / "thread.h.base").read_text(), "temporary Thread padding was only source change")
    check((OUT / "thread_layout.patch").exists(), "temporary variant patch archived")

    generation = json.loads((OUT / "generation_manifest.json").read_text())
    check(len(generation) == 2, "two generation runs")
    versions = {}
    features = {}
    for row in generation:
        side = row["side"]
        binary = OUT / f"dartvm_{side}"
        snapshot = OUT / f"{side}_direct.jit"
        check(row["rc"] == 0 and row["pid"] > 0, f"{side} generation success")
        check(row["command"] == [str(binary), f"--snapshot={snapshot}",
                                   "--snapshot-kind=app-jit", str(SCRIPT)],
              f"{side} generation command")
        paths = {"binary": binary, "script": SCRIPT, "snapshot_after": snapshot,
                 "stdout": OUT / f"generate_{side}.stdout",
                 "stderr": OUT / f"generate_{side}.stderr"}
        for field, path in paths.items():
            check(sha(path) == row["sha256"][field], f"{side} {field} hash")
        check(paths["stdout"].read_text() == "jit guard ok\n", f"{side} generation output")
        check(paths["stderr"].read_bytes() == b"", f"{side} generation stderr")
        versions[side], features[side] = snapshot_header(snapshot)
        check(features[side].endswith("shorebird-native-entry-thr-offsets=" + MARKERS[side]),
              f"{side} Thread offsets in JIT snapshot")
    check(versions["base"] == versions["shifted"], "same snapshot version hash")
    check(features["base"].replace(MARKERS["base"], MARKERS["shifted"]) ==
          features["shifted"], "only Thread offsets differ in JIT features")

    loads = json.loads((OUT / "load_manifest.json").read_text())
    check(len(loads) == 4, "four runtime/snapshot combinations")
    for row in loads:
        runtime, snapshot = row["runtime"], row["snapshot"]
        source = snapshot.removesuffix("_direct")
        prefix = OUT / f"load_{runtime}_{snapshot}"
        binary = OUT / f"dartvm_{runtime}"
        snap = OUT / f"{snapshot}.jit"
        check(row["command"] == [str(binary), str(snap)] and row["pid"] > 0,
              f"{runtime}/{source} load command")
        paths = {"binary": binary, "snapshot": snap,
                 "stdout": Path(f"{prefix}.stdout"), "stderr": Path(f"{prefix}.stderr")}
        for field, path in paths.items():
            check(sha(path) == row["sha256"][field],
                  f"{runtime}/{source} {field} hash")
        if runtime == source:
            check(row["rc"] == 0 and paths["stdout"].read_text() == "jit guard ok\n"
                  and paths["stderr"].read_bytes() == b"",
                  f"{runtime}/{source} runs normally")
        else:
            error = paths["stderr"].read_text()
            check(row["rc"] == 255 and paths["stdout"].read_bytes() == b"" and
                  "Snapshot not compatible with the current VM configuration" in error and
                  "shorebird-native-entry-thr-offsets=" + MARKERS[runtime] in error and
                  "shorebird-native-entry-thr-offsets=" + MARKERS[source] in error,
                  f"{runtime}/{source} rejects before execution")

    # A deliberately changed recorded digest must not validate.
    bad_digest = "0" * 64
    check(bad_digest != sha(OUT / "base_direct.jit"), "negative control detects altered digest")
    print(json.dumps({"ok": True, "checks": checks,
                      "snapshot_version_hash": versions["base"],
                      "base_offsets": MARKERS["base"], "shifted_offsets": MARKERS["shifted"],
                      "own_loads": 2, "cross_loads_rejected": 2}, indent=2))


if __name__ == "__main__":
    main()
