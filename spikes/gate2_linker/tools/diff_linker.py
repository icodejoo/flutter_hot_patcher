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
def parse_snapshot(path):
    out = subprocess.check_output(['objdump', '-d', path]).decode(errors='replace')
    funcs = {}
    cur_name = None
    cur_block = None
    ended = False
    for line in out.splitlines():
        h = re.match(r'^[0-9a-f]+ <(.+)>:$', line)
        if h:
            cur_name = h.group(1)
            cur_block = []
            funcs.setdefault(cur_name, []).append(cur_block)
            ended = False
            continue
        m = re.match(r'\s+[0-9a-f]+:\t([0-9a-f ]+?)\t(.*)', line)
        if not m or cur_block is None or ended:
            continue
        raw, mnem = m.group(1).strip(), m.group(2).strip()
        if not raw:
            continue
        cm = re.search(r'call[a-z]*\s+[0-9a-f]+ <([^>+]+)', mnem)
        cur_block.append((raw, mnem, cm.group(1) if cm else None))
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

def main():
    base_path, patch_path = sys.argv[1], sys.argv[2]
    list_all = '--list' in sys.argv[3:]
    optimistic = '--optimistic' in sys.argv[3:]
    base, patch = parse_snapshot(base_path), parse_snapshot(patch_path)

    added = set(patch) - set(base)
    removed = set(base) - set(patch)
    common = set(base) & set(patch)

    # Names that collide (appear >1x) on either side cannot be aligned by name.
    ambiguous = {n for n in common if len(base[n]) > 1 or len(patch[n]) > 1}
    aligned = common - ambiguous  # exactly one block each side -> safe to diff

    byte_changed = {n for n in aligned if sig(base[n][0]) != sig(patch[n][0])}

    # Seed: byte-changed (cond 1) + added (new) + ambiguous (conservative,
    # unless --optimistic assumes an ideal CanonicalName aligner would resolve
    # and clear them).
    seed_ambiguous = set() if optimistic else set(ambiguous)
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
          f'{"OPTIMISTIC (ideal aligner)" if optimistic else "CONSERVATIVE (bare-name)"}')
    print(f'total function names in patch : {total}')
    print(f'added (new, interpret)        : {len(added)}')
    print(f'removed (gone from base)      : {len(removed)}')
    print(f'ambiguous (name collision)    : {len(ambiguous)}'
          f'   ({100.0*len(ambiguous)/max(1,total):.1f}% — needs CanonicalName)')
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
