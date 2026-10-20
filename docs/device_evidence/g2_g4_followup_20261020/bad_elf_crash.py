#!/usr/bin/env python3
"""Tie each side's bad_elf_type first patched boot to its device crash report.

The 2026-10-19 new-engine G4 run recorded "exit code 0" for ours and
"signal 6" for theirs, both from `devicectl --console`. The device kept a
crash report for each boot. This reads both reports and checks, per side:
  - the report's pid is the boot stage's device_pid in report.json
  - the report's Flutter LC_UUID is the Flutter.framework in that side's
    installed Runner.app
  - the termination signal
The crash reports stay in the ignored scratchpad (copied from the device with
`devicectl device copy from --domain-type systemCrashLogs`).

--self-test feeds a report with the pid altered and must fail.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
CRASHES = REPO / 'scratchpad/g4_bad_elf_exit_20261020'
RUNS = REPO / 'scratchpad/g3_20261019/g4_new_engine/device/runs'
REPORTS = {'theirs': 'Runner-2026-10-19-183006.ips', 'ours': 'Runner-2026-10-19-183020.ips'}


def read_ips(path):
    head, body = path.read_text().split('\n', 1)
    return json.loads(head), json.loads(body)


def flutter_uuid(binary):
    out = subprocess.run(['dwarfdump', '--uuid', str(binary)], capture_output=True,
                         text=True, check=True).stdout
    return out.split()[1].lower()


def assess(side, header, body):
    run = json.loads((RUNS / f'{side}_bad_elf_type_v5/report.json').read_text())
    boot = run['stages']['boot']
    images = body['usedImages']
    crash_uuid = next(i['uuid'] for i in images if i.get('name') == 'Flutter')
    installed = flutter_uuid(RUNS / f'{side}_bad_elf_type_v5/Runner.app/Frameworks/Flutter.framework/Flutter')
    thread = body['threads'][body['faultingThread']]
    frames = [f"{images[f['imageIndex']].get('name')}:{f.get('symbol') or hex(f['imageOffset'])}"
              for f in thread['frames'][:8]]
    row = {'bundle': header.get('bundleID'), 'pid': body.get('pid'), 'boot_device_pid': boot['device_pid'],
           'devicectl_said_exit': boot['devicectl_returncode_before_teardown'],
           'signal': body['exception'].get('signal'), 'termination': body['termination'].get('indicator'),
           'flutter_uuid_in_crash': crash_uuid, 'flutter_uuid_installed': installed,
           'faulting_frames': frames}
    row['ok'] = (row['pid'] == row['boot_device_pid'] and crash_uuid == installed
                 and f'.{side}.' in (row['bundle'] or ''))
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    rows = {}
    for side, name in REPORTS.items():
        header, body = read_ips(CRASHES / name)
        if args.self_test and side == 'ours':
            body['pid'] += 1
        rows[side] = assess(side, header, body)
    same = all(r['ok'] for r in rows.values()) and rows['ours']['signal'] == rows['theirs']['signal'] == 'SIGABRT'
    print(json.dumps({'rows': rows, 'both_sigabrt_and_tied_to_run': same}, indent=2, ensure_ascii=False))
    if args.self_test:
        return 0 if not same else 1
    return 0 if same else 1


if __name__ == '__main__':
    sys.exit(main())
