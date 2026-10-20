#!/usr/bin/env python3
"""Compare the new-engine G4 device runs (both v5).

Reads archived reports plus staged framework and payload hashes. Both sides:
scratchpad/g3_20261019/g4_new_engine/device.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OURS = ROOT / 'scratchpad/g3_20261019/g4_new_engine/device'
THEIRS = OURS
CASES = ('valid', 'bad_elf_type', 'bad_version', 'wrong_base', 'bad_signature', 'half_file')
THEIR_REVISION = {case: 'v5' for case in CASES}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def kind(stage):
    return stage['updater_state'].get('patches/1/state.json', {}).get('kind')


def outcome(stages):
    """Final observed disposition: what the user sees after the patch."""
    boot = stages['boot']
    final = stages.get('recovery', boot)
    return {'boot_marker': boot['marker'], 'boot_exited': boot['process_exited_during_observation'],
            'final_marker': final['marker'], 'final_exited': final['process_exited_during_observation'],
            'final_kind': kind(final)}


def load():
    reports = {}
    for case in CASES:
        reports['ours', case] = json.loads((OURS / f'runs/ours_{case}_v5/report.json').read_text())
        revision = THEIR_REVISION.get(case, 'v2')
        reports['theirs', case] = json.loads(
            (THEIRS / f'runs/theirs_{case}_{revision}/report.json').read_text())
    return reports


def assess(reports, check_files=True):
    checks = {}
    manifest = json.loads((OURS / 'manifest_build_v4.json').read_text())['sides']['ours']
    for case in CASES:
        ours, theirs = reports['ours', case], reports['theirs', case]
        for side, report in (('ours', ours), ('theirs', theirs)):
            base = report['stages']['baseline']
            checks[f'{side}_{case}_baseline'] = (base['marker'] == ['BASE_V1'] and
                                                 report['status'] == 'RECORDED')
        if check_files:
            run = OURS / f'runs/ours_{case}_v5'
            checks[f'ours_{case}_framework_identity'] = (
                sha(run / 'Runner.app/Frameworks/Flutter.framework/Flutter') ==
                manifest['signed_framework_sha256'])
            inputs = ours['inputs']
            checks[f'ours_{case}_inputs'] = (
                sha(inputs['delta']) == inputs['delta_sha256'] and
                sha(inputs['control']) == inputs['control_sha256'] and
                sha(OURS / f'ours/cases_v5/{case}.vmcode') == inputs['payload_sha256'])
        a, b = outcome(ours['stages']), outcome(theirs['stages'])
        if case == 'valid':
            checks['valid_both_patch'] = (a['final_marker'] == b['final_marker'] == ['PATCH_V2'] and
                                          not a['final_exited'] and not b['final_exited'])
        elif case == 'bad_version':
            # Same disposition: no app marker in either observation window,
            # process alive, patch still Installed.
            checks['bad_version_same'] = (a == b and a['final_marker'] == [] and
                                          a['final_kind'] == 'Installed' and not a['final_exited'] and
                                          ours['stages']['boot']['elapsed_seconds'] >= 15 and
                                          ours['stages']['recovery']['elapsed_seconds'] >= 15)
        elif case == 'bad_elf_type':
            # The reference exits on signal 6 and ours exits with code 0 on
            # the first patched boot. The scoped G4-03/ELF exception remains;
            # both recover to BASE_V1 / Bad / alive.
            checks['bad_elf_type_final_same'] = (
                a['final_marker'] == b['final_marker'] == ['BASE_V1'] and
                a['final_kind'] == b['final_kind'] == 'Bad' and
                not a['final_exited'] and not b['final_exited'])
            checks['bad_elf_type_both_exit'] = a['boot_exited'] and b['boot_exited']
        else:
            checks[f'{case}_same'] = (a == b and a['final_marker'] == ['BASE_V1'] and
                                      a['final_kind'] == 'Bad' and not a['final_exited'])
    return checks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    reports = load()
    checks = assess(reports)

    negative = {}
    def broken(edit):
        changed = copy.deepcopy(reports)
        edit(changed)
        return not all(assess(changed, check_files=False).values())
    def ours_version_falls_back(r):
        r['ours', 'bad_version']['stages']['boot']['marker'] = ['BASE_V1']
        r['ours', 'bad_version']['stages']['boot']['updater_state'] = {
            'patches/1/state.json': {'kind': 'Bad'}}
    negative['ours_bad_version_fallback'] = broken(ours_version_falls_back)
    negative['ours_valid_no_patch'] = broken(
        lambda r: r['ours', 'valid']['stages']['boot'].update(marker=['BASE_V1']))
    negative['ours_half_file_crash'] = broken(
        lambda r: r['ours', 'half_file']['stages']['boot'].update(process_exited_during_observation=True))
    negative['ours_bad_elf_no_crash'] = broken(
        lambda r: r['ours', 'bad_elf_type']['stages']['boot'].update(process_exited_during_observation=False))
    negative['ours_wrong_base_installed'] = broken(
        lambda r: r['ours', 'wrong_base']['stages']['boot'].update(
            updater_state={'patches/1/state.json': {'kind': 'Installed'}}))

    rows = {case: {'ours': outcome(reports['ours', case]['stages']),
                   'theirs': outcome(reports['theirs', case]['stages'])} for case in CASES}
    result = {'checks': checks, 'negative_controls': negative, 'rows': rows,
              'passed': all(checks.values()) and all(negative.values())}
    text = json.dumps(result, indent=2) + '\n'
    if args.out:
        args.out.write_text(text)
    print(json.dumps({'passed': result['passed'], 'checks': len(checks),
                      'failed': [k for k, v in checks.items() if not v],
                      'negative_controls': negative}, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
