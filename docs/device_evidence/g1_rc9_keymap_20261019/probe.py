#!/usr/bin/env python3
"""Split the archived prog DD voters by slot and bind both tool outcomes."""

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path('/Users/Cruz/dart-3122/sdk')
RESEARCH = Path('/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle')
ORIGINAL = ROOT / 'scratchpad/g1_coverage_20261016/run_v2/voters/prog/voters.bin'
KERNEL = RESEARCH / 'out_disas/prog.dill'
OUTPUT = ROOT / 'scratchpad/g1_rc9_keymap_20261019'
BINARIES = {
    'ours': SDK / 'xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot',
    'ref': RESEARCH / 'bin/gen_snapshot.arm64',
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_unsigned(data, pos):
    start = pos
    value = 0
    shift = 0
    while pos < len(data):
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7f) << shift
        if byte & 0x80:
            return value, data[start:pos], pos
        shift += 7
    raise ValueError('truncated unsigned integer')


def split_slots(data):
    assert data[:8] == bytes.fromhex('557ecadd02000000')
    count, _, pos = read_unsigned(data, 8)
    slots = []
    for _ in range(count):
        start = pos
        slot_id, _, pos = read_unsigned(data, pos)
        voters, _, pos = read_unsigned(data, pos)
        for _ in range(voters * 10):
            _, _, pos = read_unsigned(data, pos)
        slots.append((slot_id, voters, data[start:pos]))
    assert pos == len(data)
    return slots


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    slots = split_slots(ORIGINAL.read_bytes())
    result = {
        'original_sha256': sha(ORIGINAL),
        'kernel_sha256': sha(KERNEL),
        'binary_sha256': {name: sha(path) for name, path in BINARIES.items()},
        'runs': [],
    }
    for slot_id, voters, raw_slot in slots:
        case = OUTPUT / f'slot_{slot_id}'
        case.mkdir(exist_ok=True)
        voter_file = case / 'voters.bin'
        voter_file.write_bytes(ORIGINAL.read_bytes()[:8] + b'\x81' + raw_slot)
        for name, binary in BINARIES.items():
            output = case / f'{name}.so'
            resolution = case / f'{name}.tsv'
            command = [str(binary), '--snapshot_kind=app-aot-elf',
                       f'--elf={output}', f'--dd_slot_mapping={voter_file}',
                       f'--print_dd_resolution_to={resolution}', str(KERNEL)]
            started = time.time_ns()
            process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            stdout, stderr = process.communicate(timeout=120)
            ended = time.time_ns()
            (case / f'{name}.stdout').write_bytes(stdout)
            (case / f'{name}.stderr').write_bytes(stderr)
            lines = re.findall(r'DD resolution: .*?from (\d+) functions in key map',
                               stderr.decode(errors='replace'))
            row = {
                'slot_id': slot_id, 'voters': voters, 'side': name,
                'pid': process.pid, 'started_ns': started, 'ended_ns': ended,
                'command': command, 'rc': process.returncode,
                'voters_sha256': sha(voter_file),
                'first_second_keymap_counts': [int(x) for x in lines],
                'stdout_sha256': sha(case / f'{name}.stdout'),
                'stderr_sha256': sha(case / f'{name}.stderr'),
                'elf_sha256': sha(output) if output.exists() else None,
                'tsv_sha256': sha(resolution) if resolution.exists() else None,
            }
            result['runs'].append(row)
            print(slot_id, name, row['rc'], row['first_second_keymap_counts'],
                  stderr.decode(errors='replace').splitlines()[:2], flush=True)
    (OUTPUT / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
