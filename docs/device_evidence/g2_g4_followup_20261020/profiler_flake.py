#!/usr/bin/env python3
"""Re-read the symmetric Profiler_EnterExitIsolate repeat (2026-10-20).

The G2 recheck on SDK 41693e90584 had one ours-only failure,
vm/cc/Profiler_EnterExitIsolate, crashing at profiler.cc:1249
`fp_ != nullptr`. Stock had run that test once. The raw runs are in the
ignored scratchpad/g2_profiler_flake_20261020/runs.jsonl (written by run.py
there): ours and stock DebugSIMARM64 run_vm_tests, interleaved in one shuffled
job list with 11 concurrent workers ("loaded"), then one at a time ("idle").

Prints per condition and side the count of each verdict, and whether ours
crashes with that signature no more often than stock. --self-test flips every
stock crash to pass and must turn the verdict red.
"""

import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
RUNS = REPO / 'scratchpad/g2_profiler_flake_20261020/runs.jsonl'
META = REPO / 'scratchpad/g2_profiler_flake_20261020/meta.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    runs = [json.loads(line) for line in RUNS.read_text().splitlines() if line.strip()]
    if args.self_test:
        for run in runs:
            if run['side'] == 'stock' and run['verdict'] == 'crash_profiler_fp':
                run['verdict'] = 'pass'
    table = collections.defaultdict(collections.Counter)
    for run in runs:
        table[f"{run['condition']}/{run['side']}"][run['verdict']] += 1
    meta = json.loads(META.read_text())
    crashes = {side: sum(c['crash_profiler_fp'] for k, c in table.items() if k.endswith('/' + side))
               for side in ('ours', 'stock')}
    other = sum(c['other_failure'] + c['timeout'] for c in table.values())
    report = {'runs_sha256': hashlib.sha256(RUNS.read_bytes()).hexdigest(),
              'artifacts_unchanged': meta['artifacts_before'] == meta.get('artifacts_after'),
              'artifacts': meta['artifacts_before'],
              'table': {k: dict(v) for k, v in sorted(table.items())},
              'crashes': crashes, 'other_failures': other,
              'stock_shows_same_crash': crashes['stock'] > 0,
              'ours_not_worse': crashes['ours'] <= crashes['stock'] and other == 0}
    report['verdict'] = ('SHARED_UPSTREAM_FLAKE' if report['stock_shows_same_crash']
                         and report['ours_not_worse'] and report['artifacts_unchanged']
                         else 'NOT_SHOWN')
    print(json.dumps(report, indent=2))
    green = report['verdict'] == 'SHARED_UPSTREAM_FLAKE'
    if args.self_test:
        return 0 if not green else 1
    return 0 if green else 1


if __name__ == '__main__':
    sys.exit(main())
