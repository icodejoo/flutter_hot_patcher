#!/usr/bin/env python3
"""Bind current-tool DD output after the target-first rejection fix."""

import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = Path('/Users/Cruz/Documents/fhp-research/spikes/shorebird_linkinfo_oracle')
GEN = Path('/Users/Cruz/dart-3122/sdk/xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot')
OUT = ROOT / 'scratchpad/g1_rc9_keymap_20261019'
CASES = {
    'hello': (
        ROOT / 'scratchpad/g1_coverage_20261016/run_v2/voters/hello/voters.bin',
        RESEARCH / 'out_verify/hello.dill',
        ROOT / 'scratchpad/g1_coverage_20261016/run_v2/theirs/hello/dd/resolution.tsv'),
    'prog': (
        ROOT / 'scratchpad/g1_coverage_20261016/run_v2/voters/prog/voters.bin',
        RESEARCH / 'out_disas/prog.dill',
        ROOT / 'scratchpad/g1_coverage_20261016/run_v2/theirs/prog/dd/resolution.tsv'),
    'tie': (
        ROOT / 'scratchpad/g1_rc9_tie_20261019/forward.voters.bin',
        RESEARCH / 'out_verify/hello.dill',
        ROOT / 'scratchpad/g1_rc9_tie_20261019/forward_ref/resolution.tsv'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    rows = []
    binary_hash = sha(GEN)
    for name, (voters, kernel, reference) in CASES.items():
        elf = OUT / f'{name}_after.so'
        tsv = OUT / f'{name}_after.tsv'
        stdout = OUT / f'{name}_after.stdout'
        stderr = OUT / f'{name}_after.stderr'
        command = [str(GEN), '--snapshot_kind=app-aot-elf', f'--elf={elf}',
                   f'--dd_slot_mapping={voters}',
                   f'--print_dd_resolution_to={tsv}', str(kernel)]
        input_before = [sha(voters), sha(kernel)]
        started = time.time_ns()
        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        out, err = process.communicate(timeout=120)
        ended = time.time_ns()
        stdout.write_bytes(out)
        stderr.write_bytes(err)
        row = {'case': name, 'pid': process.pid, 'started_ns': started,
               'ended_ns': ended, 'command': command, 'rc': process.returncode,
               'binary_sha256': binary_hash,
               'input_sha256_before': input_before,
               'input_sha256_after': [sha(voters), sha(kernel)],
               'reference_tsv_sha256': sha(reference),
               'output_sha256': {key: sha(path) for key, path in
                                 [('elf', elf), ('tsv', tsv),
                                  ('stdout', stdout), ('stderr', stderr)]},
               'tsv_matches_reference': tsv.read_bytes() == reference.read_bytes()}
        rows.append(row)
        print(name, row['rc'], row['tsv_matches_reference'])
    (OUT / 'post_fix_manifest.json').write_text(json.dumps(rows, indent=2) + '\n')
    assert all(r['rc'] == 0 and r['tsv_matches_reference'] for r in rows)


if __name__ == '__main__':
    main()
