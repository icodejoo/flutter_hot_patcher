#!/usr/bin/env python3
"""Device check for the --split-debug-info fix (our toolchain, Wonderous, QA iPhone only).

Stages G3's reference-built Runner.app shell with our Flutter runtime and our
split-mode base App (wonderous_split/ours_release/App), signs it exactly as
G3 stage_device.py does, and runs G3 run_device.py's launch/push/observe
sequence once per patch:
  fmt_w40 -- formatting-only patch: expect BASE_V1 logic=23 on the patched
             boot AND updater state Installed (the patch booted, behaviour
             unchanged)
  logic   -- G3's logic patch: expect PATCH_V2 logic=23->33 and Installed
Each patch gets a fresh install (uninstall before and after). Reports under
wonderous_split/device/<patch>/report.json.
"""
import base64
import os
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
G3 = HERE.parent / 'g3_20261019'
sys.path.insert(0, str(G3))
import run_device as RD      # noqa: E402  launch/call/dev/sha, DEVICE, BUNDLE, PORT
import stage_device as SD    # noqa: E402  run/entitlements, SIGN, ENGINE, G4

APP = sys.argv[1] if len(sys.argv) > 1 else 'wonderous'
SPLIT = HERE / f'{APP}_split'
# PATCH_SRC=strip_test: use the --strip patch ELFs (SPLIT/strip_test/<name>/).
PATCH_SRC = os.environ.get('PATCH_SRC', '')
EXPECT = {'fmt_w40': 'BASE_V1 logic=23', 'logic': 'PATCH_V2 logic=33'}


def stage(out):
    staged = out / 'Runner.app'
    assert not staged.exists(), staged
    SD.run('copy_shell', ['ditto', G3 / f'work/{APP}/ref/base/Runner.app', staged], out)
    shutil.copy2(SD.ENGINE / 'Flutter.framework/Flutter', staged / 'Frameworks/Flutter.framework/Flutter')
    shutil.copy2(SPLIT / 'ours_release/App', staged / 'Frameworks/App.framework/App')
    import plistlib, uuid
    info_file = staged / 'Info.plist'
    info = plistlib.loads(info_file.read_bytes())
    info.update(CFBundleIdentifier=SD.BUNDLE, CFBundleDisplayName=f'FMT split {APP}',
                NSLocalNetworkUsageDescription='Local QA patch fixture',
                NSAppTransportSecurity={'NSAllowsArbitraryLoads': True})
    info_file.write_bytes(plistlib.dumps(info))
    app_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'fhp-fmt-split-20261020-{APP}-ours'))
    private = HERE.parents[1] / 'scratchpad/g4_rerun_20261019/device/test_private.pem'
    public = subprocess.run(['openssl', 'rsa', '-in', str(private), '-RSAPublicKey_out', '-outform', 'DER'],
                            capture_output=True, check=True).stdout
    (staged / 'Frameworks/App.framework/flutter_assets/shorebird.yaml').write_text(
        f'app_id: {app_id}\nchannel: stable\nbase_url: http://127.0.0.1:{SD.PORT}\n'
        'auto_update: false\npatch_verification: strict\n'
        f'patch_public_key: {base64.b64encode(public).decode()}\n')
    profile = SD.G4 / 'Runner.app/embedded.mobileprovision'
    shutil.copy2(profile, staged / 'embedded.mobileprovision')
    for ext in staged.rglob('*.appex'):
        v = plistlib.loads((ext / 'Info.plist').read_bytes())
        v['CFBundleIdentifier'] = f'{SD.BUNDLE}.{ext.stem}'
        (ext / 'Info.plist').write_bytes(plistlib.dumps(v))
        shutil.copy2(profile, ext / 'embedded.mobileprovision')
    for fw in sorted(staged.rglob('*.framework'), key=lambda p: -len(p.parts)):
        SD.run(f'sign_framework_{fw.stem}', ['codesign', '--force', '--sign', SD.SIGN, '--timestamp=none', fw], out)
    for dylib in sorted(staged.rglob('*.dylib')):
        if '.framework/' not in str(dylib):
            SD.run(f'sign_dylib_{dylib.stem}', ['codesign', '--force', '--sign', SD.SIGN, '--timestamp=none', dylib], out)
    for ext in sorted(staged.rglob('*.appex'), key=lambda p: -len(p.parts)):
        SD.run(f'sign_extension_{ext.stem}', ['codesign', '--force', '--sign', SD.SIGN, '--timestamp=none',
                                              '--entitlements', SD.entitlements(f'{SD.BUNDLE}.{ext.stem}', out), ext], out)
    SD.run('sign_runner', ['codesign', '--force', '--sign', SD.SIGN, '--timestamp=none',
                           '--entitlements', SD.entitlements(SD.BUNDLE, out), staged], out)
    SD.run('verify_sign', ['codesign', '--verify', '--deep', '--strict', staged], out)
    return staged, {'app_sha256': RD.sha(staged / 'Frameworks/App.framework/App'),
                    'split_base_app_sha256': RD.sha(SPLIT / 'ours_release/App'),
                    'engine_sha256': RD.sha(staged / 'Frameworks/Flutter.framework/Flutter')}


def run_patch(staged, name, out):
    out.mkdir(parents=True, exist_ok=False)
    src = SPLIT / PATCH_SRC / name if PATCH_SRC else SPLIT / name / 'ours'
    delta = src / 'delta.patch'
    vmcode = src / 'out.vmcode'
    report = {'patch': name, 'device_udid': RD.DEVICE, 'expect_boot_marker': EXPECT[name],
              'delta_bytes': delta.stat().st_size, 'delta_sha256': RD.sha(delta), 'vmcode_sha256': RD.sha(vmcode),
              'started_utc': datetime.now(timezone.utc).isoformat(), 'stages': {}}
    path = out / 'report.json'
    save = lambda: path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    save()
    try:
        RD.call('uninstall_before', RD.dev('uninstall', 'app', RD.BUNDLE), out)
        report['install_rc'] = RD.call('install', RD.dev('install', 'app', staged), out, timeout=180)
        save()
        if report['install_rc']:
            raise RuntimeError('install failed')
        report['stages']['baseline'] = b = RD.launch('baseline', out)
        save()
        if not any('BASE_V1 logic=23' in m for m in b['marker']) or b['process_exited_during_observation']:
            report['status'] = 'BASELINE_FAILED'
            return report
        private = HERE.parents[1] / 'scratchpad/g4_rerun_20261019/device/test_private.pem'
        sig = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', str(private)],
                             input=RD.sha(vmcode).encode(), capture_output=True, check=True).stdout
        control = {'payload': 'payload.bin', 'patch': {
            'number': 1, 'hash': RD.sha(vmcode), 'hash_signature': base64.b64encode(sig).decode(),
            'download_url': f'http://127.0.0.1:{RD.PORT}/payload.bin'}}
        (out / 'control.json').write_text(json.dumps(control, indent=2) + '\n')
        for label, src, dest in [('payload', delta, 'Documents/g3/payload.bin'),
                                 ('control', out / 'control.json', 'Documents/g3/control.json')]:
            rc = RD.call(f'push_{label}', RD.dev('copy', 'to', '--domain-type', 'appDataContainer',
                                                 '--domain-identifier', RD.BUNDLE, '--source', src,
                                                 '--destination', dest), out)
            if rc:
                raise RuntimeError(f'push_{label} failed')
        report['stages']['download'] = d = RD.launch('download', out)
        save()
        report['stages']['boot'] = bt = RD.launch('boot', out)
        save()
        kind = bt['updater_state'].get('patches/1/state.json', {}).get('kind')
        report['boot_patch_state'] = kind
        report['status'] = ('PASS' if any('status=1' in u for u in d['update'])
                            and any(EXPECT[name] in m for m in bt['marker'])
                            and kind == 'Installed'
                            and not d['process_exited_during_observation']
                            and not bt['process_exited_during_observation'] else 'FAIL')
    finally:
        report['uninstall_after_rc'] = RD.call('uninstall_after', RD.dev('uninstall', 'app', RD.BUNDLE), out)
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        save()
    return report


def main():
    root = SPLIT / ('device_' + PATCH_SRC if PATCH_SRC else 'device')
    root.mkdir(exist_ok=True)
    staged, ident = stage(root)
    (root / 'stage.json').write_text(json.dumps(ident, indent=2) + '\n')
    for name in ('fmt_w40', 'logic'):
        r = run_patch(staged, name, root / name)
        print(name, r['status'], 'delta', r['delta_bytes'], 'boot markers', r['stages'].get('boot', {}).get('marker'),
              'state', r.get('boot_patch_state'), flush=True)


if __name__ == '__main__':
    main()
