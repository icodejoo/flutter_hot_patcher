#!/usr/bin/env python3
"""Reassemble archived AOT assembly and compare its snapshot regions to ELF."""

import hashlib
import importlib.util
import json
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "scratchpad/g1_g4_20261016/matrix_final"
SYMBOLS_PATH = ROOT / "docs/device_evidence/g1_rootcause_20261016/symbols.py"
NAMES = (
    "_kDartVmSnapshotData",
    "_kDartIsolateSnapshotData",
    "_kDartVmSnapshotInstructions",
    "_kDartIsolateSnapshotInstructions",
)
spec = importlib.util.spec_from_file_location("g1_symbols", SYMBOLS_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def symbols_in_macho_object(data):
    """Return Mach-O symbol bytes with their containing section bounds."""
    magic, _, _, _, command_count, _, _, _ = struct.unpack_from("<IiiIIIII", data)
    assert magic == 0xFEEDFACF
    sections = []
    text_relocations = []
    symtab = None
    cursor = 32
    for _ in range(command_count):
        command, size = struct.unpack_from("<II", data, cursor)
        if command == 0x19:  # LC_SEGMENT_64
            section_count = struct.unpack_from("<I", data, cursor + 64)[0]
            for index in range(section_count):
                position = cursor + 72 + index * 80
                name, _, address, length, file_offset = struct.unpack_from(
                    "<16s16sQQI", data, position
                )
                decoded_name = name.rstrip(b"\0").decode()
                sections.append((decoded_name, address, length, file_offset))
                if decoded_name == "__text":
                    relocation_offset, relocation_count = struct.unpack_from(
                        "<II", data, position + 56
                    )
                    text_relocations = [struct.unpack_from(
                        "<I", data, relocation_offset + item * 8
                    )[0] for item in range(relocation_count)]
        elif command == 0x2:  # LC_SYMTAB
            symtab = struct.unpack_from("<IIII", data, cursor + 8)
        cursor += size
    assert symtab is not None
    sym_offset, count, string_offset, _ = symtab
    result = {}
    for index in range(count):
        name_index, _, section_index, _, address = struct.unpack_from(
            "<IBBHQ", data, sym_offset + index * 16
        )
        if not section_index:
            continue
        start = string_offset + name_index
        name = data[start:data.index(b"\0", start)].decode()
        section = sections[section_index - 1]
        offset = section[3] + address - section[1]
        result[name] = (section[0], offset, section[3] + section[2])
    return result, text_relocations


def compare_region(assembly, elf, instructions):
    if len(assembly) != len(elf):
        return False, []
    differing = [index for index, (x, y) in enumerate(zip(assembly, elf)) if x != y]
    # Platform-dependent instruction-image header values occupy 80..103;
    # Mach-O records a relocation at offset 80.
    acceptable = all(80 <= index < 104 for index in differing) if instructions else not differing
    return acceptable, differing


def main():
    hashes = {}
    report = {}
    with tempfile.TemporaryDirectory(prefix="g1_assembly_check_") as directory:
        for fixture in ("hello", "prog", "base_dd"):
            report[fixture] = {}
            for side in ("ours", "theirs"):
                source = MATRIX / "m21" / side / fixture / "assembly/app.S"
                elf_path = MATRIX / f"gs.{fixture}.{side}.so"
                object_path = Path(directory) / f"{fixture}.{side}.o"
                for path in (source, elf_path):
                    hashes[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
                subprocess.run(["clang", "-c", str(source), "-o", str(object_path)],
                               check=True, capture_output=True)
                object_bytes = object_path.read_bytes()
                macho_symbols, relocations = symbols_in_macho_object(object_bytes)
                elf_symbols = {item["name"]: item["bytes"] for item in
                               module.symbols(elf_path.read_bytes())}
                entries = {}
                text_start = macho_symbols["_kDartVmSnapshotInstructions"][1]
                expected_relocations = {
                    macho_symbols[name][1] - text_start + 80
                    for name in NAMES if name.endswith("Instructions")
                }
                assert set(relocations) == expected_relocations
                for name in NAMES:
                    section, offset, section_end = macho_symbols[name]
                    target = elf_symbols[name]
                    assert offset + len(target) <= section_end
                    actual = object_bytes[offset:offset + len(target)]
                    instructions = name.endswith("Instructions")
                    ok, differing = compare_region(actual, target, instructions)
                    entries[name] = {
                        "ok": ok, "length": len(target), "section": section,
                        "header_relocation_bytes": len(differing),
                        "difference_range": [min(differing), max(differing)] if differing else [],
                    }
                report[fixture][side] = entries
    control_data = bytearray(b"x" * 128)
    control_elf = bytes(control_data)
    control_data[104] ^= 1
    negative_control = not compare_region(control_data, control_elf, True)[0]
    output = {
        "source": "archived 2026-10-16 matrix; app.S compiled with local clang into temporary Mach-O objects",
        "fixtures": report, "input_sha256": hashes,
        "negative_control_outside_relocation_detected": negative_control,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not negative_control or not all(
        entry["ok"] for fixture in report.values() for side in fixture.values()
        for entry in side.values()
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
