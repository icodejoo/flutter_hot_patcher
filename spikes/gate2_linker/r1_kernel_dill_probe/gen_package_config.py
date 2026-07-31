#!/usr/bin/env python3
"""Generate a .dart_tool/package_config.json for dump_canonical_names.dart
that maps `package:kernel` (and its one dependency, _fe_analyzer_shared) to
their in-tree locations in the dart-sdk source checkout, so the script can
be run via the SDK's own JIT `dart` binary without needing a full pub-built
SDK distribution (which this project never built -- only the minimal
runtime/gen_snapshot pieces).
"""
import json, os, sys

sdk = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
out_dir = os.path.join(here, ".dart_tool")
os.makedirs(out_dir, exist_ok=True)

config = {
    "configVersion": 2,
    "packages": [
        {
            "name": "r1_probe",
            "rootUri": "../",
            "packageUri": "./",
        },
        {
            "name": "kernel",
            "rootUri": f"file://{sdk}/pkg/kernel/",
            "packageUri": "lib/",
        },
        {
            "name": "_fe_analyzer_shared",
            "rootUri": f"file://{sdk}/pkg/_fe_analyzer_shared/",
            "packageUri": "lib/",
        },
    ],
    "generated": "2026-07-31T00:00:00Z",
    "generator": "manual-probe",
    "generatorVersion": "0.0.0",
}
path = os.path.join(out_dir, "package_config.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
print("wrote", path)
