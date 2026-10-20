#!/usr/bin/env python3
"""Symbol-level comparison of two Dart AOT ELF snapshots (read-only).

Pairs .symtab entries by name (in order of appearance, so repeated names pair
up positionally) and reports, per symbol, size and byte equality of its bytes.
"""
import collections
import struct
import sys


def symbols(data):
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3a)
    hdrs = [struct.unpack_from('<IIQQQQII', data, shoff + i * shentsize) for i in range(shnum)]
    sym = next(h for h in hdrs if h[1] == 2)  # SHT_SYMTAB
    strtab = hdrs[sym[6]]
    strs = data[strtab[4]:strtab[4] + strtab[5]]
    out = []
    for off in range(sym[4], sym[4] + sym[5], 24):
        name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', data, off)
        if shndx == 0 or size == 0:
            continue
        sec = hdrs[shndx]
        file_off = sec[4] + (value - sec[3])
        n = strs[name:strs.index(b'\0', name)].decode(errors='replace')
        out.append({'name': n, 'shndx': shndx, 'value': value, 'size': size,
                    'bytes': data[file_off:file_off + size] if sec[1] != 8 else b''})
    return out


def pair(a, b):
    qa, qb = collections.defaultdict(list), collections.defaultdict(list)
    for s in a:
        qa[s['name']].append(s)
    for s in b:
        qb[s['name']].append(s)
    pairs, only_a, only_b = [], [], []
    for name in dict.fromkeys([s['name'] for s in a] + [s['name'] for s in b]):
        xa, xb = qa.get(name, []), qb.get(name, [])
        for i in range(max(len(xa), len(xb))):
            if i < len(xa) and i < len(xb):
                pairs.append((xa[i], xb[i]))
            elif i < len(xa):
                only_a.append(xa[i])
            else:
                only_b.append(xb[i])
    return pairs, only_a, only_b


if __name__ == '__main__':
    a, b = (symbols(open(p, 'rb').read()) for p in sys.argv[1:3])
    pairs, oa, ob = pair(a, b)
    same = sum(1 for x, y in pairs if x['bytes'] == y['bytes'])
    sized = [(x, y) for x, y in pairs if x['size'] != y['size']]
    print(f'symbols {len(a)}/{len(b)} paired {len(pairs)} identical {same} '
          f'same-size-differ {len(pairs) - same - len(sized)} size-differ {len(sized)} '
          f'only_a {len(oa)} only_b {len(ob)}')
    for x, y in sized:
        print(f"  size {x['size']:6d} vs {y['size']:6d} ({x['size'] - y['size']:+d})  {x['name']}")
