#!/usr/bin/env python3
"""Read-only G3 audit over local build manifests and QA device reports."""

import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
WORK = ROOT / 'scratchpad/g3_20261019'
APPS = ('wonderous', 'localsend', 'bingoplus')
SIDES = ('ref', 'ours')
RUN_ID = {('wonderous', 'ref'): 'run2', ('wonderous', 'ours'): 'run4'}
DEVICE = '00008110-000E583836F3601E'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def macho_text_sha(path):
    lines = subprocess.run(['otool', '-l', str(path)], capture_output=True,
                           text=True, check=True).stdout.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != 'sectname __text' or lines[index + 1].strip() != 'segname __TEXT':
            continue
        fields = {parts[0]: parts[-1] for entry in lines[index + 2:index + 9]
                  if (parts := entry.split()) and parts[0] in ('size', 'offset')}
        size, offset = int(fields['size'], 16), int(fields['offset'])
        data = Path(path).read_bytes()
        assert offset + size <= len(data)
        return hashlib.sha256(data[offset:offset + size]).hexdigest()
    raise ValueError(f'__TEXT,__text missing: {path}')

def load():
    reports = {}
    for app in APPS:
        for side in SIDES:
            run = RUN_ID.get((app, side), 'run')
            path = WORK / 'work' / app / side / 'device' / run / 'report.json'
            reports[(app, side)] = json.loads(path.read_text())
    return reports

def assess(reports, files=True):
    checks = {}
    percentages = {}
    for app in APPS:
        base = WORK / 'work' / app
        ref_link = [json.loads(line) for line in (base / 'ref/patch/link.jsonl').read_text().splitlines()
                    if '"type":"link_success"' in line]
        ours_match = re.search(r'Link percentage: ([0-9.]+)%', (base / 'ours/link.log').read_text())
        percentages[app] = {'ref': ref_link[-1]['link_percentage'] if ref_link else None,
                            'ours': float(ours_match.group(1)) if ours_match else None}
        checks[f'{app}:link_percentages'] = all(v is not None and 0 <= v <= 100
                                                for v in percentages[app].values())
        base_source = (WORK / 'g3_harness_base.dart').read_text()
        patch_source = (WORK / 'g3_harness_patch.dart').read_text()
        checks[f'{app}:source_delta'] = (patch_source == base_source.replace(
            'BASE_V1', 'PATCH_V2').replace('sum + value * 2 + 1', 'sum + value * 3 + 1'))
        for side in SIDES:
            report = reports[app, side]
            prefix = f'{app}:{side}'
            stages = report.get('stages', {})
            checks[prefix + ':device'] = report.get('device_udid') == DEVICE
            checks[prefix + ':install_cleanup'] = (report.get('install_rc') == 0 and
                                                   report.get('uninstall_after_rc') == 0)
            checks[prefix + ':declared_pass'] = report.get('status') == 'PASS'
            checks[prefix + ':stages'] = set(stages) == {'baseline', 'download', 'boot'}
            if not checks[prefix + ':stages']:
                continue
            initial, download, boot = (stages[k] for k in ('baseline', 'download', 'boot'))
            checks[prefix + ':markers'] = (initial.get('marker') == ['BASE_V1 logic=23'] and
                                            download.get('marker') == ['BASE_V1 logic=23'] and
                                            boot.get('marker') == ['PATCH_V2 logic=33'])
            checks[prefix + ':updates'] = (any('status=0' in x for x in initial.get('update', [])) and
                                            any('status=1' in x for x in download.get('update', [])))
            checks[prefix + ':installed'] = (boot.get('updater_state', {})
                                              .get('patches/1/state.json', {}).get('kind') == 'Installed')
            checks[prefix + ':survival'] = all(not stage.get('process_exited_during_observation')
                                                for stage in (initial, download, boot))
            checks[prefix + ':symmetric_windows'] = all(
                29.9 <= stage.get('elapsed_seconds', -1) <= 32
                for stage in (initial, download, boot)) and report.get('window_seconds') == 30
            checks[prefix + ':state_copies'] = all(stage.get('state_copy_rc') == 0
                                                    for stage in (initial, download, boot))
            if files:
                manifest = json.loads((base / side / 'device/manifest.json').read_text())
                app_binary = base / side / 'device/Runner.app/Frameworks/App.framework/App'
                framework = base / side / 'device/Runner.app/Frameworks/Flutter.framework/Flutter'
                config = (base / side / 'device/Runner.app/Frameworks/App.framework/'
                          'flutter_assets/shorebird.yaml').read_text()
                checks[prefix + ':local_updater_config'] = (
                    f'app_id: {manifest["app_id"]}' in config and
                    'base_url: http://127.0.0.1:18730' in config and
                    'auto_update: false' in config and
                    'patch_verification: strict' in config)
                checks[prefix + ':staged_hashes'] = (sha(app_binary) == manifest['app_binary_sha256'] and
                                                     sha(framework) == manifest['engine_binary_sha256'])
                if side == 'ours':
                    engine = Path('/Users/Cruz/shorebird_engine/engine/src/flutter/engine/src/out/'
                                  'ios_release_ref/Flutter.framework/Flutter')
                    checks[prefix + ':engine_text_identity'] = (
                        macho_text_sha(framework) == macho_text_sha(engine))
                build_manifest_path = (base / 'ref/patch/build_manifest.json' if side == 'ref'
                                       else base / 'ours/build_manifest.json')
                build_manifest = json.loads(build_manifest_path.read_text())
                checks[prefix + ':build_hashes'] = all(
                    sha(row['path']) == row['sha256'] and Path(row['path']).stat().st_size == row['size']
                    for row in build_manifest.values())
                delta = base / side / ('patch/delta.patch' if side == 'ref' else 'delta.patch')
                vmcode = base / side / ('patch/out.vmcode' if side == 'ref' else 'out.vmcode')
                checks[prefix + ':device_payload_hashes'] = (
                    report.get('payload_sha256') == sha(delta) and
                    report.get('vmcode_sha256') == sha(vmcode))
                if side == 'ours':
                    blobs = [base / 'ours' / name for name in
                             ('diff_base', 'corrected_base.blob', 'reference_analyzer_base.blob',
                              'independent_macho_base.blob')]
                    checks[prefix + ':base_three_way'] = len({sha(x) for x in blobs}) == 1
    return checks, percentages

def main():
    reports = load()
    checks, percentages = assess(reports)
    controls = {}
    def corrupt(name, app, side, path, value):
        bad = copy.deepcopy(reports)
        target = bad[app, side]
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        result, _ = assess(bad, files=False)
        controls[name] = [key for key, passed in result.items() if not passed]
    corrupt('wrong_boot_marker', 'wonderous', 'ref',
            ['stages', 'boot', 'marker'], ['BASE_V1 logic=23'])
    corrupt('bad_patch_state', 'localsend', 'ours',
            ['stages', 'boot', 'updater_state', 'patches/1/state.json', 'kind'], 'Bad')
    corrupt('short_observation', 'bingoplus', 'ref',
            ['stages', 'boot', 'elapsed_seconds'], 1.0)
    corrupt('wrong_device', 'bingoplus', 'ours', ['device_udid'], 'personal-phone')
    result = {'status': 'PASS' if all(checks.values()) and all(controls.values()) else 'FAIL',
              'checks_passed': sum(checks.values()), 'checks_total': len(checks),
              'failed_checks': [key for key, passed in checks.items() if not passed],
              'link_percentages': percentages,
              'negative_controls': controls}
    out = Path(__file__).with_name('audit.json')
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result['status'] == 'PASS' else 1

if __name__ == '__main__':
    raise SystemExit(main())
