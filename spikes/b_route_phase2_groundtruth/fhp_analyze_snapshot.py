#!/usr/bin/env python3
"""
fhp_analyze_snapshot: Shorebird-compatible analyze_snapshot replacement.

Usage:
  python3 fhp_analyze_snapshot.py --shorebird --out=<out.json> <snapshot.aot>

Produces the same JSON format as `analyze_snapshot --shorebird`:
  {"shorebird": "true", "snapshot_data": {...}, "functions": [...]}

Each function entry:
  {name, index_in_entries, offset, size,
   self_hash, subgraph_hash, op_subgraph_hash,
   self_pp, subgraph_pp, self_selectors, subgraph_selectors,
   self_field_table, subgraph_field_table, callees}

Hash computation:
  self_hash = SHA-1(instruction bytes)
  subgraph_hash = self_hash (simplified: no callee graph yet; see A4)
  op_subgraph_hash = self_hash

Note: Without A4 (link data for PP alignment), subgraph_hash == self_hash means
functions whose byte sequences differ due to PP reordering won't link.
This is correct for true function body changes and conservative for PP-only changes.
"""

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path


def parse_elf64(data: bytes) -> dict:
    """Parse an ELF64 file, returning section and symbol info."""
    assert data[:4] == b'\x7fELF', "Not an ELF file"
    assert data[4] == 2, "Not ELF64"

    e_shoff = struct.unpack_from('<Q', data, 40)[0]
    e_shentsize = struct.unpack_from('<H', data, 58)[0]
    e_shnum = struct.unpack_from('<H', data, 60)[0]
    e_shstrndx = struct.unpack_from('<H', data, 62)[0]

    # Parse section headers
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        sh_name = struct.unpack_from('<I', data, off)[0]
        sh_type = struct.unpack_from('<I', data, off + 4)[0]
        sh_addr = struct.unpack_from('<Q', data, off + 16)[0]
        sh_offset = struct.unpack_from('<Q', data, off + 24)[0]
        sh_size = struct.unpack_from('<Q', data, off + 32)[0]
        sections.append({'name_idx': sh_name, 'type': sh_type,
                         'addr': sh_addr, 'offset': sh_offset, 'size': sh_size})

    # Parse section name table
    shstrtab = data[sections[e_shstrndx]['offset']:
                    sections[e_shstrndx]['offset'] + sections[e_shstrndx]['size']]

    def sec_name(s):
        end = shstrtab.index(b'\0', s['name_idx'])
        return shstrtab[s['name_idx']:end].decode()

    named = {sec_name(s): s for s in sections}

    # Parse symbol table (.symtab + .strtab)
    syms = {}
    if '.symtab' in named and '.strtab' in named:
        strtab_s = named['.strtab']
        strtab = data[strtab_s['offset']:strtab_s['offset'] + strtab_s['size']]
        sym_s = named['.symtab']
        sym_data = data[sym_s['offset']:sym_s['offset'] + sym_s['size']]
        sym_entry_size = 24
        for i in range(sym_s['size'] // sym_entry_size):
            off = i * sym_entry_size
            st_name = struct.unpack_from('<I', sym_data, off)[0]
            st_value = struct.unpack_from('<Q', sym_data, off + 8)[0]
            st_size = struct.unpack_from('<Q', sym_data, off + 16)[0]
            st_info = sym_data[off + 4]
            st_type = st_info & 0xF
            name_end = strtab.index(b'\0', st_name)
            name = strtab[st_name:name_end].decode()
            # STT_FUNC = 2, STT_NOTYPE = 0
            if st_value and st_name and name:  # include STT_OBJECT (type=1) for base syms
                # Could be multiple syms for same address; keep all
                syms.setdefault(name, []).append((st_value, st_size))

    return {'sections': named, 'syms': syms}


def sha1hex(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def analyze_shorebird(aot_path: str) -> dict:
    data = Path(aot_path).read_bytes()
    elf = parse_elf64(data)
    sections = elf['sections']
    syms = elf['syms']

    # Find the isolate snapshot instructions base
    isolate_sym = syms.get('_kDartIsolateSnapshotInstructions', [(0, 0)])[0]
    vm_sym = syms.get('_kDartVmSnapshotInstructions', [(0, 0)])[0]
    isolate_base_addr = isolate_sym[0]
    vm_base_addr = vm_sym[0]

    # Find text section (instructions live here)
    text_sec = sections.get('.text', {})
    text_addr = text_sec.get('addr', 0)
    text_file_off = text_sec.get('offset', 0)
    text_size = text_sec.get('size', 0)

    def code_bytes(addr: int, size: int) -> bytes:
        """Extract code bytes from the ELF at the given virtual address."""
        file_off = text_file_off + (addr - text_addr)
        if file_off < 0 or file_off + size > len(data):
            return b''
        return data[file_off:file_off + size]

    # Collect all functions: (offset_from_isolate_base, size, name, addr)
    # offset = addr - isolate_base_addr
    functions = []
    seen_offsets = set()
    for name, entries in syms.items():
        if name.startswith('_k') or not entries:
            continue
        for addr, size in entries:
            if addr < isolate_base_addr:
                continue  # VM section or non-instruction
            offset = addr - isolate_base_addr
            if offset in seen_offsets:
                continue
            seen_offsets.add(offset)
            functions.append((offset, size, name, addr))

    # Sort by offset (matches Shorebird's index_in_entries ordering)
    functions.sort(key=lambda x: x[0])

    # Build JSON output
    func_list = []
    for idx, (offset, size, name, addr) in enumerate(functions):
        payload = code_bytes(addr, size)
        h = sha1hex(payload) if payload else sha1hex(b'')
        func_list.append({
            'name': name,
            'index_in_entries': idx,
            'offset': offset,
            'size': size,
            'self_hash': h,
            'subgraph_hash': h,       # simplified: no callee graph
            'op_subgraph_hash': h,    # simplified: no PP normalization
            'self_pp': [],
            'subgraph_pp': [],
            'self_selectors': [],
            'subgraph_selectors': [],
            'self_field_table': [],
            'subgraph_field_table': [],
            'callees': [],
        })

    # snapshot_data section (mirrors Shorebird format)
    text_s = sections.get('.text', {})
    rodata_s = sections.get('.rodata', {})
    snap = {
        'vm_data_length': rodata_s.get('size', 0),
        'vm_instructions_length': text_s.get('size', 0),
        'vm_data_hash': sha1hex(data[rodata_s['offset']:rodata_s['offset'] + rodata_s.get('size', 0)]
                                if '.rodata' in sections else b''),
        'vm_instructions_hash': sha1hex(data[text_file_off:text_file_off + text_size]),
    }

    return {
        'shorebird': 'true',
        'snapshot_data': snap,
        'functions': func_list,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--shorebird', action='store_true', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('snapshot')
    args = p.parse_args()

    result = analyze_shorebird(args.snapshot)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(f"Wrote {len(result['functions'])} functions to {args.out}", file=sys.stderr)


if __name__ == '__main__':
    main()
