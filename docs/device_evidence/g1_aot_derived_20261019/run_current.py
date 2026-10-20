#!/usr/bin/env python3
"""Regenerate the three valid G1 AOT fixtures with current signed host tools."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path("/Users/Cruz/dart-3122/sdk")
RESEARCH = Path("/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle")
OLD = ROOT / "scratchpad/g1_g4_20261016/matrix_final"
OUT = ROOT / "scratchpad/g1_current_20261019"
GEN = SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot"
ANALYZER = SDK / "xcodebuild/ProductSimIosARM64/clang_arm64/analyze_snapshot"
KERNELS = {
    "hello": RESEARCH / "out_verify/hello.dill",
    "prog": RESEARCH / "out_disas/prog.dill",
    "base_dd": RESEARCH / "out_dd/base.dill",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(name, binary, flags, input_path, output, directory, provenance):
    command = [str(binary), *flags, str(input_path)]
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (directory / f"{name}.stdout").write_bytes(result.stdout)
    (directory / f"{name}.stderr").write_bytes(result.stderr)
    if result.returncode != 0 or not output.exists():
        raise RuntimeError(f"{name}: rc={result.returncode}, output={output.exists()}")
    provenance[name] = {
        "command": command, "rc": result.returncode,
        "input_sha256": digest(input_path), "output_sha256": digest(output),
        "output_bytes": output.stat().st_size,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "sdk_head": subprocess.check_output(["git", "-C", str(SDK), "rev-parse", "HEAD"],
                                            text=True).strip(),
        "gen_snapshot_sha256": digest(GEN),
        "analyze_snapshot_sha256": digest(ANALYZER),
        "fixtures": {},
    }
    for fixture, kernel in KERNELS.items():
        directory = OUT / fixture
        directory.mkdir(parents=True, exist_ok=True)
        records = {}
        elf = directory / "app.so"
        run("gen_elf", GEN,
            ["--snapshot_kind=app-aot-elf", f"--elf={elf}", "--print_shorebird_info"],
            kernel, elf, directory, records)
        assembly = directory / "app.S"
        run("gen_assembly", GEN,
            ["--snapshot_kind=app-aot-assembly", f"--assembly={assembly}",
             "--print_shorebird_info"], kernel, assembly, directory, records)
        outputs = (
            ("shorebird", ["--shorebird", f"--out={directory / 'shorebird.json'}"],
             directory / "shorebird.json"),
            ("dump_blobs", ["--dump_blobs", f"--out={directory / 'blobs.bin'}"],
             directory / "blobs.bin"),
            ("dump_object_pool_link_data",
             [f"--dump_object_pool_link_data={directory / 'pool.bin'}"],
             directory / "pool.bin"),
            ("disassemble", ["--disassemble", f"--out={directory / 'disassemble.json'}"],
             directory / "disassemble.json"),
        )
        for name, flags, output in outputs:
            run(name, ANALYZER, flags, elf, output, directory, records)
        table = OLD / f"as.{fixture}.ours.ddsm_in.ddt"
        dd_json = directory / "dd_table_data.json"
        run("dd_table_data", ANALYZER,
            ["--shorebird", f"--dd_table_data={table}", f"--out={dd_json}"],
            elf, dd_json, directory, records)
        records["dd_table_input_sha256"] = digest(table)
        report["fixtures"][fixture] = records
    (OUT / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({fixture: {name: value["output_bytes"] for name, value in
                      records.items() if isinstance(value, dict)} for fixture, records in
                      report["fixtures"].items()}, indent=2))


if __name__ == "__main__":
    main()
