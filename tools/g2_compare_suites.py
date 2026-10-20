#!/usr/bin/env python3
"""Compare one pair of complete upstream G2 suite runs, preserving duplicates."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

from g2_run_suite import validate_cc_execution, validate_pipeline_log, validate_verdict


def load_run(directory):
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest.get('status') not in {'PASS', 'FAIL'}:
        raise ValueError(f'{directory}: run has not completed validation')
    data = (directory / 'results.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest.get('results_sha256'):
        raise ValueError(f'{directory}: results hash mismatch')
    selected = json.loads((directory / 'selected.json').read_text())
    if not selected or any(type(n) is not int or n <= 0 for n in selected.values()):
        raise ValueError(f'{directory}: invalid selection')
    rows = [json.loads(line) for line in data.decode().splitlines()]
    if Counter(row['name'] for row in rows) != Counter(selected):
        raise ValueError(f'{directory}: execution coverage differs from selection')
    if len(rows) != manifest.get('rows') or len(rows) != manifest.get('selected'):
        raise ValueError(f'{directory}: declared counts disagree with results')
    for row in rows:
        validate_verdict(row)
    log = (directory / 'run.log').read_text()
    validate_cc_execution(Counter(selected), log)
    validate_pipeline_log(log)
    failed = sum(not row['matches'] for row in rows)
    if manifest['status'] != ('FAIL' if failed else 'PASS'):
        raise ValueError(f'{directory}: declared status disagrees with results')
    if manifest.get('runner_rc') != int(bool(failed)):
        raise ValueError(f'{directory}: runner exit disagrees with results')
    command = manifest['command']
    config = tuple(command[command.index(flag) + 1] for flag in ['-m', '-a', '-c', '-r'])
    args_path = Path(manifest['build']) / 'args.gn'
    args = args_path.read_bytes()
    if hashlib.sha256(args).hexdigest() != manifest.get('sha256', {}).get(str(args_path)):
        raise ValueError(f'{directory}: build arguments do not match recorded identity')
    normalized_args = sorted(line.strip() for line in args.decode().splitlines()
                             if line.strip() and not line.lstrip().startswith('#')
                             and not line.strip().startswith('dart_version_git_info ='))
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['name']].append(row)
    return manifest, config, normalized_args, grouped


def compare(ours_path, stock_path, ignored_args=()):
    om, oc, oa, ours = load_run(ours_path)
    sm, sc, sa, stock = load_run(stock_path)
    # Only the named gn keys may differ, and only when explicitly requested;
    # the waived lines are reported so the result names its own exception.
    def key(line):
        return line.split('=', 1)[0].strip()
    waived = sorted(line for line in set(oa) ^ set(sa) if key(line) in ignored_args)
    oa = [line for line in oa if line not in waived]
    sa = [line for line in sa if line not in waived]
    if oc != sc or oa != sa or om['suites'] != sm['suites']:
        raise ValueError('different configurations, arguments or suite selections')
    regressions, improvements, shared_failures, unresolved = [], [], [], []
    for name in sorted(ours.keys() & stock.keys()):
        a, b = ours[name], stock[name]
        if Counter(row['expected'] for row in a) != Counter(row['expected'] for row in b):
            unresolved.append(name)
            continue
        af, bf = sum(not r['matches'] for r in a), sum(not r['matches'] for r in b)
        detail = {'name': name, 'ours_failures': af, 'stock_failures': bf}
        if af > bf:
            regressions.append(detail)
        elif af < bf:
            improvements.append(detail)
        elif af:
            shared_failures.append(detail)
    ours_only = sorted(ours.keys() - stock.keys())
    stock_only = sorted(stock.keys() - ours.keys())
    extra_failures = [name for name in ours_only if any(not r['matches'] for r in ours[name])]
    status = ('REGRESSION' if regressions or extra_failures else
              'INCOMPLETE' if unresolved or stock_only else 'COMPARABLE')
    return {'scope': 'one paired upstream suite/configuration; not the whole G2 gate',
            'status': status, 'exit_code': {'COMPARABLE': 0, 'REGRESSION': 1, 'INCOMPLETE': 2}[status],
            'configuration': oc, 'suites': om['suites'], 'waived_build_args': waived,
            'ours_rows': om['rows'], 'stock_rows': sm['rows'],
            'ours_results_sha256': om['results_sha256'], 'stock_results_sha256': sm['results_sha256'],
            'ours_worse': regressions, 'ours_better': improvements,
            'shared_failures': shared_failures, 'unresolved': unresolved,
            'ours_only': ours_only, 'ours_only_failures': extra_failures, 'stock_only': stock_only}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('ours', type=Path)
    p.add_argument('stock', type=Path)
    p.add_argument('--ignore-build-arg', action='append', default=[],
                   help='gn key allowed to differ between the two builds')
    a = p.parse_args()
    try:
        result = compare(a.ours, a.stock, tuple(a.ignore_build_arg))
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f'REFUSED: {e}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return result['exit_code']


if __name__ == '__main__':
    sys.exit(main())
