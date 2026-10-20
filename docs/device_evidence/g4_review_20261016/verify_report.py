#!/usr/bin/env python3
"""Read-only verification of the agy G4 DD-crash report (2026-10-16).

Checks only evidence that already exists: the fresh_run inputs/outputs and
report.json, the macOS crash reports (.ips) the report cites, the matrix DD
inputs, and the public datastream format. It runs no analyzer, no debugger and
no disassembler.

Writes a JSON verdict (with no reference instruction bytes, no machine
identifiers) to --out, and prints a summary. Exit 0 if every check passes,
1 if any check fails.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path('/Users/Cruz/Documents/flutter_hot_patcher')
AGY = REPO / 'scratchpad/agy_g4_review_20261016'
MATRIX = REPO / 'scratchpad/g1_g4_20261016/matrix_final'
IPS_DIR = Path.home() / 'Library/Logs/DiagnosticReports'
SDK = Path('/Users/Cruz/dart-3122/sdk')
SDK_HEAD = '8367f9e0ca624cb8d2cc02ce2f38d677a3f1bdf0'
SDK_DIFF_SHA = '6f1ec5170a0b3da5236b4deb68986c9855f3ea4d42e12b6cc8fedc44c3f74cbd'
EXPECTED_INPUTS = {
    'ddt': (3969, '6a6645b15903f00e8a80629e64f0646bf1a751cf527edabc1fad70b2ebaa41c7'),
    'ddcl': (54060, '6e5441ac2344db164330e165aa4dbb44e9fd5be7948c66d12ba7a46fc97bb74e'),
    'ddid': (14925, 'a57f0cc0db8b2703e710d364c77a82ae1241faee436b937d063450d8ca592cc6'),
}
# The case -> crash report correspondence the agy report asserts (BRIEF item 5).
CASE_IPS = {
    'table_count': (16936, '152637.0004'),
    'table_empty_0': (16939, '152637'),
    'table_empty_1': (16940, '152637.0002'),
    'table_empty_2': (16941, '152637.000'),
    'table_trunc1': (16942, '152637.0003'),
    'table_trunc2000': (18158, '161125'),
    'links_flip20000': (18171, '161139'),
}
FLIP_OFFSET = 20000
FLIP_XOR = 0x02

checks = []


def check(name, ok, detail=None):
    checks.append({'check': name, 'ok': bool(ok), 'detail': detail})
    return ok


def sha(data):
    return hashlib.sha256(data).hexdigest()


# --- public datastream format (runtime/vm/datastream.h) -----------------------
# Data bytes are 0..127, seven bits each, little-endian; the final byte is
# > 127 and carries (b - 128) for unsigned values, (b - 192) for signed ones.
# This is the rule the SDK's DDInputReader applies (analyze_snapshot_api_impl.cc
# ~2388); research datastream.py tests `b >= marker`, which agrees for the
# unsigned values and non-negative characters these files contain.

class Truncated(Exception):
    pass


class Reader:
    def __init__(self, data):
        self.d, self.i = data, 0

    def pending(self):
        return len(self.d) - self.i

    def varint(self, end_marker):
        start, r, shift = self.i, 0, 0
        while shift < 64:
            if self.i >= len(self.d):
                raise Truncated(start)
            b = self.d[self.i]
            self.i += 1
            if b > 127:
                return start, self.i, r | ((b - end_marker) << shift)
            r |= b << shift
            shift += 7
        raise Truncated(start)

    def unsigned(self):
        return self.varint(128)

    def string(self):
        start, end, n = self.unsigned()
        if n < 0 or n > self.pending():
            raise Truncated(start)
        chars = [self.varint(192) for _ in range(n)]
        return {'len_start': start, 'len_end': end, 'len': n,
                'start': start, 'end': chars[-1][1] if chars else end,
                'value': ''.join(chr(c[2] & 0xFF) for c in chars)}


def parse_table(data):
    """count:u, { hash:str, index:u, size:u } * count. Mirrors the SDK check."""
    r = Reader(data)
    try:
        _, _, count = r.unsigned()
    except Truncated:
        return {'error': 'bad entry count'}
    if count < 0 or count > r.pending() // 3:
        return {'error': 'bad entry count', 'count': count}
    for i in range(count):
        try:
            r.string(); r.unsigned(); r.unsigned()
        except Truncated:
            return {'error': f'truncated at entry {i} of {count}', 'count': count}
    return {'count': count, 'consumed': r.i, 'trailing': len(data) - r.i}


def parse_links(data, fields=None):
    """count:u, { caller_hash:str, dd_index:u, callee_position:u } * count."""
    r = Reader(data)
    try:
        s, e, count = r.unsigned()
    except Truncated:
        return {'error': 'bad link count'}
    if fields is not None:
        fields.append({'link': None, 'field': 'count', 'start': s, 'end': e, 'value': count})
    if count < 0 or count > r.pending() // 3:
        return {'error': 'bad link count', 'count': count}
    for i in range(count):
        try:
            h = r.string()
            if fields is not None:
                fields.append({'link': i, 'field': 'caller_hash.length', 'start': h['len_start'],
                               'end': h['len_end'], 'value': h['len']})
                fields.append({'link': i, 'field': 'caller_hash.chars', 'start': h['len_end'],
                               'end': h['end'], 'value': h['value']})
            for name in ('dd_index', 'callee_position'):
                s, e, v = r.unsigned()
                if fields is not None:
                    fields.append({'link': i, 'field': name, 'start': s, 'end': e, 'value': v})
        except Truncated:
            return {'error': f'truncated at link {i} of {count}', 'count': count}
    return {'count': count, 'consumed': r.i, 'trailing': len(data) - r.i}


# --- crash reports -----------------------------------------------------------

def load_ips(path):
    raw = path.read_bytes()
    _, body = raw.split(b'\n', 1)
    return raw, json.loads(body)


def ips_summary(path):
    raw, b = load_ips(path)
    thread = b['threads'][b.get('faultingThread', 0)]
    ts = thread.get('threadState', {})
    image = b['usedImages'][0]
    exc = b['exception']
    out = {
        'ips_filename': path.name,
        'ips_sha256': sha(raw),
        'pid': b.get('pid'),
        'parent': f"{b.get('parentProc')}/{b.get('parentPid')}",
        'capture_time': b.get('captureTime'),
        'image_uuid': image.get('uuid'),
        'exception': {k: exc.get(k) for k in ('type', 'signal', 'subtype', 'codes')},
        'frames': [{'symbol': f.get('symbol'), 'symbolLocation': f.get('symbolLocation'),
                    'imageOffset': f.get('imageOffset'), 'imageIndex': f.get('imageIndex')}
                   for f in thread['frames']],
    }
    if 'pc' in ts:
        pc = ts['pc']['value']
        out['pc_minus_image_base'] = pc - image['base']
        out['far'] = hex(ts['far']['value']) if 'far' in ts else None
        regs = ts.get('x', [])
        out['x21'] = hex(regs[21]['value']) if len(regs) > 21 and 'value' in regs[21] else None
    return out


def first_dart_frame(frames):
    for f in frames:
        sym = f['symbol'] or ''
        if sym.startswith('dart::') or sym.startswith('std::') and 'DDEntry' in sym:
            return f"{sym.split('(')[0]}+{f['symbolLocation']}"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    result = {'scope': 'read-only re-verification of existing G4 DD evidence; '
                       'no analyzer, debugger or disassembler was run'}

    # 1. Matrix DD inputs: both sides byte-identical and as recorded.
    inputs = {}
    for ext, (size, digest) in EXPECTED_INPUTS.items():
        ours = (MATRIX / f'as.hello.ours.ddsm_in.{ext}').read_bytes()
        theirs = (MATRIX / f'as.hello.theirs.ddsm_in.{ext}').read_bytes()
        inputs[ext] = {'bytes': len(ours), 'sha256': sha(ours), 'sides_identical': ours == theirs}
        check(f'input {ext} both sides identical, {size} B, sha256 as recorded',
              ours == theirs and len(ours) == size and sha(ours) == digest, inputs[ext])
    result['inputs'] = inputs
    table = (MATRIX / 'as.hello.ours.ddsm_in.ddt').read_bytes()
    links = (MATRIX / 'as.hello.ours.ddsm_in.ddcl').read_bytes()

    # 2. fresh_run: every recorded hash matches the file on disk; every input
    #    file is the deterministic mutation tools/g4_compare_dd_inputs.py makes.
    report = json.loads((AGY / 'fresh_run/report.json').read_text())
    flipped = bytearray(links); flipped[FLIP_OFFSET] ^= FLIP_XOR
    changed = bytearray(table); changed[0] = 255
    expected_inputs = {'valid': (table, links), 'table_count': (bytes(changed), links),
                       'table_empty': (b'', links), 'table_trunc1': (table[:1], links),
                       'table_trunc2000': (table[:2000], links),
                       'links_flip20000': (table, bytes(flipped))}
    runs = report['runs']
    check('fresh_run has 16 runs (8 per side)', len(runs) == 16 and
          sum(r['side'] == 'ours' for r in runs) == 8, len(runs))
    hash_mismatch, input_mismatch = [], []
    for r in runs:
        d = AGY / 'fresh_run' / r['side'] / f"{r['case']}_{r['attempt']}"
        for name, digest in r['files_sha256'].items():
            if sha((d / name).read_bytes()) != digest:
                hash_mismatch.append(f"{r['side']}/{r['case']}_{r['attempt']}/{name}")
        dt, cl = expected_inputs[r['case']]
        if (d / 'table').read_bytes() != dt or (d / 'links').read_bytes() != cl:
            input_mismatch.append(f"{r['side']}/{r['case']}_{r['attempt']}")
    check('fresh_run recorded file hashes match disk', not hash_mismatch, hash_mismatch)
    check('fresh_run inputs equal the deterministic mutations of the matrix inputs',
          not input_mismatch, input_mismatch)
    valid = {r['side']: r for r in runs if r['case'] == 'valid'}
    check('valid input accepted on both sides with identical mapping output',
          all(v['disposition'] == 'accepted' for v in valid.values()) and
          valid['ours']['files_sha256']['mapping'] == valid['theirs']['files_sha256']['mapping'],
          valid['ours']['files_sha256']['mapping'])
    bad = [r for r in runs if r['case'] != 'valid']
    ours_bad = [r for r in bad if r['side'] == 'ours']
    theirs_bad = [r for r in bad if r['side'] == 'theirs']
    check('ours: 7 malformed inputs all rc 255 rejected',
          len(ours_bad) == 7 and all(r['returncode'] == 255 and r['disposition'] == 'rejected'
                                     for r in ours_bad))
    sig = sorted(r['signal'] for r in theirs_bad)
    check('theirs: 7 malformed inputs crashed, 4 SIGBUS + 3 SIGABRT',
          sig == ['SIGABRT'] * 3 + ['SIGBUS'] * 4, sig)
    result['fresh_run'] = [{'side': r['side'], 'case': f"{r['case']}_{r['attempt']}",
                            'returncode': r['returncode'], 'signal': r['signal'],
                            'disposition': r['disposition'],
                            'stderr_first_line': r['stderr'].splitlines()[0] if r['stderr'] else ''}
                           for r in runs]
    check('fresh_run binaries recorded', len(report['binaries_sha256']) == 2,
          report['binaries_sha256'])
    result['binaries_sha256'] = report['binaries_sha256']

    # 3. The public-format parser reproduces OUR analyzer's own diagnostics on the
    #    same bytes -- a known-good reading before it is trusted for item 4.
    ours_stderr = {f"{r['case']}_{r['attempt']}": r['stderr'] for r in ours_bad}
    model = {'table_count_0': parse_table(bytes(changed)),
             'table_empty_0': parse_table(b''),
             'table_trunc1_0': parse_table(table[:1]),
             'table_trunc2000_0': parse_table(table[:2000]),
             'links_flip20000_0': parse_links(bytes(flipped))}
    agree = {}
    for case, m in model.items():
        prefix = 'DD caller links: ' if case.startswith('links') else 'DD table: '
        agree[case] = {'model': m.get('error'),
                       'ours_stderr_has_it': f"Error: {prefix}{m.get('error')}" in ours_stderr[case]}
    check('public-format parser reproduces all five distinct ours diagnostics',
          all(a['ours_stderr_has_it'] for a in agree.values()), agree)
    result['parser_agreement'] = agree
    result['valid_table'] = parse_table(table)
    result['valid_links'] = parse_links(links)
    check('valid inputs parse completely under the public format',
          'error' not in result['valid_table'] and 'error' not in result['valid_links'],
          {'table': result['valid_table'], 'links': result['valid_links']})

    # 4. Which field does links[20000] belong to?
    fields = []
    parse_links(links, fields)
    hit = [f for f in fields if f['start'] <= FLIP_OFFSET < f['end']]
    check('offset 20000 lies in exactly one parsed field', len(hit) == 1, hit)
    f = hit[0]
    flip = {'offset': FLIP_OFFSET, 'before': hex(links[FLIP_OFFSET]),
            'after': hex(flipped[FLIP_OFFSET]), 'xor': hex(FLIP_XOR),
            'terminal_bit_unchanged': (links[FLIP_OFFSET] > 127) == (flipped[FLIP_OFFSET] > 127),
            'field': {k: f[k] for k in ('link', 'field', 'start', 'end')},
            'field_value_before': f['value'] if f['field'] != 'caller_hash.chars' else None}
    if f['field'].endswith('length') or f['field'] in ('dd_index', 'callee_position', 'count'):
        n = Reader(bytes(flipped)); n.i = f['start']
        flip['field_value_after'] = n.unsigned()[2]
    hashes = [x['value'] for x in fields if x['field'] == 'caller_hash.length']
    flip['caller_hash_lengths_in_valid_file'] = sorted(set(hashes))
    check('mutation keeps the end-of-varint bit (not a terminator flip)',
          flip['terminal_bit_unchanged'], flip)
    # Follow the desynchronised parse of the mutated file under the public format.
    trace, r = [], Reader(bytes(flipped))
    _, _, count = r.unsigned()
    for i in range(count):
        start = r.i
        try:
            h = r.string(); a = r.unsigned(); b = r.unsigned()
        except Truncated as t:
            trace.append({'link': i, 'start': start, 'truncated_at': t.args[0],
                          'reader_position': r.i, 'file_length': len(flipped)})
            break
        if i >= f['link']:
            trace.append({'link': i, 'start': start, 'end': r.i, 'hash_len': h['len'],
                          'dd_index': a[2], 'callee_position': b[2]})
    flip['desync_trace'] = trace
    last = trace[-1]
    check('public-format parse of the mutated links desyncs from link 340 and '
          'reaches end of file at link 349 (= ours diagnostic)',
          last.get('link') == 349 and last.get('reader_position') == len(flipped) and
          trace[0]['link'] == f['link'], last)
    result['links_flip20000_field'] = flip

    # 5. Crash reports: the seven cited entries equal their .ips files.
    agy7 = {e['case']: e for e in json.loads((AGY / 'all_7_crashes_verified.json').read_text())}
    check('all_7_crashes_verified.json lists the seven cases', sorted(agy7) == sorted(CASE_IPS),
          sorted(agy7))
    stacks = {}
    for case, (pid, stem) in CASE_IPS.items():
        path = IPS_DIR / f'analyze_snapshot_arm64-2026-10-16-{stem}.ips'
        s = ips_summary(path)
        e = agy7[case]
        same = (e['pid'] == pid == s['pid'] and e['ips_filename'] == path.name and
                e['exception']['signal'] == s['exception']['signal'] and
                e['exception']['type'] == s['exception']['type'] and
                [(x['symbol'], x['symbolLocation'], x['imageOffset']) for x in e['frames']] ==
                [(x['symbol'], x['symbolLocation'], x['imageOffset'])
                 for x in s['frames'][:len(e['frames'])]])
        check(f'{case}: agy JSON equals {path.name} (pid, exception, frames)', same)
        s['case'] = case
        s['top_dart_frame'] = first_dart_frame(s['frames'])
        stacks[case] = s
    result['stacks'] = stacks
    tops = {c: s['top_dart_frame'] for c, s in stacks.items()}
    check('table_count/trunc1/trunc2000 SIGBUS at ReadFromStream+436',
          all(tops[c] == 'dart::DDTableLinkInfo::ReadFromStream+436' and
              stacks[c]['exception']['signal'] == 'SIGBUS'
              for c in ('table_count', 'table_trunc1', 'table_trunc2000')), tops)
    lf = stacks['links_flip20000']
    check('links_flip20000 SIGBUS frame 0 is Dart_ComputeDDSlotMapping+732, no '
          'ReadFromStream frame on its stack',
          lf['exception']['signal'] == 'SIGBUS' and
          tops['links_flip20000'] == 'dart::snapshot_analyzer::Dart_ComputeDDSlotMapping+732' and
          not any('ReadFromStream' in (x['symbol'] or '') for x in lf['frames']), tops)
    check('links_flip20000: pc - image base equals frame 0 imageOffset; far equals x21',
          lf['pc_minus_image_base'] == lf['frames'][0]['imageOffset'] and lf['far'] == lf['x21'],
          {k: lf[k] for k in ('pc_minus_image_base', 'far', 'x21')})
    check('empty inputs: SIGABRT via vector<DDEntry>::reserve from ReadFromStream+164',
          all(stacks[c]['exception']['signal'] == 'SIGABRT' and
              any((x['symbol'] or '').startswith('dart::DDTableLinkInfo::ReadFromStream') and
                  x['symbolLocation'] == 164 for x in stacks[c]['frames']) and
              any('reserve' in (x['symbol'] or '') for x in stacks[c]['frames'])
              for c in ('table_empty_0', 'table_empty_1', 'table_empty_2')))
    kinds = {c: ('length_error' if any('length_error' in (x['symbol'] or '') for x in stacks[c]['frames'])
                 else 'bad_alloc' if any('bad_alloc' in (x['symbol'] or '') for x in stacks[c]['frames'])
                 else None) for c in ('table_empty_0', 'table_empty_1', 'table_empty_2')}
    result['empty_input_abort_kind'] = kinds
    check('same reference image in all seven reports',
          len({s['image_uuid'] for s in stacks.values()}) == 1,
          sorted({s['image_uuid'] for s in stacks.values()}))

    # 6. Provenance of the two late reports: which batch produced each report.
    batches = {}
    for p in sorted(IPS_DIR.glob('analyze_snapshot_arm64-2026-10-16-*.ips')):
        s = ips_summary(p)
        batches.setdefault(s['parent'], []).append(
            {'ips': p.name, 'pid': s['pid'], 'signal': s['exception']['signal'],
             'top': first_dart_frame(s['frames'])})
    result['ips_by_parent_process'] = batches
    fresh_parent = stacks['table_count']['parent']
    check('the fresh_run batch (parent of table_count) left exactly 5 reports',
          len(batches[fresh_parent]) == 5, fresh_parent)
    late = {c: stacks[c]['parent'] for c in ('table_trunc2000', 'links_flip20000')}
    check('table_trunc2000 and links_flip20000 reports come from separate later '
          'processes, not the fresh_run batch',
          all(p != fresh_parent and len(batches[p]) == 1 for p in late.values()), late)

    # 7. SDK frozen.
    head = subprocess.run(['git', '-C', str(SDK), 'rev-parse', 'HEAD'],
                          capture_output=True, check=True).stdout.decode().strip()
    diff = subprocess.run(['git', '-C', str(SDK), 'diff'], capture_output=True, check=True).stdout
    check('SDK HEAD unchanged', head == SDK_HEAD, head)
    check('SDK working-tree patch sha256 unchanged (raw git diff bytes)',
          sha(diff) == SDK_DIFF_SHA, sha(diff))

    result['checks'] = checks
    result['failed'] = [c['check'] for c in checks if not c['ok']]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + '\n')
    for c in checks:
        print(('ok  ' if c['ok'] else 'FAIL') + '  ' + c['check'])
    print(f"{len(checks) - len(result['failed'])}/{len(checks)} checks passed")
    print('links[20000]:', json.dumps(flip, ensure_ascii=False))
    return 1 if result['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
