#!/usr/bin/env python3
"""Run small ELF segment metadata controls against frozen loader binaries."""
import hashlib
import json
from pathlib import Path
import resource
import struct
import sys

REPO = Path('/Users/Cruz/Documents/flutter_hot_patcher')
sys.path.insert(0, str(REPO / 'tools'))
from g4_compare_loaders import run


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def headers(data):
    h = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    return [(h[5] + i * h[9], struct.unpack_from('<IIQQQQQQ', data, h[5] + i * h[9]))
            for i in range(h[10])]


def constraints(data):
    return [{'index': i, 'offset': p[2], 'filesz': p[5], 'memsz': p[6],
             'file_range_valid': p[2] <= len(data) and p[5] <= len(data) - p[2],
             'filesz_le_memsz': p[5] <= p[6]}
            for i, (_, p) in enumerate(headers(data)) if p[0] == 1]


def variants(data):
    loads = [(off, p) for off, p in headers(data) if p[0] == 1]
    first, p = loads[0]; last, q = loads[-1]
    out = {'baseline': data, 'trailing_byte': data + b'\0'}
    changes = {
        'original_outside_file': [(first + 32, len(data) + 4096)],
        'filesz_over_memsz_within_file': [(first + 32, p[6] + 1)],
        'last_segment_exact_eof': [(last + 32, len(data) - q[2]), (last + 40, len(data) - q[2])],
        'last_segment_one_past_eof': [(last + 32, len(data) - q[2] + 1), (last + 40, len(data) - q[2] + 1)],
        'last_segment_one_zero_tail': [(last + 40, q[6] + 1)],
    }
    for name, fields in changes.items():
        b = bytearray(data)
        for off, value in fields:
            struct.pack_into('<Q', b, off, value)
        out[name] = bytes(b)
    return out


def main():
    base = REPO / 'scratchpad/g1_g4_20261016/loaders_v3'
    out = REPO / 'scratchpad/g4_resolution_20261016/segment_boundary'
    out.mkdir(parents=True, exist_ok=False)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    bins = {
        'ours': Path('/Users/Cruz/dart-3122/sdk/xcodebuild/ProductSimIosARM64/clang_arm64/analyze_snapshot'),
        'theirs': Path('/Users/Cruz/.shorebird/bin/cache/flutter/c15ef6379403a0a55531a058bdb2c8e55bc05c98/bin/cache/artifacts/engine/ios-release/analyze_snapshot_arm64'),
        'direct_ours': REPO / 'scratchpad/g1_g4_20261016/direct_loader/g4_load_elf_probe',
    }
    report = {'scope': 'ELF metadata controls, not device acceptance',
              'binaries_sha256': {k: sha(p) for k, p in bins.items()}, 'cases': {}}
    for side in ('ours', 'theirs'):
        data = (base / side / 'baseline.so').read_bytes()
        for case, modified in variants(data).items():
            path = out / side / (case + '.so'); path.parent.mkdir(exist_ok=True)
            path.write_bytes(modified)
            row = run(bins[side], path, out / side / case)
            row['segments'] = constraints(modified)
            if row['disposition'] == 'accepted':
                row['class_output_sha256'] = sha(out / side / case / 'classes.json')
            report['cases'].setdefault(case, {})[side] = row
            if side == 'ours':
                report['cases'][case]['direct_ours'] = run(bins['direct_ours'], path,
                                                          out / 'direct' / case, direct=True)
            print(side, case, row['disposition'], flush=True)
    failures = []
    for case, paired in report['cases'].items():
        conforming = all(p['file_range_valid'] and p['filesz_le_memsz'] for p in paired['ours']['segments'])
        for side in ('ours', 'theirs', 'direct_ours'):
            expected = 'accepted' if conforming or side == 'theirs' else 'rejected'
            if paired[side]['disposition'] != expected:
                failures.append(case + '/' + side + ': unexpected disposition')
        for side in ('ours', 'theirs'):
            if paired[side]['disposition'] == 'accepted':
                if paired[side]['class_output_sha256'] != report['cases']['baseline'][side]['class_output_sha256']:
                    failures.append(case + '/' + side + ': class output changed')
    if report['binaries_sha256'] != {k: sha(p) for k, p in bins.items()}:
        failures.append('binary identity changed')
    report.update(status='VERIFIED_STRICT_REJECTION' if not failures else 'INCOMPLETE', failures=failures)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(report['status'], failures)
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
