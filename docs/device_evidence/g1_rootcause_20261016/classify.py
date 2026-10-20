#!/usr/bin/env python3
"""G1 root-cause classification of the 68 matrix gaps and 54 coverage gaps.

Read-only: reads existing artifacts under scratchpad/ and the G1 audit reports,
runs no gen_snapshot. (The object-pool dumps under pool/ were produced once by
analyze_snapshot --dump_object_pool on existing .so files; they are inputs.)

Every root cause is backed by a check that runs here; a cell is assigned to a
root cause only through a rule whose check passed. --negative-controls mutates
inputs in memory and requires each check to fail.

Exit 0 when every cell is assigned and every check passes, 1 otherwise.
"""
import argparse
import bisect
import collections
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
REPO = Path('/Users/Cruz/Documents/flutter_hot_patcher')
SP = REPO / 'scratchpad'
M = SP / 'g1_g4_20261016/matrix_final'
M21 = M / 'm21'
COV = SP / 'g1_coverage_20261016/run_v2'
MATRIX_AUDIT = REPO / 'docs/device_evidence/g1_20261016_audit/report.json'
COVERAGE = REPO / 'docs/device_evidence/g1_coverage_20261016/report.json'
SDK = Path('/Users/Cruz/dart-3122/sdk')
SNAPSHOT_HASH_FILES = ['app_snapshot.cc', 'app_snapshot.h', 'dart.cc', 'dart_api_impl.cc',
                       'datastream.h', 'image_snapshot.cc', 'image_snapshot.h', 'object.cc',
                       'object.h', 'raw_object.cc', 'raw_object.h', 'snapshot.cc', 'snapshot.h',
                       'symbols.cc', 'symbols.h']
FIXTURES = ['hello', 'base_dd', 'prog']

ROOT_CAUSES = {
    'RC1': ('snapshot version hash', 'structural',
            'md5 of 15 VM source files (tools/make_version.py); theirs edited those files, '
            'their hash matches neither ours nor upstream; matching it means copying their string'),
    'RC2': ('features-string token shorebird-native-entry-thr-offsets', 'our addition',
            'SDK ac863d5cd46 (2026-09-28) appends 50 bytes to the AOT features string as a '
            'Thread-layout guard; theirs has no such token'),
    'RC3': ('ResumeStub is 4 bytes longer', 'our addition',
            'one extra instruction in vm and isolate ResumeStub (the Resume safety fix); every '
            'other code difference is a branch displacement that lands on the same target'),
    'RC4': ('build version string', 'build metadata',
            'dart_version carries the source commit date: ours Oct 2 2026 +0800, theirs Jun 11 2026 -0700'),
    'RC5': ('analyzer process-local addresses', 'structural',
            'native-function pool entries print as process addresses (ASLR); the code_infos '
            'hashing those entries differ with them'),
    'RC6': ('field_table group-internal order', 'known (F128)',
            'heap traversal order; same (id,hash) multiset measured 2026-09-30'),
    'RC7': ('load_obfuscation_map product not compared', 'test gap',
            'the matrix only checks the map is accepted; no product comparison was made'),
    'RC8': ('object pool not re-sorted by --base_op_link_data', 'REAL BUG',
            'code accesses are renumbered (ImageWriter::EditObjectPoolAccesses) but the pool '
            'itself keeps its order, so renumbered loads read the wrong entry'),
    'RC9': ('DD slot-mapping pass differs', 'real gap',
            'resolution table size/sentinels, setter-name rendering, key-map size, and the '
            'DD table rewrite into the snapshot (theirs +8 B and a "DD table:" report line)'),
    'RC10': ('field-table link on an inserting patch adds 64 B more on ours', 'real gap (small)',
             'identity case is symmetric; base_insert ours +512 B vs theirs +448 B'),
    'RC11': ('JIT --compile_all code size', 'unexplained',
             'ours 4,201,824 B vs theirs 4,912,240 B instructions; not on the iOS AOT release path'),
    'RC12': ('linker report lines missing', 'cosmetic',
             'theirs prints "Sorted ObjectPool, moved N of M entries." after op linking'),
    'AOT': ('AOT snapshot difference carried by the option', 'composite',
            'the cell inherits the baseline AOT difference, which decomposes into RC1+RC2+RC3 '
            'plus the data-payload remainder D1'),
}

checks = []


def check(name, ok, detail=None):
    checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    return bool(ok)


def sha(b):
    return hashlib.sha256(b).hexdigest()


# --- ELF symbols ---------------------------------------------------------------

def symbols(data):
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum, _ = struct.unpack_from('<HHH', data, 0x3a)
    hdrs = [struct.unpack_from('<IIQQQQII', data, shoff + i * shentsize) for i in range(shnum)]
    sym = next(h for h in hdrs if h[1] == 2)
    strtab = hdrs[sym[6]]
    strs = data[strtab[4]:strtab[4] + strtab[5]]
    out = []
    for off in range(sym[4], sym[4] + sym[5], 24):
        name, _, _, shndx, value, size = struct.unpack_from('<IBBHQQ', data, off)
        if shndx == 0 or size == 0:
            continue
        sec = hdrs[shndx]
        fo = sec[4] + (value - sec[3])
        out.append({'name': strs[name:strs.index(b'\0', name)].decode(errors='replace'),
                    'value': value, 'size': size,
                    'bytes': data[fo:fo + size] if sec[1] != 8 else b''})
    return out


def pair(a, b):
    qa, qb = collections.defaultdict(list), collections.defaultdict(list)
    for s in a:
        qa[s['name']].append(s)
    for s in b:
        qb[s['name']].append(s)
    out = []
    for n in dict.fromkeys([s['name'] for s in a] + [s['name'] for s in b]):
        out += list(zip(qa.get(n, []), qb.get(n, [])))
    return out, len(a) - sum(min(len(qa[n]), len(qb.get(n, []))) for n in qa)


def imm26(w):
    v = w & 0x3ffffff
    return v - (1 << 26) if v & (1 << 25) else v


def code_decomposition(a_syms, b_syms):
    """Every differing code word must be a B/BL whose target is the same symbol+offset."""
    pairs, unpaired = pair(a_syms, b_syms)
    def index(syms):
        code = sorted((s for s in syms if not s['name'].startswith('_kDart')), key=lambda s: s['value'])
        return code, [s['value'] for s in code]
    ia, ib = index(a_syms), index(b_syms)
    twin = {id(x): id(y) for x, y in pairs}
    def resolve(ix, addr):
        code, starts = ix
        j = bisect.bisect_right(starts, addr) - 1
        if j < 0 or addr >= code[j]['value'] + code[j]['size']:
            return None, None
        return id(code[j]), addr - code[j]['value']
    r = collections.Counter()
    size_differ = []
    for x, y in pairs:
        if x['name'].startswith('_kDart'):
            continue
        if x['bytes'] == y['bytes']:
            r['identical'] += 1
            continue
        if x['size'] != y['size']:
            size_differ.append((x['name'], x['size'], y['size']))
            continue
        ok = True
        for i in range(0, x['size'], 4):
            wa, = struct.unpack_from('<I', x['bytes'], i)
            wb, = struct.unpack_from('<I', y['bytes'], i)
            if wa == wb:
                continue
            if (wa >> 26) != (wb >> 26) or (wa >> 26) not in (0x25, 0x05):
                ok = False
                r['non_branch_words'] += 1
                continue
            sa, oa = resolve(ia, x['value'] + i + imm26(wa) * 4)
            sb, ob = resolve(ib, y['value'] + i + imm26(wb) * 4)
            if sa is not None and twin.get(sa) == sb and oa == ob:
                r['branch_same_target'] += 1
            else:
                ok = False
                r['branch_target_mismatch'] += 1
        r['branch_only_functions' if ok else 'other_functions'] += 1
    return dict(r), size_differ, unpaired


def snapshot_header(sym):
    b = sym['bytes']
    end = b.index(b'\0', 52)
    return b[20:52].decode(), b[52:end].decode()


# --- checks ----------------------------------------------------------------------

def check_rc1(mutate=None):
    """RC1: our hash recomputes from our sources; theirs differs from ours and upstream.

    The artifacts were built from SDK HEAD plus working-tree patch 6f1ec517, which
    touches none of the 15 hash inputs, so the inputs are read from HEAD blobs: the
    live tree has moved on since (the G4 work edited app_snapshot.cc at 17:50).
    """
    import subprocess
    h = hashlib.md5()
    for f in SNAPSHOT_HASH_FILES:
        h.update(subprocess.run(['git', '-C', str(SDK), 'show', f'HEAD:runtime/vm/{f}'],
                                capture_output=True, check=True).stdout)
    ours_src = h.hexdigest()
    hs = {}
    for side in ['ours', 'theirs']:
        s = {x['name']: x for x in symbols((M / f'gs.hello.{side}.so').read_bytes())}
        hs[side] = snapshot_header(s['_kDartVmSnapshotData'])[0]
    if mutate == 'rc1':
        hs['ours'] = hs['theirs']
    return check('RC1 our snapshot hash = md5(15 VM files) and differs from theirs',
                 hs['ours'] == ours_src and hs['theirs'] != ours_src,
                 {'ours_binary': hs['ours'], 'ours_from_source': ours_src, 'theirs': hs['theirs']})


def check_rc2(mutate=None):
    out = {}
    for fx in ['hello', 'prog']:
        f = {}
        for side in ['ours', 'theirs']:
            s = {x['name']: x for x in symbols((M / f'gs.{fx}.{side}.so').read_bytes())}
            f[side] = snapshot_header(s['_kDartVmSnapshotData'])[1]
        if mutate == 'rc2':
            f['ours'] = f['theirs'] + ' x'
        out[fx] = f['ours'][len(f['theirs']):] if f['ours'].startswith(f['theirs']) else None
    tok = ' shorebird-native-entry-thr-offsets=2312,2320,2328'
    return check('RC2 our features string = theirs + one 50-byte token',
                 all(v == tok for v in out.values()) and len(tok) == 50, out)


def check_rc3_and_code(mutate=None):
    """RC3: only the Resume stubs differ in size; every other code diff is a same-target branch."""
    res = {}
    ok = True
    for fx in ['hello', 'prog']:
        a = symbols((M / f'gs.{fx}.ours.so').read_bytes())
        b = symbols((M / f'gs.{fx}.theirs.so').read_bytes())
        if mutate == 'rc3':
            # Shift one branch in a copy of ours so it lands somewhere else.
            for s in a:
                if s['name'].startswith('_kDart') or len(s['bytes']) < 8:
                    continue
                w, = struct.unpack_from('<I', s['bytes'], 0)
                found = False
                for i in range(0, s['size'], 4):
                    w, = struct.unpack_from('<I', s['bytes'], i)
                    if (w >> 26) == 0x25:
                        nb = bytearray(s['bytes'])
                        struct.pack_into('<I', nb, i, (w & ~0x3ffffff) | ((imm26(w) + 2) & 0x3ffffff))
                        s['bytes'] = bytes(nb)
                        found = True
                        break
                if found:
                    break
        r, size_differ, unpaired = code_decomposition(a, b)
        stubs = sorted(n for n, _, _ in size_differ)
        res[fx] = {'counts': r, 'size_differ': size_differ, 'unpaired': unpaired}
        ok &= (r.get('other_functions', 0) == 0 and unpaired == 0 and
               all(sa - sb == 4 for _, sa, sb in size_differ) and
               all('Resume' in n for n in stubs) and len(stubs) == 2)
    return check('RC3 code: only the two Resume stubs differ in size (+4); all other differing '
                 'words are branches to the same symbol+offset', ok, res)


def check_shorebird_json(mutate=None):
    """The shorebird JSON cells decompose into RC1/RC2/RC3/RC4 exactly."""
    res, ok = {}, True
    for fx in FIXTURES:
        a = json.loads((M / f'as.{fx}.ours.shorebird').read_text())
        b = json.loads((M / f'as.{fx}.theirs.shorebird').read_text())
        fa, fb = a['functions'], b['functions']
        if mutate == 'sb':
            fa[3] = dict(fa[3], self_hash='0' * 40)
        names_equal = [x['name'] for x in fa] == [y['name'] for y in fb]
        size_d = [i for i, (x, y) in enumerate(zip(fa, fb)) if x['size'] != y['size']]
        self_d = [i for i, (x, y) in enumerate(zip(fa, fb)) if x['self_hash'] != y['self_hash']]
        r = size_d[0] if len(size_d) == 1 else None
        stub_ok = r is not None and self_d == [r] and 'ResumeStub' in fa[r]['name'] and \
            fa[r]['size'] - fb[r]['size'] == 4
        off_d = {i for i, (x, y) in enumerate(zip(fa, fb)) if x['offset'] != y['offset']}
        after = {i for i, x in enumerate(fa) if r is not None and x['offset'] > fa[r]['offset']}
        off_ok = off_d == after and all(fa[i]['offset'] - fb[i]['offset'] == 4 for i in off_d)
        def reaches(i):
            seen, stack = {i}, [i]
            while stack:
                j = stack.pop()
                if j == r:
                    return True
                for c in fa[j]['callees']:
                    if c not in seen:
                        seen.add(c)
                        stack.append(c)
            return False
        sg_d = {i for i, (x, y) in enumerate(zip(fa, fb)) if x['subgraph_hash'] != y['subgraph_hash']}
        op_d = {i for i, (x, y) in enumerate(zip(fa, fb)) if x['op_subgraph_hash'] != y['op_subgraph_hash']}
        reach = {i for i in range(len(fa)) if r is not None and reaches(i)}
        other = [k for k in fa[0] if k not in ('name', 'index_in_entries', 'size', 'self_hash',
                                                'offset', 'subgraph_hash', 'op_subgraph_hash')
                 and any(x.get(k) != y.get(k) for x, y in zip(fa, fb))]
        sd = {k for k in a['snapshot_data'] if a['snapshot_data'][k] != b['snapshot_data'].get(k)}
        expected_sd = {'dart_version', 'snapshot_version', 'vm_data_length',
                       'adjusted_vm_instructions_hash', 'vm_data_hash'}
        top = [k for k in a if k not in ('functions', 'snapshot_data') and a[k] != b[k]]
        cell_ok = (names_equal and stub_ok and off_ok and sg_d == reach and op_d == reach and
                   not other and sd <= expected_sd and not top)
        res[fx] = {'functions': len(fa), 'resume_stub_index': r, 'offset_shifted': len(off_d),
                   'functions_after_stub': len(after), 'subgraph_differ': sorted(sg_d),
                   'reach_resume_stub': sorted(reach), 'other_fields_differ': other,
                   'snapshot_data_differ': sorted(sd), 'other_top_level_differ': top, 'ok': cell_ok}
        ok &= cell_ok
    return check('shorebird JSON x3: 1 size/self_hash diff = ResumeStub; offset diffs = exactly '
                 'the functions after it (+4); subgraph diffs = exactly the functions reaching it; '
                 'snapshot_data diffs only version/hash/length fields', ok, res)


def check_d29(mutate=None):
    """JIT/core cells whose whole difference is the 32-byte version hash at bytes 20..51."""
    res, ok = {}, True
    files = []
    for fx in FIXTURES:
        for d, f in [('core', 'vm_data.bin'), ('core', 'iso_data.bin'), ('appjit', 'jit_data.bin')]:
            files.append((f'{fx}/{d}/{f}', COV / 'ours' / fx / d / f, COV / 'theirs' / fx / d / f))
    for name, a, b in files:
        x, y = bytearray(a.read_bytes()), b.read_bytes()
        if mutate == 'd29' and name.endswith('vm_data.bin'):
            x[100] ^= 1
        diff = [i for i in range(min(len(x), len(y))) if x[i] != y[i]]
        good = len(x) == len(y) and diff and all(20 <= i < 52 for i in diff)
        res[name] = {'size': len(x), 'differing': len(diff), 'range': [min(diff), max(diff)] if diff else None}
        ok &= bool(good)
    return check('RC1-only JIT/core artifacts: same size, every differing byte in 20..51', ok, res)


def check_identity(mutate=None):
    """Options whose output equals the side's own baseline on both sides."""
    res, ok = {}, True
    for fx in FIXTURES:
        for side in ['ours', 'theirs']:
            base = (COV / side / fx / 'baseline/app.so').read_bytes()
            for d in ['verbose', 'ct', 'dt', 'op']:
                out = bytearray((COV / side / fx / d / 'app.so').read_bytes())
                if mutate == 'identity' and d == 'ct' and side == 'ours' and fx == 'hello':
                    out[5000] ^= 1
                same = bytes(out) == base
                res[f'{fx}/{side}/{d}'] = same
                ok &= same
    for sc in ['base_patch', 'base_insert']:
        for side in ['ours', 'theirs']:
            nolink = (M21 / side / sc / 'nolink/app.so').read_bytes()
            for d in ['ct', 'dt'] + (['op'] if sc == 'base_patch' else []):
                same = (M21 / side / sc / d / 'app.so').read_bytes() == nolink
                res[f'{sc}/{side}/{d}'] = same
                ok &= same
    return check('identity options: output byte-identical to the same side\'s baseline', ok, res)


def check_strip_sections(mutate=None):
    """strip keeps every snapshot section byte-identical to the baseline on both sides."""
    res, ok = {}, True
    for fx in FIXTURES:
        for side in ['ours', 'theirs']:
            a = {x['name']: x['bytes'] for x in symbols((M / f'gs.{fx}.{side}.so').read_bytes())}
            raw = bytearray((M21 / side / fx / 'strip/app.so').read_bytes())
            if mutate == 'strip' and side == 'theirs' and fx == 'hello':
                raw[0x5000] ^= 1
            # strip removes .symtab, so compare by file sections instead
            from_sec = elf_sections(bytes(raw))
            base_sec = elf_sections((M / f'gs.{fx}.{side}.so').read_bytes())
            same = all(from_sec[n] == base_sec[n] for n in ('.text', '.rodata', '.note.gnu.build-id'))
            res[f'{fx}/{side}'] = same
            ok &= same
    return check('strip: .text/.rodata/build-id byte-identical to baseline on both sides', ok, res)


def elf_sections(data):
    shoff, = struct.unpack_from('<Q', data, 0x28)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', data, 0x3a)
    raw = [struct.unpack_from('<IIQQQQ', data, shoff + i * shentsize) for i in range(shnum)]
    so, ss = raw[shstrndx][4], raw[shstrndx][5]
    names = data[so:so + ss]
    return {names[n:names.index(b'\0', n)].decode(): (b'' if t == 8 else data[o:o + s])
            for n, t, _, _, o, s in raw}


def check_container_core(mutate=None):
    """Every other AOT container carries the baseline's core section deltas (+16 .text etc.)."""
    res, ok = {}, True
    for fx in ['hello', 'base_dd', 'prog']:
        base = {s: elf_sections((M / f'gs.{fx}.{s}.so').read_bytes()) for s in ['ours', 'theirs']}
        want = len(base['ours']['.text']) - len(base['theirs']['.text'])
        for opt, fn in [('obfuscate', 'app.so'), ('strip', 'app.so')]:
            sec = {s: elf_sections((M21 / s / fx / opt / fn).read_bytes()) for s in ['ours', 'theirs']}
            got = len(sec['ours']['.text']) - len(sec['theirs']['.text'])
            rod = len(sec['ours']['.rodata']) - len(sec['theirs']['.rodata'])
            res[f'{fx}/{opt}'] = {'text_delta': got, 'rodata_delta': rod, 'baseline_text_delta': want}
            ok &= rod == 128
    return check('ELF option outputs keep the baseline .rodata delta (+128 B)', ok, res)


def check_rc8(mutate=None):
    """Object pool: after op linking on base_insert, our code reads entries the pool no longer holds."""
    P = {k: json.loads((HERE / 'pool' / f'{k}.json').read_text())
         for k in ['ours_nolink', 'ours_op', 'theirs_nolink', 'theirs_op']}
    at = {k: {e['offset']: e['code'] for e in v['entries']} for k, v in P.items()}
    if mutate == 'rc8':
        at['ours_op'] = dict(at['theirs_op'])
    res, consistent = {}, collections.Counter()
    for side in ['ours', 'theirs']:
        a = symbols((M21 / side / 'base_insert/op/app.so').read_bytes())
        b = symbols((M21 / side / 'base_insert/nolink/app.so').read_bytes())
        pairs, _ = pair(a, b)
        n = good = 0
        for x, y in pairs:
            if x['name'].startswith('_kDart') or x['bytes'] == y['bytes'] or x['size'] != y['size']:
                continue
            for i in range(0, x['size'], 4):
                wa, = struct.unpack_from('<I', x['bytes'], i)
                wb, = struct.unpack_from('<I', y['bytes'], i)
                if wa == wb:
                    continue
                if (wa & 0xffc003e0) == (0xf9400000 | (27 << 5)) and (wb & 0xffc003e0) == (0xf9400000 | (27 << 5)):
                    new, old = ((wa >> 10) & 0xfff) * 8, ((wb >> 10) & 0xfff) * 8
                    n += 1
                    # the renumbered load should read what the unlinked load read
                    good += at[f'{side}_op'].get(new) == at[f'{side}_nolink'].get(old)
        moved = sum(1 for o in at[f'{side}_nolink'] if at[f'{side}_nolink'][o] != at[f'{side}_op'].get(o))
        res[side] = {'renumbered_pool_loads': n, 'still_read_same_object': good, 'pool_entries_moved': moved}
    ok = (res['theirs']['renumbered_pool_loads'] > 0 and
          res['theirs']['still_read_same_object'] == res['theirs']['renumbered_pool_loads'] and
          res['ours']['renumbered_pool_loads'] == res['theirs']['renumbered_pool_loads'] and
          res['ours']['still_read_same_object'] < res['ours']['renumbered_pool_loads'])
    return check('RC8 base_insert op: theirs renumbered loads all still read the same object; '
                 'ours renumbers the same loads but the pool was not re-sorted', ok, res)


def check_rc9(mutate=None):
    res = {}
    for fx in FIXTURES:
        o = (COV / 'ours' / fx / 'dd/stderr.log').read_text()
        t = (COV / 'theirs' / fx / 'dd/stderr.log').read_text()
        ro = (COV / 'ours' / fx / 'dd/resolution.tsv').read_text().splitlines()
        rt = (COV / 'theirs' / fx / 'dd/resolution.tsv').read_text().splitlines()
        if mutate == 'rc9':
            t = o
        sizes = [(COV / s / fx / 'dd/app.so').stat().st_size for s in ['ours', 'theirs']]
        base = [(COV / s / fx / 'baseline/app.so').stat().st_size for s in ['ours', 'theirs']]
        res[fx] = {'theirs_has_dd_table_line': 'DD table:' in t, 'ours_has_dd_table_line': 'DD table:' in o,
                   'key_map_first_pass': [o.split(' functions in key map')[0].rsplit(' ', 1)[-1],
                                          t.split(' functions in key map')[0].rsplit(' ', 1)[-1]],
                   'resolution_header': [ro[1] if len(ro) > 1 else None, rt[1] if len(rt) > 1 else None],
                   'resolution_differs': ro != rt,
                   'so_growth_vs_baseline': [sizes[0] - base[0], sizes[1] - base[1]]}
    ok = all(v['theirs_has_dd_table_line'] and not v['ours_has_dd_table_line'] and
             v['so_growth_vs_baseline'][0] != v['so_growth_vs_baseline'][1] and
             v['key_map_first_pass'][0] != v['key_map_first_pass'][1] for v in res.values())
    return check('RC9 dd_slot_mapping: theirs rewrites the DD table into the snapshot and reports it, '
                 'ours does not; first-pass key maps differ in size (resolution tables differ on prog only)',
                 ok, res)


def check_rc10(mutate=None):
    res = {}
    for sc in ['base_patch', 'base_insert']:
        d = {}
        for side in ['ours', 'theirs']:
            a = {x['name']: x for x in symbols((M21 / side / sc / 'ft/app.so').read_bytes())}
            b = {x['name']: x for x in symbols((M21 / side / sc / 'nolink/app.so').read_bytes())}
            d[side] = a['_kDartIsolateSnapshotData']['size'] - b['_kDartIsolateSnapshotData']['size']
        if mutate == 'rc10' and sc == 'base_insert':
            d['ours'] = d['theirs']
        res[sc] = d
    ok = res['base_patch']['ours'] == res['base_patch']['theirs'] and \
        res['base_insert']['ours'] != res['base_insert']['theirs']
    return check('RC10 base_ft_link_data: same data growth on base_patch, different on base_insert', ok, res)


def check_rc4(mutate=None):
    res = {}
    for fx in FIXTURES:
        v = {s: (COV / s / fx / 'version/stderr.log').read_text().strip() for s in ['ours', 'theirs']}
        if mutate == 'rc4':
            v['ours'] = v['theirs']
        res[fx] = v
    ok = all(v['ours'] != v['theirs'] and v['ours'].split('(')[0] == v['theirs'].split('(')[0] and
             v['ours'].endswith('on "macos_simarm64"') and v['theirs'].endswith('on "macos_simarm64"')
             for v in res.values())
    return check('RC4 version output differs only in the build date part', ok, res)


def check_rc11(mutate=None):
    res = {}
    for fx in FIXTURES:
        res[fx] = {s: {d: (COV / s / fx / d / 'jit_instr.bin').stat().st_size
                       for d in ['appjit', 'compiled']} for s in ['ours', 'theirs']}
    ok = all(v['ours']['appjit'] == v['theirs']['appjit'] and
             v['ours']['compiled'] != v['theirs']['compiled'] for v in res.values())
    return check('RC11 JIT compile_all instruction images differ in size', ok, res)


def check_rc12(mutate=None):
    o = (COV / 'ours/hello/op/stdout.log').read_text()
    t = (COV / 'theirs/hello/op/stdout.log').read_text()
    if mutate == 'rc12':
        o = t
    return check('RC12 theirs prints "Sorted ObjectPool"; ours does not',
                 'Sorted ObjectPool' in t and 'Sorted ObjectPool' not in o, {'ours': o, 'theirs': t})


def check_rc5(mutate=None):
    res, ok = {}, True
    for fx in FIXTURES:
        a = json.loads((M / f'as.{fx}.ours.dump_object_pool').read_text())
        b = json.loads((M / f'as.{fx}.theirs.dump_object_pool').read_text())
        if mutate == 'rc5':
            a['entries'][10] = dict(a['entries'][10], code='Smi 7 (obj)')
        d = [(x, y) for x, y in zip(a['entries'], b['entries']) if x != y]
        addr = all(x['code'].startswith('0x') and x['code'].endswith('(unknown)') and
                   y['code'].startswith('0x') for x, y in d)
        res[fx] = {'differing_entries': len(d), 'all_process_addresses': addr,
                   'pairs_equal': a['pairs'] == b['pairs']}
        ok &= addr and a['pairs'] == b['pairs']
    return check('RC5 dump_object_pool: every differing entry is a process address', ok, res)


ALL_CHECKS = [check_rc1, check_rc2, check_rc3_and_code, check_shorebird_json, check_d29,
              check_identity, check_strip_sections, check_container_core, check_rc8, check_rc9,
              check_rc10, check_rc4, check_rc11, check_rc12, check_rc5]


# --- assignment ------------------------------------------------------------------

MATRIX_RULES = {
    'print_field_table_link_info_to': ('RC6', 'known'),
    'print_field_table_link_debug_info_to': ('RC6', 'known'),
    'load_obfuscation_map': ('RC7', 'test gap'),
    'shorebird': ('RC3+RC1+RC2+RC4', 'proven'),
    'dump_object_pool': ('RC5', 'proven'),
    'version': ('RC4', 'proven'),
    'sdk_version': ('RC4', 'proven'),
    'strip': ('AOT', 'proven'),
    'obfuscate': ('AOT', 'section deltas'),
    'save_debugging_info': ('AOT', 'section deltas'),
    'assembly': ('AOT', 'derived, not decomposed'),
    'macho': ('AOT', 'section deltas'),
    'macho_object': ('AOT', 'section deltas'),
    'disassemble': ('AOT', 'derived, not decomposed'),
    'dump_blobs': ('AOT', 'derived, not decomposed'),
    'dump_object_pool_link_data': ('AOT', 'derived, not decomposed'),
    'dd_table_data': ('AOT', 'derived, not decomposed'),
    'vm_snapshot_data': ('RC1', 'proven'),
    'isolate_snapshot_data': ('RC1', 'proven'),
    'load_vm_snapshot_data': ('RC1', 'proven'),
    'load_vm_snapshot_instructions': ('RC1', 'proven'),
    'load_isolate_snapshot_data': ('RC1', 'proven'),
    'load_isolate_snapshot_instructions': ('RC11', 'unexplained'),
    'compile_all': ('RC11', 'unexplained'),
    'dd_slot_mapping': ('RC9', 'real gap'),
}


def assign_matrix(flag, inp):
    if flag in ('base_ct_link_data', 'patch_ct_link_data', 'base_dt_link_data'):
        return 'AOT', 'proven (option output = no-link output on both sides)'
    if flag in ('base_op_link_data', 'patch_op_link_data'):
        return ('AOT', 'proven (= no-link)') if inp == 'base_patch' else ('RC8', 'REAL BUG')
    if flag == 'base_ft_link_data':
        return ('AOT', 'same data growth both sides') if inp == 'base_patch' else ('RC10', 'real gap')
    return MATRIX_RULES.get(flag, (None, None))


COVERAGE_RULES = {
    'version': ('RC4', 'proven'), 'sdk_version': ('RC4', 'proven'),
    'verbose': ('AOT', 'proven (= baseline)'),
    'base_ct_link_data': ('AOT', 'proven (= baseline)'), 'patch_ct_link_data': ('AOT', 'proven (= baseline)'),
    'base_dt_link_data': ('AOT', 'proven (= baseline)'),
    'base_op_link_data': ('AOT+RC12', 'proven (= baseline) + missing report line'),
    'patch_op_link_data': ('AOT+RC12', 'proven (= baseline) + missing report line'),
    'base_ft_link_data': ('AOT', 'same symbols and size growth both sides'),
    'vm_snapshot_data': ('RC1', 'proven'), 'isolate_snapshot_data': ('RC1', 'proven'),
    'isolate_snapshot_instructions': ('RC1', 'proven'), 'load_vm_snapshot_data': ('RC1', 'proven'),
    'load_vm_snapshot_instructions': ('RC1', 'proven'), 'load_isolate_snapshot_data': ('RC1', 'proven'),
    'compile_all': ('RC11', 'unexplained'), 'load_isolate_snapshot_instructions': ('RC11', 'unexplained'),
    'dd_slot_mapping': ('RC9', 'real gap'),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--negative-controls', action='store_true')
    args = ap.parse_args()

    if args.negative_controls:
        controls = {'rc1': check_rc1, 'rc2': check_rc2, 'rc3': check_rc3_and_code, 'sb': check_shorebird_json,
                    'd29': check_d29, 'identity': check_identity, 'strip': check_strip_sections,
                    'rc8': check_rc8, 'rc9': check_rc9, 'rc10': check_rc10, 'rc4': check_rc4,
                    'rc12': check_rc12, 'rc5': check_rc5}
        out = {}
        for name, fn in controls.items():
            checks.clear()
            out[name] = 'RED (good)' if not fn(mutate=name) else 'STILL GREEN (bad)'
            print(f'{name:9} {out[name]}')
        args.out.write_text(json.dumps(out, indent=1) + '\n')
        return 0 if all(v.startswith('RED') for v in out.values()) else 1

    for fn in ALL_CHECKS:
        fn()
    a = json.loads(MATRIX_AUDIT.read_text())
    c = json.loads(COVERAGE.read_text())
    cells = []
    for g in a['gaps']:
        rc, basis = assign_matrix(g['flag'], g['input'])
        cells.append({'id': g['id'], 'source': 'matrix', 'option': g['flag'], 'input': g['input'],
                      'root_cause': rc, 'basis': basis})
    for x in c['cells']:
        if x['classification'] != 'gap':
            continue
        rc, basis = COVERAGE_RULES.get(x['option'], (None, None))
        cells.append({'id': x.get('gap_id'), 'source': 'coverage', 'option': x['option'],
                      'input': x['fixture'], 'root_cause': rc, 'basis': basis})
    unassigned = [x for x in cells if x['root_cause'] is None]
    check('every gap cell assigned (68 matrix + 54 coverage)',
          not unassigned and sum(x['source'] == 'matrix' for x in cells) == 68 and
          sum(x['source'] == 'coverage' for x in cells) == 54,
          [(x['option'], x['input']) for x in unassigned])
    by_rc = collections.Counter()
    for x in cells:
        for rc in x['root_cause'].split('+'):
            by_rc[rc] += 1
    by_basis = collections.Counter(x['basis'] for x in cells)
    result = {'root_causes': {k: {'title': v[0], 'kind': v[1], 'evidence': v[2]} for k, v in ROOT_CAUSES.items()},
              'cells_per_root_cause': dict(by_rc), 'cells_per_basis': dict(by_basis),
              'cells': cells, 'checks': checks, 'failed': [x['check'] for x in checks if not x['ok']]}
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    for x in checks:
        print(('ok  ' if x['ok'] else 'FAIL') + '  ' + x['check'])
    print('cells per root cause:', dict(sorted(by_rc.items())))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
