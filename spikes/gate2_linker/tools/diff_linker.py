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
  - GNU-objdump/readelf format only (llvm-objdump's differing column layout
    parses to zero instructions — guarded, hard-fails rather than silently
    reporting "all equivalent", see REVIEW Tier A1). x86-64 and arm64 are both
    supported (ARCH_CONFIG, auto-detected via `readelf -h`, see
    ARM64_PORT_NOTES.md) — call-site mnemonic (`call`/`bl`), the pool register
    (`%r15`/`x27`) and syntax (hex-in-parens/decimal-in-brackets), and
    inter-function padding mnemonics all differ per arch and are looked up from
    ARCH_CONFIG rather than hardcoded. Other architectures hard-fail (detect_arch)
    rather than silently using the wrong regex.

Usage: diff_linker.py BASE PATCH [--list] [--optimistic] [--emit-closure]
                      [--base-debug B.debug --patch-debug P.debug]
                      [--base-src-root DIR --patch-src-root DIR]
  --optimistic: drop ambiguous-changed seeds. This is a LOWER BOUND for
    measurement only — NOT usable to generate a real patch (it can omit genuinely
    changed colliding instances).
"""
import subprocess, sys, re, bisect

# Architecture-specific disassembly conventions (REVIEW Tier A2 fix): x86-64's
# `call`/%r15-pool/int3-padding assumptions do NOT hold on arm64 — direct calls
# are `bl`, the object-pool register is x27 (confirmed empirically: same role
# as x86's %r15 — `ldr d1,[x27,#22456]` loads a pooled double constant, same
# pattern as x86 `movsd 0xNN(%r15)`), and pool offsets are decimal (`#NNNN`)
# not hex. Verified against real Android arm64 gen_snapshot output
# (spikes/gate2_linker/ARM64_PORT_NOTES.md) — not guessed.
ARCH_CONFIG = {
    'x64': {
        'call_re': re.compile(r'call[a-z]*\s+([0-9a-f]+) <(.+)>'),
        'pool_re': re.compile(r'0x[0-9a-f]+\(%r15\)'),
        'pool_sub': 'POOL(%r15)',
        'pad_prefixes': ('int3', 'nop'),
        'objdump': 'objdump',
    },
    'arm64': {
        'call_re': re.compile(r'\bbl\s+([0-9a-f]+) <(.+)>'),
        'pool_re': re.compile(r'\[x27, #\d+\]'),
        'pool_sub': '[POOL]',
        # udf/.inst are arm64's filler-in-disassembly forms (no int3 concept).
        'pad_prefixes': ('udf', '.inst', 'andeq'),
        # The native (x86-64 host) `objdump` can't disassemble AArch64 code
        # ("can't disassemble for architecture UNKNOWN") — needs the cross
        # binutils target explicitly (e.g. `apt-get install
        # binutils-aarch64-linux-gnu`). readelf (DWARF-only, format not
        # instruction-set-specific) works fine with the native binary either way.
        'objdump': 'aarch64-linux-gnu-objdump',
    },
}

# Detect the ELF architecture via `readelf -h` (Machine field), NOT by trusting
# a flag — mirrors the "never silent" principle (REVIEW R8): an unrecognized
# or mismatched arch must hard-fail, not silently fall back to wrong regexes.
def detect_arch(path):
    out = subprocess.check_output(['readelf', '-h', path]).decode(errors='replace')
    m = re.search(r'Machine:\s*(.+)', out)
    machine = m.group(1).strip() if m else ''
    if 'X86-64' in machine:
        return 'x64'
    if 'AArch64' in machine:
        return 'arm64'
    _die(f"unrecognized ELF machine type '{machine}' in {path} — "
         f"only x86-64 and AArch64 are supported; refusing to guess.")

# Build {code address -> canonical key} + {code address -> (low_pc, high_pc)}
# from a --save-debugging-info DWARF ELF (P0 finding, see
# probe_canonical_name/NOTES.md). canonical key = source-file URI (~= library) +
# DW_AT_name (Class.method). Returns ({}, {}) if no debug file (caller falls
# back to bare names).
#
# 从 --save-debugging-info 的 DWARF 建 {代码地址 -> canonical key} + {地址 -> 区间}(P0)。
# 无调试文件返回空。
def dwarf_canonical_map(debug_path, strip_prefix=None):
    if not debug_path:
        return {}, {}
    info = subprocess.check_output(['readelf', '--debug-dump=info', debug_path]).decode(errors='replace')
    raw = subprocess.check_output(['readelf', '--debug-dump=rawline', debug_path]).decode(errors='replace')
    files = {}
    for m in re.finditer(r'^\s*(\d+)\t\d+\t\d+\t\d+\t(.+)$', raw, re.M):
        files[int(m.group(1))] = m.group(2).strip()
    die_re = re.compile(r'^\s*<\d+><([0-9a-f]+)>:.*\((DW_TAG_\w+)\)', re.M)
    starts = [(m.start(), m.group(1), m.group(2)) for m in die_re.finditer(info)]
    spec, addr_key, addr_range = {}, {}, {}
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
        # DW_AT_high_pc is an absolute address in this GNU readelf rendering
        # (verified against real output — not a DW_FORM_data* size offset).
        hi = at('high_pc')
        if hi is not None:
            him = re.search(r'0x([0-9a-f]+)', hi)
            if him:
                addr_range[addr] = int(him.group(1), 16)
    return addr_key, addr_range

# Parse a snapshot into {key: [block,...]}. With addr_map (from DWARF), key is the
# canonical key; else the bare ELF symbol name. Each block is a list of
# (raw_bytes, normalized_mnemonic_placeholder, resolved_call_target). Returns also
# a total instruction count so callers can hard-fail on a non-GNU/empty parse.
def parse_snapshot(path, addr_map=None, addr_range=None, arch='x64'):
    addr_map = addr_map or {}
    addr_range = addr_range or {}
    call_re = ARCH_CONFIG[arch]['call_re']
    objdump_bin = ARCH_CONFIG[arch]['objdump']
    sorted_addrs = sorted(addr_map)  # for secondary-entry (<sym+0xNN>) resolution
    # Resolve a call-target address to a canonical key: exact hit, else — ONLY if
    # it falls STRICTLY WITHIN [low_pc, high_pc) of some function (a genuine
    # secondary/unchecked entry point of THAT function, S4 fix) — that function's
    # key. A target with no high_pc, or that falls in unmapped space (e.g. a call
    # into a VM runtime stub with no DWARF subprogram) must NOT be attributed to
    # "whatever DWARF function happens to precede it in address order": an
    # earlier, unbounded version of this fix did that and produced a real
    # false-positive cascade (see p3c_cid_dispatch probe) — stub layout shifts
    # with any unrelated code-size change, flipping the mis-attribution base<->
    # patch and making unrelated unchanged functions look byte-changed. Returns
    # None (fall back to bare name) when out of range or no high_pc is known.
    def resolve(taddr):
        if taddr in addr_map:
            return addr_map[taddr]
        if not sorted_addrs:
            return None
        i = bisect.bisect_right(sorted_addrs, taddr) - 1
        if i < 0:
            return None
        lo = sorted_addrs[i]
        hi = addr_range.get(lo)
        if hi is not None and lo <= taddr < hi:
            return addr_map[lo]
        return None

    out = subprocess.check_output([objdump_bin, '-d', path]).decode(errors='replace')
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
        cm = call_re.search(mnem)
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
# wildcard object-pool slot. Object FIELD offsets are KEPT (V9). Per-arch pool
# syntax from ARCH_CONFIG (x86: `0xNN(%r15)` hex; arm64: `[x27, #NN]` decimal —
# confirmed empirically, see ARCH_CONFIG comment).
def normalize(mnem, arch='x64'):
    mnem = re.sub(r'\b[0-9a-f]+ (<[^>]+>)', r'\1', mnem)  # drop abs call/jmp target addr
    cfg = ARCH_CONFIG[arch]
    mnem = cfg['pool_re'].sub(cfg['pool_sub'], mnem)
    return mnem

# Condition-1 signature of one block. S2 fix: fold the RESOLVED call target into
# the signature so retargeting a call to a different same-named function (which
# leaves the instruction text identical after normalize drops the address) is
# caught. Per-arch inter-function padding mnemonics are filtered (ARCH_CONFIG).
def sig(block, arch='x64'):
    pad = ARCH_CONFIG[arch]['pad_prefixes']
    parts = []
    for _, m, t in block:
        if m.startswith(pad):
            continue
        parts.append(normalize(m, arch) + (f' ->{t}' if t else ''))
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

    # Arch is DETECTED (readelf -h), not trusted from a flag (REVIEW Tier A2 /
    # R8 never-silent). base/patch must be the SAME arch — comparing across
    # architectures is meaningless and each snapshot's own disassembly rules
    # must match its own machine type.
    base_arch, patch_arch = detect_arch(base_path), detect_arch(patch_path)
    if base_arch != patch_arch:
        _die(f'base is {base_arch}, patch is {patch_arch} — must be the same architecture.')
    arch = base_arch
    print(f'architecture                  : {arch}')

    base_map, base_range = dwarf_canonical_map(base_dbg, base_root)
    patch_map, patch_range = dwarf_canonical_map(patch_dbg, patch_root)
    if base_map or patch_map:
        print(f'alignment                     : CanonicalName (DWARF: '
              f'{len(base_map)} base / {len(patch_map)} patch code addrs mapped)')
    else:
        print('alignment                     : bare ELF symbol name (no --*-debug)')

    base, base_n = parse_snapshot(base_path, base_map, base_range, arch)
    patch, patch_n = parse_snapshot(patch_path, patch_map, patch_range, arch)

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
        return sorted(sig(b, arch) for b in blocks)
    ambiguous = {n for n in common if len(base[n]) > 1 or len(patch[n]) > 1}
    ambiguous_changed = {n for n in ambiguous if multiset(base[n]) != multiset(patch[n])}
    ambiguous_cleared = ambiguous - ambiguous_changed
    aligned = common - ambiguous

    byte_changed = {n for n in aligned if sig(base[n][0], arch) != sig(patch[n][0], arch)}

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
