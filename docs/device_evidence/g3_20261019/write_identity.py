#!/usr/bin/env python3
"""Record exact local source/tool/device identities without storing binaries."""

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SDK = Path('/Users/Cruz/dart-3122/sdk')
FLUTTER = Path('/Users/Cruz/shorebird_engine/engine/src/flutter')
ENGINE = FLUTTER / 'engine/src/out/ios_release_ref'
REF = Path('/Users/Cruz/.shorebird/bin/cache/flutter/c2515c46c7fca511e39735a615f0f12f3dca6230')
WORK = ROOT / 'scratchpad/g3_20261019'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def git(tree, *args):
    return subprocess.run(['git', '-C', str(tree), *args], capture_output=True,
                          text=True, check=True).stdout.strip()

inventory = json.loads((WORK / 'device_inventory.json').read_text())
qa = [d for d in inventory['result']['devices']
      if d.get('hardwareProperties', {}).get('udid') == '00008110-000E583836F3601E']
assert len(qa) == 1
device = qa[0]
identity = {
    'sdk_head': git(SDK, 'rev-parse', 'HEAD'),
    'sdk_worktree_clean': not git(SDK, 'status', '--porcelain=v1'),
    'engine_head': git(FLUTTER, 'rev-parse', 'HEAD'),
    'engine_tracked_changes': git(FLUTTER, 'status', '--porcelain=v1', '-uno'),
    'pause_present': (ROOT / '.loop/PAUSE').is_file(),
    'bingoplus_source_head': git('/Users/Cruz/Projects/bingoplus_native', 'rev-parse', 'HEAD'),
    'device': {'name': device['deviceProperties']['name'],
               'ios_version': device['deviceProperties']['osVersionNumber'],
               'model': device['hardwareProperties']['marketingName'],
               'udid': device['hardwareProperties']['udid']},
    'sha256': {
        'ours_gen_snapshot': sha(ENGINE / 'clang_arm64/gen_snapshot_arm64'),
        'ours_analyze_snapshot': sha(ENGINE / 'artifacts_arm64/analyze_snapshot_arm64'),
        'ours_flutter_runtime': sha(ENGINE / 'Flutter.framework/Flutter'),
        'sdk_pinned_gen_snapshot': sha(SDK / 'xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot'),
        'ref_gen_snapshot': sha(REF / 'bin/cache/artifacts/engine/ios-release/gen_snapshot_arm64'),
        'ref_analyze_snapshot': sha(REF / 'bin/cache/artifacts/engine/ios-release/analyze_snapshot_arm64'),
        'harness_base': sha(WORK / 'g3_harness_base.dart'),
        'harness_patch': sha(WORK / 'g3_harness_patch.dart'),
    },
}
out = Path(__file__).with_name('identity.json')
out.write_text(json.dumps(identity, indent=2, ensure_ascii=False) + '\n')
print(json.dumps(identity, indent=2, ensure_ascii=False))
