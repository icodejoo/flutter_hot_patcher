#!/usr/bin/env python3
"""
fhp_linker: equivalent to `aot_tools link --base=BASE --patch=PATCH --output=OUT`
Uses Shorebird's analyze_snapshot (or any --shorebird-mode JSON producer) as input.

Usage:
  python3 linker.py --analyze-snapshot=<binary> --base=<base.aot> --patch=<patch.aot> --output=<out.vmcode>

Output format (matches Shorebird .vmcode):
  [uint32 LE count N]
  [N × (uint32 sim_offset, uint32 cpu_offset)]
  [zero-pad to 16384 bytes]
  [patch ELF bytes verbatim]
"""
import argparse
import json
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

_PAGE_SIZE = 4096  # macOS/iOS page size

def _header_size(n_entries: int) -> int:
    content = 4 + n_entries * 8
    pages = (content + _PAGE_SIZE - 1) // _PAGE_SIZE
    return max(pages, 4) * _PAGE_SIZE  # at least 16384 (4 pages)

HEADER_SIZE = _PAGE_SIZE * 4  # 16384 default; actual = dynamic per entry count


def run_analyze_snapshot(analyze_snapshot_bin: str, aot_file: str) -> dict:
    """Run analyze_snapshot --shorebird and return parsed JSON."""
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp:
        tmp_path = tmp.name
    try:
        result = subprocess.run(
            [analyze_snapshot_bin, '--shorebird', f'--out={tmp_path}', aot_file],
            capture_output=True, text=True, check=True,
        )
        return json.loads(Path(tmp_path).read_text())
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def build_link_table(base_json: dict, patch_json: dict, **kwargs) -> list[tuple[int, int]]:
    """
    Match patch functions to base functions by subgraph_hash.
    Returns list of (sim_offset, cpu_offset) — patch offset, base offset.
    Unmatched functions are silently excluded (they'll run interpreted).
    """
    # Build lookup: subgraph_hash → list of base functions
    base_by_hash: dict[str, list] = {}
    for f in base_json['functions']:
        base_by_hash.setdefault(f['subgraph_hash'], []).append(f)

    # For collision resolution: (name, hash) → base function
    base_by_name_hash: dict[tuple, dict] = {
        (f['name'], f['subgraph_hash']): f
        for f in base_json['functions']
    }

    entries = []
    for pf in patch_json['functions']:
        # Optionally skip functions unsafe to run natively via SimulatorToCPU
        # (enabled via exclude_vm_unsafe=True for use with A7 vmcode loading)
        if kwargs.get('exclude_vm_unsafe', False):
            name = pf.get('name', '')
            if ('[Stub]' in name or name.startswith('stub ') or
                    name.startswith('stub_') or
                    name.startswith('_start') or
                    name.startswith('_get') or
                    name.startswith('_run') or
                    name.startswith('_kDart')):
                continue
        ph = pf['subgraph_hash']
        candidates = base_by_hash.get(ph, [])
        if len(candidates) == 1:
            entries.append((pf['offset'], candidates[0]['offset']))
        elif len(candidates) > 1:
            # Tiebreak by name (name is stable across same-source compilations)
            bf = base_by_name_hash.get((pf['name'], ph))
            if bf is not None:
                entries.append((pf['offset'], bf['offset']))
            # else: drop (Shorebird would use IDENTITY here, we conservatively skip)
    return entries


def write_vmcode(entries: list[tuple[int, int]], patch_elf: bytes) -> bytes:
    """Build the .vmcode binary."""
    N = len(entries)
    header = struct.pack('<I', N)
    for sim, cpu in entries:
        header += struct.pack('<II', sim, cpu)
    h_size = _header_size(len(entries))
    header = header.ljust(h_size, b'\0')
    return header + patch_elf


def link(
    analyze_snapshot_bin: str,
    base_aot: str,
    patch_aot: str,
    output_path: str,
    base_json_override: str | None = None,
    patch_json_override: str | None = None,
) -> float:
    """Run the full linker pipeline. Returns link_percentage."""
    if base_json_override:
        base_json = json.loads(Path(base_json_override).read_text())
    else:
        base_json = run_analyze_snapshot(analyze_snapshot_bin, base_aot)

    if patch_json_override:
        patch_json = json.loads(Path(patch_json_override).read_text())
    else:
        patch_json = run_analyze_snapshot(analyze_snapshot_bin, patch_aot)

    entries = build_link_table(base_json, patch_json)
    patch_elf = Path(patch_aot).read_bytes()
    vmcode = write_vmcode(entries, patch_elf)
    Path(output_path).write_bytes(vmcode)

    total_patch_code = sum(f['size'] for f in patch_json['functions'])
    linked_code = sum(
        next(f['size'] for f in patch_json['functions'] if f['offset'] == sim)
        for sim, _ in entries
    )
    link_pct = 100.0 * linked_code / total_patch_code if total_patch_code else 0.0
    return link_pct


def main():
    parser = argparse.ArgumentParser(description='fhp_linker: build Shorebird-compatible .vmcode')
    parser.add_argument('--analyze-snapshot', help='Path to analyze_snapshot binary')
    parser.add_argument('--base', required=True, help='Base AOT snapshot (.aot ELF)')
    parser.add_argument('--patch', required=True, help='Patch AOT snapshot (.aot ELF)')
    parser.add_argument('--output', required=True, help='Output .vmcode path')
    parser.add_argument('--base-json', help='Pre-computed base analyze_snapshot JSON (skip running binary)')
    parser.add_argument('--patch-json', help='Pre-computed patch analyze_snapshot JSON')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    if not args.analyze_snapshot and not (args.base_json and args.patch_json):
        parser.error('Either --analyze-snapshot or both --base-json and --patch-json required')

    link_pct = link(
        analyze_snapshot_bin=args.analyze_snapshot or '',
        base_aot=args.base,
        patch_aot=args.patch,
        output_path=args.output,
        base_json_override=args.base_json,
        patch_json_override=args.patch_json,
    )

    if args.verbose:
        print(f'Link percentage: {link_pct:.2f}%', file=sys.stderr)
        if link_pct < 80:
            print(f'[WARN] Low link percentage. Patched app may be slow.', file=sys.stderr)

    print(f'{link_pct:.2f}')


if __name__ == '__main__':
    main()
