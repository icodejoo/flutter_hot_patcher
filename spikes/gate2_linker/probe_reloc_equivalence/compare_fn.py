#!/usr/bin/env python3
"""Compare the machine code of same-named functions across two AOT snapshots.

For each function name, disassemble it in both snapshots (located via nm),
then report naive byte equality and, if different, the first differing
instruction — to reveal WHY (relocation vs genuine logic change). Core question
for whether byte-level equivalence testing is valid at all.
"""
import subprocess, sys, re

def fn_addr(snap, name):
    out = subprocess.check_output(['nm', snap]).decode(errors='replace')
    for line in out.splitlines():
        p = line.split()
        if len(p) == 3 and p[2] == name and p[1] in ('t', 'T'):
            return int(p[0], 16)
    return None

# length must be large enough to cover the whole function up to its first ret;
# 0x60 was too small for long functions (missed back-half differences).
def disasm(snap, addr, length=0x400):
    out = subprocess.check_output([
        'objdump', '-d',
        '--start-address=0x%x' % addr,
        '--stop-address=0x%x' % (addr + length),
        snap]).decode(errors='replace')
    insns = []
    for line in out.splitlines():
        m = re.match(r'\s+[0-9a-f]+:\t([0-9a-f ]+?)\t(.*)', line)
        if m and m.group(1).strip():
            insns.append((m.group(1).strip(), m.group(2).strip()))
    return insns

def stop_at_ret(insns):
    out = []
    for raw, mnem in insns:
        out.append((raw, mnem))
        if mnem.startswith('ret'):
            break
    return out

def main():
    base, other = sys.argv[1], sys.argv[2]
    for name in sys.argv[3:]:
        a1, a2 = fn_addr(base, name), fn_addr(other, name)
        if a1 is None or a2 is None:
            print(f'{name}: NOT FOUND (base={a1}, other={a2})')
            continue
        i1, i2 = stop_at_ret(disasm(base, a1)), stop_at_ret(disasm(other, a2))
        b1 = ' '.join(r for r, _ in i1)
        b2 = ' '.join(r for r, _ in i2)
        print(f'=== {name} ===  base@0x{a1:x} other@0x{a2:x}  '
              f'naive_bytes_equal={b1 == b2}')
        if b1 != b2:
            for k in range(min(len(i1), len(i2))):
                if i1[k] != i2[k]:
                    print(f'  first diff @ insn #{k}:')
                    print(f'    base : {i1[k][0]:24s} {i1[k][1]}')
                    print(f'    other: {i2[k][0]:24s} {i2[k][1]}')
                    break
            else:
                print(f'  differ only in length: {len(i1)} vs {len(i2)} insns')

if __name__ == '__main__':
    main()
