#!/usr/bin/env python3
"""Audit the isolated iPhone G4 runs and emit a content-free summary."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--work', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    args = ap.parse_args()
    work = args.work
    checks = []

    def check(label, condition):
        checks.append({'name': label, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(label)

    def read(side, case, revision):
        return json.loads((work / 'runs' / f'{side}_{case}_{revision}' / 'report.json').read_text())

    def patch_kind(stage):
        return stage['updater_state'].get('patches/1/state.json', {}).get('kind')

    def status(stage):
        updates = stage['update']
        return updates[0].split(' ', 1)[0] if updates else None

    ours_manifest = json.loads((work / 'manifest_v6.json').read_text())
    reference_manifest = json.loads((work / 'manifest.json').read_text())
    framework_hashes = {
        'ours': ours_manifest['staged_framework_sha256'],
        'theirs': reference_manifest['sides']['theirs']['signed_framework_sha256'],
    }
    app_hashes = {
        'ours': ours_manifest['app_binary_sha256'],
        'theirs': sha(work / 'theirs/Runner.app/Frameworks/App.framework/App'),
    }
    rows = []
    revisions = {'ours': {'valid': 'v6', 'bad_elf_type': 'v6', 'bad_version': 'v6',
                          'wrong_base': 'v6', 'bad_signature': 'v6', 'half_file': 'v6'},
                 'theirs': {'valid': 'v2', 'bad_elf_type': 'v2', 'bad_version': 'v5',
                            'wrong_base': 'v2', 'bad_signature': 'v2', 'half_file': 'v2'}}
    for side, cases in revisions.items():
        for case, revision in cases.items():
            report = read(side, case, revision)
            stages = report['stages']
            prefix = f'{side}_{case}_{revision}'
            check(prefix + '_baseline', stages['baseline']['marker'] == ['BASE_V1'] and
                  status(stages['baseline']) == 'status=0' and
                  not stages['baseline']['process_exited_during_observation'])
            check(prefix + '_recorded', report['status'] == 'RECORDED')
            installed_app = work / 'runs' / prefix / 'Runner.app/Frameworks'
            check(prefix + '_framework_identity',
                  sha(installed_app / 'Flutter.framework/Flutter') == framework_hashes[side])
            check(prefix + '_app_identity',
                  sha(installed_app / 'App.framework/App') == app_hashes[side])
            inputs = report['inputs']
            check(prefix + '_delta_hash', sha(Path(inputs['delta'])) == inputs['delta_sha256'])
            check(prefix + '_control_hash', sha(Path(inputs['control'])) == inputs['control_sha256'])
            check(prefix + '_vmcode_hash', sha(work / side /
                  ('cases_v5' if revision in ('v5', 'v6') else 'cases_v2') /
                  f'{case}.vmcode') == inputs['payload_sha256'])
            boot = stages['boot']
            rows.append({'side': side, 'case': case, 'revision': revision,
                         'download_status': status(stages['download']),
                         'boot_marker': boot['marker'],
                         'boot_exited': boot['process_exited_during_observation'],
                         'boot_patch_state': patch_kind(boot),
                         'boot_observation_seconds': boot['elapsed_seconds'],
                         'recovery_marker': stages.get('recovery', {}).get('marker'),
                         'recovery_patch_state': patch_kind(stages['recovery'])
                         if 'recovery' in stages else None,
                         'payload_sha256': inputs['payload_sha256'],
                         'delta_sha256': inputs['delta_sha256'],
                         'base_blob_sha256': inputs['base_blob_sha256'],
                         'control_sha256': inputs['control_sha256']})
            if case == 'valid':
                check(prefix + '_positive', status(stages['download']) == 'status=1' and
                      boot['marker'] == ['PATCH_V2'] and
                      not boot['process_exited_during_observation'])
            elif side == 'ours':
                check(prefix + '_clean_fallback', boot['marker'] == ['BASE_V1'] and
                      patch_kind(boot) == 'Bad' and
                      not boot['process_exited_during_observation'])
            elif case == 'bad_elf_type':
                recovery = stages['recovery']
                check(prefix + '_reference_recovery', boot['process_exited_during_observation'] and
                      recovery['marker'] == ['BASE_V1'] and patch_kind(recovery) == 'Bad')
            elif case == 'bad_version':
                recovery = stages['recovery']
                check(prefix + '_reference_no_marker', boot['marker'] == [] and
                      recovery['marker'] == [] and boot['elapsed_seconds'] >= 15 and
                      recovery['elapsed_seconds'] >= 15 and
                      not boot['process_exited_during_observation'] and
                      patch_kind(recovery) == 'Installed')
            else:
                check(prefix + '_reference_fallback', boot['marker'] == ['BASE_V1'] and
                      patch_kind(boot) == 'Bad' and
                      not boot['process_exited_during_observation'])

    for side in ('ours', 'theirs'):
        cases = work / side / 'cases_v5'
        valid = (cases / 'valid.vmcode').read_bytes()
        changed = (cases / 'bad_version.vmcode').read_bytes()
        differences = [i for i, (a, b) in enumerate(zip(valid, changed)) if a != b]
        check(side + '_version_single_ascii_hex_digit', len(valid) == len(changed) and
              len(differences) == 1 and
              chr(valid[differences[0]]) in '0123456789abcdef' and
              chr(changed[differences[0]]) in '0123456789abcdef')

    cleanup = json.loads((work / 'cleanup_g4_apps_report.json').read_text())
    check('device_cleanup', cleanup['remaining_g4_bundles'] == [] and
          cleanup['original_b5_present'] and
          all(row['returncode'] == 0 for row in cleanup['runs']))
    out = {'verdict': 'G4-03 device evidence complete; two scoped reference defects',
           'checks': checks, 'check_count': len(checks), 'rows': rows,
           'binary_identity': {'framework_sha256': framework_hashes,
                               'app_macho_sha256': app_hashes},
           'cleanup': {'g4_remaining': cleanup['remaining_g4_bundles'],
                       'original_b5_present': cleanup['original_b5_present']},
           'limitations': ['Reference bad ELF crashes on its first patched boot, then recovers.',
                           'Reference valid-ASCII bad version produced no app marker within two 15-second observations; no indefinite-hang claim.',
                           'The ours build uses dart_force_simulator=true; native-mode G3 remains separate.']}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + '\n')
    print('G4_DEVICE_AUDIT_PASS', len(checks), flush=True)


if __name__ == '__main__':
    main()
