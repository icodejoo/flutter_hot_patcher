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

SYMBOL ALIGNMENT CAVEAT (probe finding): AOT ELF symbol names are NOT unique
— multiple libraries/classes share names (there are 4 `main`s; countless
`toString`/`==`/`get:length`). Aligning base<->patch by bare symbol name is
therefore unsound. The production linker must align by Kernel `CanonicalName`
(SPEC §4.1). This spike tool detects name collisions and, per conservative-
first policy, forces every colliding name to reinterpret (cannot prove it
unchanged), and reports how large that ambiguous set is — a direct measure of
why CanonicalName alignment is required.

Spike tool: x86-64, objdump-based. Tracks only direct calls resolving to a
named symbol; indirect calls (`call *off(%r14)` — VM runtime stubs) are
ignored (not patch-replaceable Dart functions).

Usage: diff_linker.py BASE.snapshot PATCH.snapshot [--list] [--optimistic]
  --optimistic: treat name-colliding functions as if they could be aligned by
    CanonicalName and were unchanged (do NOT seed them into the closure). Lets
    us see the true closure size an ideal aligner would produce, vs the
    conservative (bare-name) result. The gap is the cost of imprecise alignment.
"""
import subprocess, sys, re

# Parse a snapshot into {name: [block, ...]} where each block is one function
# body (a name may map to several blocks when the symbol name collides). Each
# block is a list of (raw_bytes, mnemonic, direct_call_target), trimmed at the
# first `ret`.
#
# 把快照解析成 {名字: [函数块, ...]}；同名符号会有多个块（撞名）。每个块是
# (原始字节, 助记符, 直接调用目标) 列表，在首个 ret 处截断。
# Build {code address -> canonical key} from a --save-debugging-info DWARF ELF
# (P0 finding, see probe_canonical_name/NOTES.md). canonical key = source-file
# URI (~= library) + DW_AT_name (Class.method), which disambiguates the bare-name
# collisions (4 `main`s, countless toString/==) the ELF symbol table cannot.
# Concrete subprograms carry low_pc + abstract_origin -> spec DIE with
# name/decl_file. Returns {} if no debug file (caller falls back to bare names).
#
# 从 --save-debugging-info 的 DWARF 建 {代码地址 -> canonical key}(P0 发现)。
# key=源文件URI+成员名,消掉 ELF 符号表消不了的裸名撞名。无调试文件则返回 {} 回退裸名。
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
            r = re.search(r'0x?([0-9a-f]+)', ao)
            ref = r.group(1) if r else None
        nm, df = spec.get(ref, (name, at('decl_file')))
        if nm is None:
            continue
        fidx = int(df) if df and df.isdigit() else None
        fpath = files.get(fidx, '?')
        # Strip the build-specific source root so base/patch keys match: the
        # same app file lives under different tmp roots in the two builds, but
        # its app-relative path (and dart:/package: URIs) must be identical.
        if strip_prefix:
            fpath = fpath.replace('file://' + strip_prefix, '').replace(strip_prefix, '')
            fpath = fpath.lstrip('/')
        addr = int(re.search(r'0x([0-9a-f]+)', lo).group(1), 16)
        addr_key[addr] = f'{fpath}::{nm}'
    return addr_key

# Parse a snapshot into {key: [block,...]}. With addr_map (from DWARF), key is
# the canonical key; else the bare ELF symbol name. Each block records its
# instructions; call targets are resolved to the target's canonical key via
# addr_map (objdump prints the target address), falling back to the bare name.
def parse_snapshot(path, addr_map=None):
    addr_map = addr_map or {}
    out = subprocess.check_output(['objdump', '-d', path]).decode(errors='replace')
    funcs = {}
    cur_block = None
    ended = False
    for line in out.splitlines():
        h = re.match(r'^([0-9a-f]+) <(.+)>:$', line)
        if h:
            addr = int(h.group(1), 16)
            key = addr_map.get(addr, h.group(2))  # canonical key or bare name
            cur_block = []
            funcs.setdefault(key, []).append(cur_block)
            ended = False
            continue
        m = re.match(r'\s+[0-9a-f]+:\t([0-9a-f ]+?)\t(.*)', line)
        if not m or cur_block is None or ended:
            continue
        raw, mnem = m.group(1).strip(), m.group(2).strip()
        if not raw:
            continue
        cm = re.search(r'call[a-z]*\s+([0-9a-f]+) <([^>+]+)', mnem)
        target = None
        if cm:
            taddr = int(cm.group(1), 16)
            target = addr_map.get(taddr, cm.group(2))  # canonical key or bare name
        cur_block.append((raw, mnem, target))
        if mnem.startswith('ret'):
            ended = True
    return funcs

# Normalize one instruction's disassembly text to strip relocation/drift noise
# so condition 1 compares LOGIC, not layout (probe V9 finding: raw bytes are
# dominated by pool-slot drift + code-segment shift, not real changes):
#   - `call 14d318 <stub AllocateArray>` -> `call <stub AllocateArray>`
#     (drop the absolute target address; the symbol is what matters, and
#      intra-function targets keep their `<name+0xNN>` relative offset)
#   - `mov 0x6dc7(%r15),%r11` -> `mov POOL(%r15),%r11`
#     (r15 is the object-pool register; its slot offset drifts when the patch
#      adds pool constants — wildcard it)
# Object FIELD offsets (`0xf(%rdi)` etc., non-r15/r14) are intentionally KEPT,
# because a field-layout change shifting them is exactly the real difference V9
# must catch.
#
# 归一化一条指令的反汇编文本，剥掉重定位/漂移噪音，让条件 1 比"逻辑"而非"布局"
# （V9 发现：原始字节被对象池 slot 漂移 + 代码段平移主导，不是真实变化）。
# 对象字段偏移（非 r15/r14）刻意保留——字段布局变更导致它变，正是 V9 要抓的真差异。
def normalize(mnem):
    mnem = re.sub(r'\b[0-9a-f]+ (<[^>]+>)', r'\1', mnem)     # drop abs call/jmp target addr
    mnem = re.sub(r'0x[0-9a-f]+\(%r15\)', 'POOL(%r15)', mnem)  # wildcard pool slot
    return mnem

# Normalized-instruction signature of one block (condition-1 signature).
# int3 padding between functions is skipped: stubs that end in a jump (no ret)
# aren't trimmed by stop-at-ret, so their trailing inter-function 0xcc padding
# leaks in and its count varies with layout — pure noise.
def sig(block):
    return ' | '.join(normalize(m) for _, m, _ in block if not m.startswith('int3'))

# Direct-call target names appearing in any block of a function.
def all_targets(blocks):
    return {t for b in blocks for _, _, t in b if t}

def _opt(flag):
    # Read value of `--flag VALUE` from argv, or None.
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None

def main():
    base_path, patch_path = sys.argv[1], sys.argv[2]
    list_all = '--list' in sys.argv[3:]
    optimistic = '--optimistic' in sys.argv[3:]
    # Optional DWARF debug ELFs (from gen_snapshot --save-debugging-info): enable
    # CanonicalName alignment. Without them, alignment falls back to bare names.
    base_dbg, patch_dbg = _opt('--base-debug'), _opt('--patch-debug')
    base_root, patch_root = _opt('--base-src-root'), _opt('--patch-src-root')
    base_map = dwarf_canonical_map(base_dbg, base_root)
    patch_map = dwarf_canonical_map(patch_dbg, patch_root)
    if base_map or patch_map:
        print(f'alignment                     : CanonicalName (DWARF: '
              f'{len(base_map)} base / {len(patch_map)} patch code addrs mapped)')
    else:
        print('alignment                     : bare ELF symbol name (no --*-debug)')
    base = parse_snapshot(base_path, base_map)
    patch = parse_snapshot(patch_path, patch_map)

    added = set(patch) - set(base)
    removed = set(base) - set(patch)
    common = set(base) & set(patch)

    # Keys that collide (appear >1x) on either side can't be aligned 1:1. But an
    # ambiguous key whose FULL multiset of normalized sigs is identical base<->
    # patch provably changed nothing there -> equivalent (sound, not a guess;
    # clears unchanged SDK generic-instantiation / closure collisions). Only
    # ambiguous keys with a differing multiset are seeded conservatively (can't
    # tell which colliding instance changed).
    def multiset(blocks):
        return sorted(sig(b) for b in blocks)
    ambiguous = {n for n in common if len(base[n]) > 1 or len(patch[n]) > 1}
    ambiguous_changed = {n for n in ambiguous if multiset(base[n]) != multiset(patch[n])}
    aligned = common - ambiguous  # exactly one block each side -> safe to diff

    byte_changed = {n for n in aligned if sig(base[n][0]) != sig(patch[n][0])}

    # Seed: byte-changed (cond 1) + added (new) + ambiguous-and-changed
    # (conservative; --optimistic assumes an ideal aligner resolves even those).
    seed_ambiguous = set() if optimistic else set(ambiguous_changed)
    must_interp = set(byte_changed) | set(added) | seed_ambiguous

    # Fixpoint (cond 2): any patch function directly calling a must_interp
    # member must itself reinterpret.
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
          f'{"OPTIMISTIC (ideal aligner)" if optimistic else "CONSERVATIVE"}')
    print(f'total function names in patch : {total}')
    print(f'added (new, interpret)        : {len(added)}')
    print(f'removed (gone from base)      : {len(removed)}')
    print(f'ambiguous (colliding key)     : {len(ambiguous)}'
          f'   ({100.0*len(ambiguous)/max(1,total):.1f}%); of them changed (seeded): '
          f'{len(ambiguous_changed)}, unchanged (multiset-equal → equivalent): '
          f'{len(ambiguous)-len(ambiguous_changed)}')
    print(f'byte-changed (cond 1)         : {len(byte_changed)}')
    print(f'must reinterpret (closure)    : {len(must_interp)}'
          f'   ({100.0*len(must_interp)/max(1,total):.1f}% of program)')
    print(f'  of which propagated (cond 2): '
          f'{len(must_interp) - len(byte_changed) - len(added) - len(seed_ambiguous)}')
    print(f'equivalent (baseline)         : {len(equivalent)}')

    if list_all:
        propagated = must_interp - byte_changed - added - ambiguous
        print('\n--- byte-changed (condition 1) ---')
        for n in sorted(byte_changed):
            print(f'  {n}')
        print('--- propagated via call graph (condition 2) ---')
        for n in sorted(propagated):
            hit = sorted(all_targets(patch[n]) & must_interp)
            print(f'  {n}   (calls: {", ".join(hit)})')

if __name__ == '__main__':
    main()
