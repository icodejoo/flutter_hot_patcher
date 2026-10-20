#!/usr/bin/env python3
"""Per-section byte comparison of Dart AOT snapshots (ELF64 / Mach-O 64).

Pure-python, read-only. Used to decide whether an option's output difference
between the two toolchains is the baseline snapshot difference carried along,
or a new divergence the option introduces.
"""
import struct
import sys


def elf_sections(data):
    if data[:4] != b'\x7fELF':
        return None
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3a)
    raw = []
    for i in range(shnum):
        off = shoff + i * shentsize
        name, typ, flags, addr, offset, size = struct.unpack_from('<IIQQQQ', data, off)
        raw.append((name, typ, offset, size))
    stroff, strsize = raw[shstrndx][2], raw[shstrndx][3]
    names = data[stroff:stroff + strsize]
    out = {}
    for name, typ, offset, size in raw:
        n = names[name:names.index(b'\0', name)].decode()
        if typ == 8:  # SHT_NOBITS
            out[n or '<null>'] = b''
        else:
            out[n or '<null>'] = data[offset:offset + size]
    return out


def macho_sections(data):
    magic, = struct.unpack_from('<I', data, 0)
    if magic != 0xfeedfacf:
        return None
    ncmds, = struct.unpack_from('<I', data, 16)
    off, out = 32, {}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            nsects, = struct.unpack_from('<I', data, off + 64)
            s = off + 72
            for _ in range(nsects):
                sect = data[s:s + 16].rstrip(b'\0').decode()
                seg = data[s + 16:s + 32].rstrip(b'\0').decode()
                _, ssize, soff = struct.unpack_from('<QQI', data, s + 32)
                flags, = struct.unpack_from('<I', data, s + 64)
                zerofill = (flags & 0xff) in (1, 0x0c, 0x12)
                out[f'{seg},{sect}'] = b'' if zerofill else data[soff:soff + ssize]
                s += 80
        elif cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', data, off + 8)
            out['<symtab>'] = data[symoff:symoff + nsyms * 16]
            out['<strtab>'] = data[stroff:stroff + strsize]
        elif cmd == 0x1b:  # LC_UUID
            out['<uuid>'] = data[off + 8:off + 24]
        off += size
    return out


def sections(data):
    return elf_sections(data) or macho_sections(data)


def diff_bytes(a, b):
    n = min(len(a), len(b))
    return sum(1 for i in range(n) if a[i] != b[i]) + abs(len(a) - len(b))


def compare(a, b):
    sa, sb = sections(a), sections(b)
    rows = {}
    for name in list(dict.fromkeys(list(sa) + list(sb))):
        x, y = sa.get(name), sb.get(name)
        if x is None or y is None:
            rows[name] = {'only': 'a' if y is None else 'b'}
        else:
            rows[name] = {'size_a': len(x), 'size_b': len(y), 'diff': diff_bytes(x, y)}
    return rows


if __name__ == '__main__':
    a, b = (open(p, 'rb').read() for p in sys.argv[1:3])
    for k, v in compare(a, b).items():
        print(k, v)
    print('total', diff_bytes(a, b))
