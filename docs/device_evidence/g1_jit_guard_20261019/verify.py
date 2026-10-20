#!/usr/bin/env python3
"""Read-only check of the G1 JIT snapshot fix and AOT regression artifacts."""

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK = Path('/Users/Cruz/dart-3122/sdk')
DATA = ROOT / 'scratchpad/g1_jit_guard_20261019'
EXPECTED_PATCH = '3c320a13c69497f6e8b77b2ed60986fc46331523516c25c758ffdfbd8d2db159'
EXPECTED_BINARIES = {
    'xcodebuild/DebugARM64/dartvm': '688bc1f42d3e9a9cd538d863a400021e42457ac9d667177140f60cd725c567b0',
    'xcodebuild/DebugARM64/dart': 'c3652208202a4f7fe9e2673a482c8a69d9fc64056f426ced1c73a2fbbf31a16b',
    'xcodebuild/DebugARM64/run_vm_tests': 'f033d1d576e8dacca1a0ce3ab2fc9f74ad6533cc3e5c4e3b29b27e89026757a9',
    'xcodebuild/ProductSimIosARM64/clang_arm64/gen_snapshot': 'a65156713bf75450a365259b1de786aa84e7c7d64fb1ac208957141e8d63e157',
    'xcodebuild/ProductSimIosARM64/clang_arm64/analyze_snapshot': '79bbdd5d66a540eacacd4ec101fcbf9fce0ae76d5f127f060ef4c12c1fd019a1',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def check():
    patch = subprocess.check_output(['git', 'diff'], cwd=SDK)
    assert sha(patch) == EXPECTED_PATCH
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                   cwd=SDK).decode().strip() == \
        '8367f9e0ca624cb8d2cc02ce2f38d677a3f1bdf0'
    assert (ROOT / '.loop/PAUSE').exists()
    for name, expected in EXPECTED_BINARIES.items():
        assert sha((SDK / name).read_bytes()) == expected

    jit = (DATA / 'hello.after.jit').read_bytes()
    marker = b'shorebird-native-entry-thr-offsets=2312,2320,2328'
    assert marker in jit
    assert (DATA / 'hello.generate.stdout').read_bytes() == b'jit guard ok\n'
    assert (DATA / 'hello.load.stdout').read_bytes() == b'jit guard ok\n'
    assert not (DATA / 'hello.generate.stderr').read_bytes()
    assert not (DATA / 'hello.load.stderr').read_bytes()

    tests = json.loads((DATA / 'focused_tests.json').read_text())
    assert len(tests) == 8
    for row in tests:
        log = (DATA / f"test_{row['test']}.log").read_bytes()
        assert row['rc'] == 0 and sha(log) == row['output_sha256']
        assert b'Running test:' in log and b'Done:' in log
        assert b'error:' not in log

    assert (DATA / 'hello.final.text').read_bytes() == \
        (DATA / 'hello.text.old').read_bytes()
    current = (DATA / 'hello.final.rodata').read_bytes()
    previous = (DATA / 'hello.rodata.old').read_bytes()
    assert len(current) == len(previous) == 302624
    changed = [i for i, (a, b) in enumerate(zip(current, previous)) if a != b]
    assert changed == list(range(20, 52)) + list(range(35348, 35380))
    assert current[20:52] == current[35348:35380]
    assert previous[20:52] == previous[35348:35380]
    analyzed = json.loads((DATA / 'hello.final.shorebird.json').read_text())
    baseline = json.loads((ROOT / 'scratchpad/g1_current_20261019/hello/shorebird.json').read_text())
    old_header = baseline['snapshot_data']
    new_header = analyzed['snapshot_data']
    assert old_header['snapshot_version'] != new_header['snapshot_version']
    assert old_header['vm_data_hash'] != new_header['vm_data_hash']
    old_header['snapshot_version'] = new_header['snapshot_version']
    old_header['vm_data_hash'] = new_header['vm_data_hash']
    assert baseline == analyzed
    return {'passed': True, 'focused_tests': len(tests),
            'jit_snapshot_sha256': sha(jit),
            'aot_text_sha256': sha((DATA / 'hello.final.text').read_bytes()),
            'aot_rodata_changed_bytes': len(changed),
            'aot_rodata_changed_fields': 'two 32-byte snapshot version hashes',
            'analyzer_json_changed_fields': ['snapshot_version', 'vm_data_hash']}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
