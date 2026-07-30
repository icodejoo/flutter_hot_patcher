#!/usr/bin/env python3
"""P0 probe / CanonicalName-map prototype: parse a --save-debugging-info DWARF
file and emit, per code range, a library-qualified canonical key that
disambiguates bare-name collisions.

canonical key = decl_file (source URI ~= library) + DW_AT_name (Class.method).
Concrete subprograms carry low_pc/high_pc + an abstract_origin ref to the
spec DIE that holds name/decl_file. We resolve the ref and join.

Usage: dwarf_names.py <debug-elf> [name-filter]
"""
import subprocess, sys, re

def main():
    dbg = sys.argv[1]
    filt = sys.argv[2] if len(sys.argv) > 2 else None
    info = subprocess.check_output(['readelf', '--debug-dump=info', dbg]).decode(errors='replace')
    raw = subprocess.check_output(['readelf', '--debug-dump=rawline', dbg]).decode(errors='replace')

    files = {}
    for m in re.finditer(r'^\s*(\d+)\t\d+\t\d+\t\d+\t(.+)$', raw, re.M):
        files[int(m.group(1))] = m.group(2).strip()

    # Parse each DIE: offset, tag, and its attributes. readelf prints DIEs as
    # " <depth><offset>: Abbrev Number: N (DW_TAG_x)" then indented attrs.
    die_re = re.compile(r'^\s*<\d+><([0-9a-f]+)>:.*\((DW_TAG_\w+)\)', re.M)
    spec = {}   # offset -> (name, decl_file, decl_line)
    starts = [(m.start(), m.group(1), m.group(2)) for m in die_re.finditer(info)]
    for i, (pos, off, tag) in enumerate(starts):
        body = info[pos:starts[i + 1][0] if i + 1 < len(starts) else len(info)]
        def at(k):
            m = re.search(r'DW_AT_' + k + r'\s*:\s*(.+)', body)
            return m.group(1).strip() if m else None
        if tag == 'DW_TAG_subprogram':
            name = at('name')
            if name is not None:
                spec[off] = (name, at('decl_file'), at('decl_line'))
            lo = at('low_pc')
            ao = at('abstract_origin')
            if lo is not None:
                # concrete instance: resolve abstract_origin -> spec name/file
                ref = None
                if ao:
                    r = re.search(r'<0x([0-9a-f]+)>', ao) or re.search(r'\[?0x([0-9a-f]+)', ao)
                    if r:
                        ref = r.group(1)
                nm, df, dl = spec.get(ref, (name, at('decl_file'), at('decl_line')))
                fidx = int(df) if df and df.isdigit() else None
                fpath = files.get(fidx, '?')
                lo_val = int(re.search(r'0x([0-9a-f]+)', lo).group(1), 16)
                if nm and (not filt or filt in (nm or '')):
                    print(f'low_pc=0x{lo_val:x}  key={fpath} :: {nm}  (line {dl})')

if __name__ == '__main__':
    main()
