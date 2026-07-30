#!/usr/bin/env python3
"""Minimal Gate 2 diff-linker: compute the "must reinterpret" transitive
closure between two AOT snapshots.

Implements the two-condition fixpoint established by probe P2
(../probe_reloc_equivalence/NOTES.md): a function may be judged EQUIVALENT
(entry -> baseline machine code, runs native) iff
  (1) its own machine code is byte-for-byte equal across base/patch, AND
  (2) every function it directly calls is also equivalent.
Failure propagates up the call graph from the byte-changed set, stopping at
virtual-call boundaries (dispatch table, redirectable — Gate 1 V2).

Alignment (probe P0): AOT ELF symbol names are NOT unique (4 `main`s, countless
toString/==). With --*-debug (a gen_snapshot --save-debugging-info DWARF ELF)
each function is keyed by CanonicalName = source-file URI + Class.method; without
it, alignment falls back to bare ELF names. Colliding keys can't be aligned 1:1:
a colliding key is judged equivalent only when its FULL multiset of normalized
signatures is identical base<->patch (see the SOUNDNESS CAVEATS below).

SOUNDNESS CAVEATS (see REVIEW_diff_linker.md — this is a SPIKE MEASUREMENT tool,
not a production linker):
  - Condition 1 compares NORMALIZED disassembly text, not raw bytes. Object-pool
    slots are wildcarded (normalize()), so a change confined to a pool constant
    (String / double / big-int / const object literal) is INVISIBLE. A production
    linker must parse the object pool and compare slot contents.
  - The multiset-equal refinement for colliding keys is NOT sound under body
    PERMUTATION (two colliding instances swapping bodies leaves the multiset
    unchanged). Production alignment must be instance-level (CanonicalName +
    decl_line/column), not an unordered multiset.
  - x86-64 / GNU-objdump only. On arm64 the `call` extraction, the %r15 pool
    wildcard, and the ret/int3/nop mnemonics do not match — condition-2 edges
    silently vanish. This tool hard-fails rather than silently mis-report when it
    detects a non-GNU / arch-mismatched / stripped input (see the guards in main).

Usage: diff_linker.py BASE PATCH [--list] [--optimistic] [--emit-closure]
                      [--base-debug B.debug --patch-debug P.debug]
                      [--base-src-root DIR --patch-src-root DIR]
  --optimistic: drop ambiguous-changed seeds. This is a LOWER BOUND for
    measurement only — NOT usable to generate a real patch (it can omit genuinely
    changed colliding instances).
"""
import subprocess, sys, re, bisect

# Build {code address -> canonical key} from a --save-debugging-info DWARF ELF
# (P0 finding, see probe_canonical_name/NOTES.md). canonical key = source-file
# URI (~= library) + DW_AT_name (Class.method). Returns {} if no debug file
# (caller falls back to bare names).
#
# 从 --save-debugging-info 的 DWARF 建 {代码地址 -> canonical key}(P0)。无调试文件返回 {}。
def dwarf_canonical_map(debug_path, strip_prefix=None):
    if not debug_path:
        return {}
    info = subprocess.check_output(['readelf', '--debug-dump=info', debug_path]).decode(errors='replace')
    raw = subprocess.check_output(['readelf', '--debug-dump=rawline', debug_path]).decode(errors='replace')
    files = {}
    for m in re.finditer(r'^\s*(\d+)\t\d+\t\d+\t\d+\t(.+)$', raw, re.M):
        files[int(m.group(1))] = m.group(2).strip()
    die_re = re.compile(r'^\s*<\d+><([0-9a-f]+)>:.*\((DW_TAG_\w+)\)', re.M)
    starts = [(m.start(), m.group(1), m.group(2)) for m in die_re.finditer(info)]
    spec, addr_key = {}, {}
    for i, (pos, off, tag) in enumerate(starts):
        body = info[pos:starts[i + 1][0] if i + 1 < len(starts) else len(info)]
        def at(k):
            mm = re.search(r'DW_AT_' + k + r'\s*:\s*(.+)', body)
            return mm.group(1).strip() if mm else None
        if tag != 'DW_TAG_subprogram':
            continue
        name = at('name')
        if name is not None:
            spec[off] = (name, at('decl_file'))
        lo = at('low_pc')
        if lo is None:
            continue
        ref = None
        ao = at('abstract_origin')
        if ao:
            r = re.search(r'<0x([0-9a-f]+)>', ao) or re.search(r'0x([0-9a-f]+)', ao)
            ref = r.group(1) if r else None
        nm, df = spec.get(ref, (name, at('decl_file')))
        if nm is None:
            continue
        fidx = int(df) if df and df.isdigit() else None
        fpath = files.get(fidx, '?')
        if strip_prefix:
            fpath = fpath.replace('file://' + strip_prefix, '').replace(strip_prefix, '')
            fpath = fpath.lstrip('/')
        addr = int(re.search(r'0x([0-9a-f]+)', lo).group(1), 16)
        addr_key[addr] = f'{fpath}::{nm}'
    return addr_key

# Parse a snapshot into {key: [block,...]}. With addr_map (from DWARF), key is the
# canonical key; else the bare ELF symbol name. Each block is a list of
# (raw_bytes, normalized_mnemonic_placeholder, resolved_call_target). Returns also
# a total instruction count so callers can hard-fail on a non-GNU/empty parse.
def parse_snapshot(path, addr_map=None):
    addr_map = addr_map or {}
    sorted_addrs = sorted(addr_map)  # for secondary-entry (<sym+0xNN>) resolution
    # Resolve a call-target address to a canonical key: exact hit, else the
    # function whose low_pc is the greatest <= addr (a secondary/unchecked entry
    # point of that function — S4 fix). Errs toward over-inclusion (safe side),
    # never toward a soundness miss. Returns None if no debug map.
    def resolve(taddr):
        if taddr in addr_map:
            return addr_map[taddr]
        if not sorted_addrs:
            return None
        i = bisect.bisect_right(sorted_addrs, taddr) - 1
        return addr_map[sorted_addrs[i]] if i >= 0 else None

    out = subprocess.check_output(['objdump', '-d', path]).decode(errors='replace')
    funcs = {}
    cur_block = None
    ninsn = 0
    for line in out.splitlines():
        h = re.match(r'^([0-9a-f]+) <(.+)>:$', line)
        if h:
            addr = int(h.group(1), 16)
            key = addr_map.get(addr, h.group(2))  # header: EXACT only (no nearest)
            cur_block = []
            funcs.setdefault(key, []).append(cur_block)
            continue
        m = re.match(r'\s+[0-9a-f]+:\t([0-9a-f ]+?)\t(.*)', line)
        if not m or cur_block is None:
            continue
        raw, mnem = m.group(1).strip(), m.group(2).strip()
        if not raw:
            continue
        # S5 fix: capture the FULL symbol to the last '>' (greedy), then strip a
        # trailing '+0xNN' offset — so `<OpC.+>` (operator+) and
        # `<f.<anonymous closure>>` keep their real names instead of being cut at
        # '+' or the inner '>'.
        cm = re.search(r'call[a-z]*\s+([0-9a-f]+) <(.+)>', mnem)
        target = None
        if cm:
            taddr = int(cm.group(1), 16)
            bare = re.sub(r'\+0x[0-9a-f]+$', '', cm.group(2))
            target = resolve(taddr) or bare  # canonical (incl. secondary entry) or bare name
        cur_block.append((raw, mnem, target))
        ninsn += 1
    return funcs, ninsn

# Normalize one instruction's disassembly text to strip relocation/drift noise so
# condition 1 compares LOGIC not layout (V9): drop absolute call/jmp target addr;
# wildcard object-pool slot `0xNN(%r15)`. Object FIELD offsets are KEPT (V9).
def normalize(mnem):
    mnem = re.sub(r'\b[0-9a-f]+ (<[^>]+>)', r'\1', mnem)       # drop abs call/jmp target addr
    mnem = re.sub(r'0x[0-9a-f]+\(%r15\)', 'POOL(%r15)', mnem)  # wildcard pool slot
    return mnem

# Condition-1 signature of one block. S2 fix: fold the RESOLVED call target into
# the signature so retargeting a call to a different same-named function (which
# leaves the instruction text identical after normalize drops the address) is
# caught. int3/nop inter-function padding is filtered.
def sig(block):
    parts = []
    for _, m, t in block:
        if m.startswith('int3') or m.startswith('nop'):
            continue
        parts.append(normalize(m) + (f' ->{t}' if t else ''))
    return ' | '.join(parts)

# Resolved direct-call target keys appearing in any block of a function.
def all_targets(blocks):
    return {t for b in blocks for _, _, t in b if t}

def _opt(flag):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None

def _die(msg):
    print(f'diff_linker: FATAL: {msg}', file=sys.stderr)
    sys.exit(2)

def main():
    base_path, patch_path = sys.argv[1], sys.argv[2]
    list_all = '--list' in sys.argv[3:]
    optimistic = '--optimistic' in sys.argv[3:]
    base_dbg, patch_dbg = _opt('--base-debug'), _opt('--patch-debug')
    base_root, patch_root = _opt('--base-src-root'), _opt('--patch-src-root')

    # Guard: asymmetric DWARF => disjoint key spaces => bogus ~100% closure.
    if bool(base_dbg) != bool(patch_dbg):
        _die('exactly one of --base-debug/--patch-debug given; both or neither '
             '(asymmetric => canonical vs bare-name keys never align).')

    base_map = dwarf_canonical_map(base_dbg, base_root)
    patch_map = dwarf_canonical_map(patch_dbg, patch_root)
    if base_map or patch_map:
        print(f'alignment                     : CanonicalName (DWARF: '
              f'{len(base_map)} base / {len(patch_map)} patch code addrs mapped)')
    else:
        print('alignment                     : bare ELF symbol name (no --*-debug)')

    base, base_n = parse_snapshot(base_path, base_map)
    patch, patch_n = parse_snapshot(patch_path, patch_map)

    # Guard: non-GNU objdump / bad format => zero instructions parsed => every
    # block empty => everything silently "equivalent". Fail loudly instead.
    if base_n == 0 or patch_n == 0:
        _die(f'parsed {base_n}/{patch_n} instructions — objdump output not '
             f'recognized (non-GNU objdump? wrong arch? not a code snapshot?). '
             f'Refusing to report "all equivalent" from an empty parse.')
    # Guard: stripped snapshot => far fewer function blocks than DWARF addrs =>
    # per-function diff collapses. Warn (don't hard-fail: bare-name mode is legit).
    for tag, fmap, dmap in (('base', base, base_map), ('patch', patch, patch_map)):
        if dmap and len(fmap) < 0.5 * len(dmap):
            print(f'diff_linker: WARNING: {tag} parsed {len(fmap)} function blocks '
                  f'but DWARF has {len(dmap)} addrs — snapshot may be STRIPPED; '
                  f'per-function diff is unreliable.', file=sys.stderr)

    added = set(patch) - set(base)
    removed = set(base) - set(patch)
    common = set(base) & set(patch)

    # Colliding keys: judged equivalent only if the full multiset of sigs matches.
    # NB: NOT sound under body permutation (see docstring / REVIEW S3).
    def multiset(blocks):
        return sorted(sig(b) for b in blocks)
    ambiguous = {n for n in common if len(base[n]) > 1 or len(patch[n]) > 1}
    ambiguous_changed = {n for n in ambiguous if multiset(base[n]) != multiset(patch[n])}
    ambiguous_cleared = ambiguous - ambiguous_changed
    aligned = common - ambiguous

    byte_changed = {n for n in aligned if sig(base[n][0]) != sig(patch[n][0])}

    seed_ambiguous = set() if optimistic else set(ambiguous_changed)
    must_interp = set(byte_changed) | set(added) | seed_ambiguous

    changed = True
    while changed:
        changed = False
        for n in patch:
            if n in must_interp:
                continue
            if all_targets(patch[n]) & must_interp:
                must_interp.add(n)
                changed = True

    equivalent = set(patch) - must_interp
    total = len(patch)
    print(f'mode                          : '
          f'{"OPTIMISTIC (lower bound; NOT for patch gen)" if optimistic else "CONSERVATIVE"}')
    print(f'total function names in patch : {total}')
    print(f'added (new, interpret)        : {len(added)}')
    print(f'removed (gone from base)      : {len(removed)}')
    print(f'ambiguous (colliding key)     : {len(ambiguous)}'
          f'   ({100.0*len(ambiguous)/max(1,total):.1f}%); of them changed (seeded): '
          f'{len(ambiguous_changed)}, unchanged (multiset-equal → equivalent): '
          f'{len(ambiguous_cleared)}')
    print(f'byte-changed (cond 1)         : {len(byte_changed)}')
    print(f'must reinterpret (closure)    : {len(must_interp)}'
          f'   ({100.0*len(must_interp)/max(1,total):.1f}% of program)')
    print(f'  of which propagated (cond 2): '
          f'{len(must_interp) - len(byte_changed) - len(added) - len(seed_ambiguous)}')
    print(f'equivalent (baseline)         : {len(equivalent)}')

    # Soundness warnings (REVIEW S3/S6): the tool cannot vouch for these on its own.
    if removed:
        print(f'diff_linker: WARNING: {len(removed)} key(s) present in base but not '
              f'patch (rename / delete / ICF-fold). NOT cascaded — callers reaching '
              f'them via non-direct edges may be missed (REVIEW S6).', file=sys.stderr)
    if ambiguous_cleared:
        print(f'diff_linker: WARNING: {len(ambiguous_cleared)} colliding key(s) cleared '
              f'as equivalent by multiset — UNSOUND under body permutation (REVIEW S3).',
              file=sys.stderr)

    if '--emit-closure' in sys.argv[3:]:
        for n in sorted(must_interp):
            print(f'CLOSURE\t{n}')

    if list_all:
        # propagated = closure minus everything directly seeded (byte-changed +
        # added + the ambiguous keys we actually seeded). Bugfix: subtract
        # seed_ambiguous, not all `ambiguous`.
        propagated = must_interp - byte_changed - added - seed_ambiguous
        if added or removed:
            print('\n--- added (in patch, not base) ---')
            for n in sorted(added):
                print(f'  {n}')
            print('--- removed (in base, not patch) ---')
            for n in sorted(removed):
                print(f'  {n}')
        print('\n--- byte-changed (condition 1) ---')
        for n in sorted(byte_changed):
            print(f'  {n}')
        if seed_ambiguous:
            print('--- ambiguous-changed (colliding key, seeded) ---')
            for n in sorted(seed_ambiguous):
                print(f'  {n}')
        print('--- propagated via call graph (condition 2) ---')
        for n in sorted(propagated):
            hit = sorted(all_targets(patch[n]) & must_interp)
            print(f'  {n}   (calls: {", ".join(hit)})')

if __name__ == '__main__':
    main()
