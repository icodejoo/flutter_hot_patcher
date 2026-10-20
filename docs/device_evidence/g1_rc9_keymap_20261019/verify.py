#!/usr/bin/env python3
"""Read-only check of the eight isolated prog voter runs."""

import hashlib
import json
import re
from pathlib import Path

from post_fix import CASES, GEN
from probe import KERNEL, ORIGINAL, OUTPUT, ROOT, sha, split_slots


def check():
    manifest = json.loads((OUTPUT / 'manifest.json').read_text())
    assert manifest['original_sha256'] == sha(ORIGINAL)
    assert manifest['kernel_sha256'] == sha(KERNEL)
    slots = split_slots(ORIGINAL.read_bytes())
    assert len(slots) == 8
    expected = {(slot, side) for slot, _, _ in slots for side in ('ours', 'ref')}
    runs = manifest['runs']
    assert {(r['slot_id'], r['side']) for r in runs} == expected
    assert len(runs) == len(expected)

    for slot, count, raw in slots:
        case = OUTPUT / f'slot_{slot}'
        voter = case / 'voters.bin'
        assert voter.read_bytes() == ORIGINAL.read_bytes()[:8] + b'\x81' + raw
        for side in ('ours', 'ref'):
            row = next(r for r in runs if r['slot_id'] == slot and
                       r['side'] == side)
            assert row['voters'] == count == 1
            assert row['pid'] > 0 and row['started_ns'] < row['ended_ns']
            assert row['rc'] == 0 and row['voters_sha256'] == sha(voter)
            assert row['command'][0].endswith('/gen_snapshot' +
                                              ('.arm64' if side == 'ref' else ''))
            assert row['command'][-1] == str(KERNEL)
            for suffix, field in [('stdout', 'stdout_sha256'),
                                  ('stderr', 'stderr_sha256'),
                                  ('so', 'elf_sha256'),
                                  ('tsv', 'tsv_sha256')]:
                path = case / f'{side}.{suffix}'
                assert (sha(path) if path.exists() else None) == row[field]
            stderr = (case / f'{side}.stderr').read_text()
            counts = [int(x) for x in re.findall(
                r'DD resolution: .*?from (\d+) functions in key map', stderr)]
            assert counts == row['first_second_keymap_counts']
            assert counts == ([5393, 5623] if side == 'ours' else
                              [5253, 5623])

    slot4 = OUTPUT / 'slot_4'
    ours = (slot4 / 'ours.stderr').read_text().splitlines()[0]
    ref = (slot4 / 'ref.stderr').read_text().splitlines()[0]
    assert 'caller_miss=1' in ours and 'tgt_miss=0' in ours
    assert 'caller_miss=0' in ref and 'tgt_miss=1' in ref
    post = json.loads((OUTPUT / 'post_fix_manifest.json').read_text())
    assert {r['case'] for r in post} == set(CASES)
    for row in post:
        name = row['case']
        voters, kernel, reference = CASES[name]
        assert row['pid'] > 0 and row['started_ns'] < row['ended_ns']
        assert row['rc'] == 0 and row['tsv_matches_reference']
        assert row['binary_sha256'] == sha(GEN)
        assert row['input_sha256_before'] == row['input_sha256_after'] == \
            [sha(voters), sha(kernel)]
        assert row['reference_tsv_sha256'] == sha(reference)
        assert (OUTPUT / f'{name}_after.tsv').read_bytes() == \
            reference.read_bytes()
        for suffix, key in [('so', 'elf'), ('tsv', 'tsv'),
                            ('stdout', 'stdout'), ('stderr', 'stderr')]:
            assert sha(OUTPUT / f'{name}_after.{suffix}') == \
                row['output_sha256'][key]
        if name == 'prog':
            old_count, ref_count = '5393', '5253'
            reference_stderr = reference.with_name('stderr.log')
        elif name == 'hello':
            old_count, ref_count = '2896', '2878'
            reference_stderr = reference.with_name('stderr.log')
        else:
            old_count, ref_count = '2896', '2878'
            reference_stderr = ROOT / 'scratchpad/g1_rc9_tie_20261019/forward_ref/stderr.log'
        actual_stderr = (OUTPUT / f'{name}_after.stderr').read_text()
        assert actual_stderr.replace(old_count, ref_count) == \
            reference_stderr.read_text()
    return {'passed': True, 'bound_runs': len(runs),
            'isolated_slots': len(slots), 'slot4_different_drop_reason': True,
            'post_fix_runs': len(post),
            'post_fix_stderr_differs_only_in_first_keymap_count': True}


if __name__ == '__main__':
    result = check()
    print(json.dumps(result, indent=2))
