#!/usr/bin/env python3
"""Generate .dart_tool/package_config.json for kernel_linker without pub."""
import json
import os
import sys

def find_dart_sdk():
    candidates = [
        os.path.expanduser('~/dart/sdk'),
        '/usr/lib/dart',
    ]
    # Also check dart on PATH
    import shutil
    dart_bin = shutil.which('dart')
    if dart_bin:
        sdk = os.path.dirname(os.path.dirname(os.path.realpath(dart_bin)))
        candidates.insert(0, sdk)
    for c in candidates:
        if os.path.isdir(os.path.join(c, 'pkg', 'kernel')):
            return c
    return None

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--sdk', default=None)
    parsed, _ = parser.parse_known_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    sdk = parsed.sdk or os.environ.get('DART_SDK') or find_dart_sdk()
    if not sdk:
        print('ERROR: Cannot find Dart SDK. Set DART_SDK env var.', file=sys.stderr)
        sys.exit(1)
    print(f'Using Dart SDK: {sdk}')

    out_dir = os.path.join(script_dir, '.dart_tool')
    os.makedirs(out_dir, exist_ok=True)

    config = {
        'configVersion': 2,
        'packages': [
            {
                'name': 'kernel_linker',
                'rootUri': '../',
                'packageUri': 'lib/',
                'languageVersion': '3.3',
            },
            {
                'name': 'kernel',
                'rootUri': f'file://{sdk}/pkg/kernel/',
                'packageUri': 'lib/',
                'languageVersion': '3.3',
            },
            {
                'name': '_fe_analyzer_shared',
                'rootUri': f'file://{sdk}/pkg/_fe_analyzer_shared/',
                'packageUri': 'lib/',
                'languageVersion': '3.3',
            },
        ],
        'generated': '2026-07-31T00:00:00.000Z',
        'generator': 'gen_package_config.py',
        'generatorVersion': '3.0.0',
    }

    out_path = os.path.join(out_dir, 'package_config.json')
    with open(out_path, 'w') as f:
        json.dump(config, f, indent=2)
    print(f'Written: {out_path}')

if __name__ == '__main__':
    main()
