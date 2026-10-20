#!/usr/bin/env python3
"""Formatting-only patches: reference toolchain vs ours, patch size per variant.

Question (operator, 2026-10-20): Shorebird turns formatting-only changes
(reformatting, line endings) into large patches. Does our toolchain produce
patches of the same size for the same formatting changes?

For one G3 app, starting from the G3 base source (BASE_V1 harness):
  1. reference release build (`flutter build ipa --release --no-codesign`,
     as shorebird_cli's buildIpa does) -> release App + release supplement
     (build/ios/shorebird/App.*), kept as the reference base;
  2. per variant: apply a formatting-only transform to the app's own
     lib/**/*.dart (the harness file excluded), then
       ref:  flutter build ipa -> app.dill + patch supplement; gen_snapshot
             ELF; release supplement next to the release App and patch
             supplement next to out.aot (shorebird_cli
             copySupplementFilesToSnapshotDirs); aot_tools link; dump_blobs;
             patch diff
       ours: our frontend_server -> dill; our gen_snapshot ELF; our
             analyze_snapshot; tools/linker.py against our G3 base; patch
             diff against our G3 diff_base
     then restore lib/ and verify every file's sha256 is back.
Builds run IN PLACE at the app's original path: kernel embeds file URIs, so
a copy at another path would change every script and swamp the measurement.

Usage: run.py <app> [variant ...]     (default: all variants)
Outputs under scratchpad/fmt_patch_20261020/<app>/; summary.json there.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
G3 = HERE.parent / 'g3_20261019'
PROJECT = HERE.parents[1]
REF = Path('/Users/Cruz/.shorebird/bin/cache/flutter/c2515c46c7fca511e39735a615f0f12f3dca6230')
REF_GEN = REF / 'bin/cache/artifacts/engine/ios-release/gen_snapshot_arm64'
REF_ANALYZE = REF / 'bin/cache/artifacts/engine/ios-release/analyze_snapshot_arm64'
REF_DART = REF / 'bin/cache/dart-sdk/bin/dart'
AOT_TOOLS = Path('/Users/Cruz/.shorebird/bin/cache/artifacts/aot-tools/a787a8fe98e99918255bb4bf4835f6ae010c1035/aot-tools.dill')
PATCH_TOOL = Path('/Users/Cruz/.shorebird/bin/cache/artifacts/patch/patch')
SDK = Path('/Users/Cruz/dart-3122/sdk')
FLUTTER = Path('/Users/Cruz/shorebird_engine/engine/src/flutter')
IOS = FLUTTER / 'engine/src/out/ios_release_ref'
HOST = FLUTTER / 'engine/src/out/host_release_ref'
OUR_GEN = IOS / 'clang_arm64/gen_snapshot_arm64'
OUR_ANALYZE = IOS / 'artifacts_arm64/analyze_snapshot_arm64'
SUPPLEMENT_NAMES = ('App.ct.link', 'App.class_table.json', 'App.ft.link', 'App.field_table.json',
                    'App.dt.link', 'App.dispatch_table.json', 'App.dd.link', 'App.dd_callers.link',
                    'App.dd_resolution.tsv')
HARNESS = 'g3_harness.dart'
# --split-debug-info mode (operator, 2026-10-20: "formatting must not produce
# a patch"). Mirrors shorebird_cli: `flutter build ipa --split-debug-info=D`,
# and ApplePatcherMixin.splitDebugInfoArgs passed to aot_tools link after
# `--` (--dwarf-stack-traces --resolve-dwarf-paths --save-debugging-info=...).
SPLIT = os.environ.get('FMT_SPLIT_DEBUG') == '1'
VARIANTS = ('nochange', 'comment_eof', 'trailing_space', 'blank_top_one', 'blank_top_all',
            'crlf', 'fmt_w40', 'logic')


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def run(name, args, cwd, out, env=None):
    t0 = time.monotonic()
    with (out / f'{name}.log').open('wb') as log:
        rc = subprocess.run([str(a) for a in args], cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                            env=env).returncode
    if rc:
        raise RuntimeError(f'{name} rc={rc}, see {out / (name + ".log")}')
    return round(time.monotonic() - t0, 1)


def app_dir(app):
    return G3 / 'apps' / ('localsend/app' if app == 'localsend' else app)


def lib_files(app):
    return sorted(p for p in (app_dir(app) / 'lib').rglob('*.dart') if p.name != HARNESS)


def snapshot_lib(app):
    return {str(p): sha(p) for p in sorted((app_dir(app) / 'lib').rglob('*')) if p.is_file()}


# ---- transforms: formatting only (plus `logic`, the G3 patch, for scale) ----

def t_nochange(app):
    return []


def _rewrite(files, fn):
    changed = []
    for p in files:
        b = p.read_bytes()
        nb = fn(p, b)
        if nb != b:
            p.write_bytes(nb)
            changed.append(p)
    return changed


def t_comment_eof(app):
    # Appended after all code: no existing token moves.
    return _rewrite(lib_files(app), lambda p, b: b + (b'' if b.endswith(b'\n') else b'\n') + b'// fmt\n')


def t_trailing_space(app):
    # Every line keeps its number; every token's character offset moves.
    return _rewrite(lib_files(app), lambda p, b: b.replace(b'\n', b' \n'))


def t_blank_top_one(app):
    main = app_dir(app) / 'lib/main.dart'
    return _rewrite([main], lambda p, b: b'\n' + b)


def t_blank_top_all(app):
    return _rewrite(lib_files(app), lambda p, b: b'\n' + b)


def t_crlf(app):
    return _rewrite(lib_files(app), lambda p, b: b.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))


def t_fmt_w40(app):
    files = lib_files(app)
    before = {p: p.read_bytes() for p in files}
    subprocess.run([str(REF_DART), 'format', '--page-width=40'] + [str(p) for p in files],
                   cwd=app_dir(app), check=True, capture_output=True)
    return [p for p in files if p.read_bytes() != before[p]]


def t_logic(app):
    h = app_dir(app) / 'lib' / HARNESS
    shutil.copyfile(G3 / 'g3_harness_patch.dart', h)
    return [h]


TRANSFORMS = {n: globals()['t_' + n] for n in VARIANTS}
# Repeats of the no-change build, to measure each toolchain's own build-to-build noise.
TRANSFORMS.update({'nochange_r2': t_nochange, 'nochange_r3': t_nochange})


# ---- reference side ----

def ref_build(app, out):
    """flutter build ipa --release --no-codesign; returns (App, app.dill, supplement dir)."""
    a = app_dir(app)
    start = time.time()
    extra = [f'--split-debug-info={out / "symbols"}'] if SPLIT else []
    # FMT_REF_BUILD=ios: `build ios` instead of shorebird_cli's `build ipa`.
    # LocalSend's Rust plugin makes the ipa archive step re-fetch the Rust
    # channel manifest (TLS handshake failure here); G3 built it with
    # `build ios`. The Dart side (app.dill, gen_snapshot, supplement) is the
    # same flutter_build path either way.
    kind = os.environ.get('FMT_REF_BUILD', 'ipa')
    secs = run(f'flutter_build_{kind}', [REF / 'bin/flutter', 'build', kind, '--release', '--no-codesign'] + extra, a, out)
    dills = sorted((a / '.dart_tool/flutter_build').glob('*/app.dill'), key=lambda p: p.stat().st_mtime)
    dill = dills[-1]
    fresh = dill.stat().st_mtime >= start
    app_bin = (a / 'build/ios/archive/Runner.xcarchive/Products/Applications/Runner.app/Frameworks/App.framework/App'
               if kind == 'ipa' else a / 'build/ios/iphoneos/Runner.app/Frameworks/App.framework/App')
    assert app_bin.is_file(), app_bin
    return app_bin, dill, a / 'build/ios/shorebird', secs, fresh


def ref_release(app, root):
    base = root / 'ref_release'
    if (base / 'done.json').is_file():
        return base
    base.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(G3 / 'g3_harness_base.dart', app_dir(app) / 'lib' / HARNESS)
    app_bin, dill, supp, secs, fresh = ref_build(app, base)
    fw = base / 'App.framework'
    fw.mkdir(exist_ok=True)
    shutil.copy2(app_bin, fw / 'App')
    shutil.copy2(dill, base / 'app.dill')
    copied = []
    for n in SUPPLEMENT_NAMES:
        if (supp / n).is_file():
            shutil.copy2(supp / n, fw / n)  # next to the release App, as shorebird_cli does
            copied.append(n)
    run('dump_blobs', [REF_DART, AOT_TOOLS, 'dump_blobs', f'--analyze-snapshot={REF_ANALYZE}',
                       f'--output={base / "diff_base"}', f'--snapshot={fw / "App"}'], base, base)
    (base / 'done.json').write_text(json.dumps({
        'app_sha256': sha(fw / 'App'), 'dill_sha256': sha(base / 'app.dill'),
        'supplement': copied, 'build_seconds': secs, 'dill_fresh': fresh}, indent=2) + '\n')
    return base


def ref_patch(app, release, out):
    app_bin, dill, supp, secs, fresh = ref_build(app, out)
    shutil.copy2(dill, out / 'app.dill')
    for n in SUPPLEMENT_NAMES:
        if (supp / n).is_file():
            shutil.copy2(supp / n, out / n.replace('App.', 'out.', 1))
    run('gen_patch_elf', [REF_GEN, '--deterministic', '--snapshot_kind=app-aot-elf',
                          f'--elf={out / "out.aot"}', out / 'app.dill'], out, out)
    run('aot_tools_link', [REF_DART, AOT_TOOLS, 'link', f'--base={release / "App.framework/App"}',
                           f'--patch={out / "out.aot"}', f'--analyze-snapshot={REF_ANALYZE}',
                           f'--gen-snapshot={REF_GEN}', f'--kernel={out / "app.dill"}',
                           f'--output={out / "out.vmcode"}', '--verbose', '--reporter=json',
                           f'--redirect-to={out / "link.jsonl"}']
        + (['--', '--dwarf-stack-traces', '--resolve-dwarf-paths',
            f'--save-debugging-info={out / "symbols" / "app.ios-arm64.symbols"}'] if SPLIT else []), out, out)
    run('patch_diff', [PATCH_TOOL, release / 'diff_base', out / 'out.vmcode', out / 'delta.patch'], out, out)
    link = [json.loads(l) for l in (out / 'link.jsonl').read_text().splitlines()
            if '"type":"link_success"' in l]
    return {'delta': (out / 'delta.patch').stat().st_size, 'vmcode': (out / 'out.vmcode').stat().st_size,
            'link_percentage': link[-1]['link_percentage'] if link else None,
            'link': link[-1] if link else None, 'dill_fresh': fresh, 'build_seconds': secs,
            'dill_sha256': sha(out / 'app.dill')}


# ---- our side ----

def our_packages(app, out):
    a = app_dir(app)
    pc = a / '.dart_tool/package_config.json'
    if not pc.is_file():
        pc = a.parent / '.dart_tool/package_config.json'
    pk = json.loads(pc.read_text())
    over = {'flutter': FLUTTER / 'packages/flutter', 'flutter_test': FLUTTER / 'packages/flutter_test',
            'flutter_localizations': FLUTTER / 'packages/flutter_localizations',
            'sky_engine': HOST / 'gen/dart-pkg/sky_engine'}
    for p in pk['packages']:
        p['rootUri'] = over[p['name']].as_uri() if p['name'] in over else urljoin(pc.as_uri(), p['rootUri'])
    dest = out / 'packages.json'
    dest.write_text(json.dumps(pk, indent=2) + '\n')
    return dest


DWARF = ['--dwarf-stack-traces', '--resolve-dwarf-paths']


def our_compile(app, out, name):
    """frontend_server -> dill -> ELF -> analyze, for the source currently in lib/."""
    a = app_dir(app)
    version = (IOS / 'clang_arm64/gen/flutter/third_party/dart/runtime/version.cc').read_text()
    sdk_hash = re.search(r'git_short_hash_\s*=\s*"([0-9a-f]+)"', version).group(1)
    frontend = [SDK / 'tools/sdks/dart-sdk/bin/dart', f'-Dsdk_hash={sdk_hash}',
                f'--packages={SDK / ".dart_tool/package_config.json"}',
                SDK / 'pkg/frontend_server/bin/frontend_server_starter.dart']
    pk = our_packages(app, out)
    run(f'frontend_{name}', frontend + ['--sdk-root', IOS / 'flutter_patched_sdk', '--target=flutter', '--aot',
                                        '--tfa', '--packages', pk, '-Ddart.vm.product=true',
                                        '-DG3_SERVER_PORT=18730', '--output-dill', out / f'{name}.dill',
                                        a / 'lib/main.dart'], a, out)
    dbg = [*DWARF, f'--save-debugging-info={out / (name + ".symbols")}'] if SPLIT else []
    run(f'elf_{name}', [OUR_GEN, '--deterministic', '--snapshot_kind=app-aot-elf', *dbg,
                        f'--elf={out / (name + ".aot")}', out / f'{name}.dill'], a, out)
    run(f'analyze_{name}', [OUR_ANALYZE, '--shorebird', f'--out={out / (name + ".json")}',
                            out / f'{name}.aot'], a, out)
    return dbg


def our_release(app, root):
    """Our base for SPLIT mode: same source as G3's base, compiled with the DWARF flags,
    turned into a Mach-O App exactly as G3 build_ours.py does, and its diff base dumped."""
    base = root / 'ours_release'
    if (base / 'done.json').is_file():
        return base
    base.mkdir(parents=True, exist_ok=True)
    dbg = our_compile(app, base, 'base')
    run('base_assembly', [OUR_GEN, '--deterministic', '--snapshot_kind=app-aot-assembly', *dbg,
                          f'--assembly={base / "base.S"}', base / 'base.dill'], app_dir(app), base)
    sdk_path = FLUTTER / 'engine/src/flutter/prebuilts/SDKs/iPhoneOS27.1.sdk'
    run('app_binary', ['xcrun', 'clang', '-x', 'assembler', '-miphoneos-version-min=15.0',
                       '-isysroot', sdk_path, '-arch', 'arm64', '-dynamiclib',
                       '-install_name', '@rpath/App.framework/App', '-o', base / 'App', base / 'base.S'],
        app_dir(app), base)
    run('dump_base_blob', [OUR_ANALYZE, '--dump_blobs', f'--out={base / "diff_base"}', base / 'App'],
        app_dir(app), base)
    (base / 'done.json').write_text(json.dumps({'app_sha256': sha(base / 'App')}, indent=2) + '\n')
    return base


def our_patch(app, out):
    a = app_dir(app)
    g3 = our_release(app, out.parents[1]) if SPLIT else G3 / 'work' / app / 'ours'
    if SPLIT:
        our_compile(app, out, 'patch')
        run('link', ['python3', PROJECT / 'tools/linker.py', f'--base={g3 / "base.aot"}',
                     f'--patch={out / "patch.aot"}', f'--base-json={g3 / "base.json"}',
                     f'--patch-json={out / "patch.json"}', f'--output={out / "out.vmcode"}', '--verbose'], a, out)
        run('patch_diff', [PATCH_TOOL, g3 / 'diff_base', out / 'out.vmcode', out / 'delta.patch'], a, out)
        m = re.search(r'Link percentage: ([0-9.]+)%', (out / 'link.log').read_text())
        return {'delta': (out / 'delta.patch').stat().st_size, 'vmcode': (out / 'out.vmcode').stat().st_size,
                'link_percentage': float(m.group(1)) if m else None, 'dill_sha256': sha(out / 'patch.dill')}
    version = (IOS / 'clang_arm64/gen/flutter/third_party/dart/runtime/version.cc').read_text()
    sdk_hash = re.search(r'git_short_hash_\s*=\s*"([0-9a-f]+)"', version).group(1)
    frontend = [SDK / 'tools/sdks/dart-sdk/bin/dart', f'-Dsdk_hash={sdk_hash}',
                f'--packages={SDK / ".dart_tool/package_config.json"}',
                SDK / 'pkg/frontend_server/bin/frontend_server_starter.dart']
    pk = our_packages(app, out)
    run('frontend', frontend + ['--sdk-root', IOS / 'flutter_patched_sdk', '--target=flutter', '--aot',
                                '--tfa', '--packages', pk, '-Ddart.vm.product=true',
                                '-DG3_SERVER_PORT=18730', '--output-dill', out / 'patch.dill',
                                a / 'lib/main.dart'], a, out)
    run('elf', [OUR_GEN, '--deterministic', '--snapshot_kind=app-aot-elf', f'--elf={out / "patch.aot"}',
                out / 'patch.dill'], a, out)
    run('analyze', [OUR_ANALYZE, '--shorebird', f'--out={out / "patch.json"}', out / 'patch.aot'], a, out)
    run('link', ['python3', PROJECT / 'tools/linker.py', f'--base={g3 / "base.aot"}',
                 f'--patch={out / "patch.aot"}', f'--base-json={g3 / "base.json"}',
                 f'--patch-json={out / "patch.json"}', f'--output={out / "out.vmcode"}', '--verbose'], a, out)
    run('patch_diff', [PATCH_TOOL, g3 / 'diff_base', out / 'out.vmcode', out / 'delta.patch'], a, out)
    m = re.search(r'Link percentage: ([0-9.]+)%', (out / 'link.log').read_text())
    return {'delta': (out / 'delta.patch').stat().st_size, 'vmcode': (out / 'out.vmcode').stat().st_size,
            'link_percentage': float(m.group(1)) if m else None, 'dill_sha256': sha(out / 'patch.dill')}


def restore_lib(app, backup, pristine):
    """Put every backed-up file back; refuse if any file was added or lost."""
    lib = app_dir(app) / 'lib'
    extra = [p for p in lib.rglob('*') if p.is_file() and not (backup / p.relative_to(lib)).is_file()]
    if extra:
        raise SystemExit(f'transform created files {extra[:3]} -- restore by hand from {backup}')
    for b in backup.rglob('*'):
        if b.is_file():
            dest = lib / b.relative_to(backup)
            if not dest.is_file() or dest.read_bytes() != b.read_bytes():
                dest.write_bytes(b.read_bytes())
    assert snapshot_lib(app) == pristine, 'lib/ not restored byte-identically'


def main():
    app = sys.argv[1]
    variants = sys.argv[2:] or list(VARIANTS)
    root = HERE / (app + ('_split' if SPLIT else ''))
    root.mkdir(parents=True, exist_ok=True)
    harness = app_dir(app) / 'lib' / HARNESS
    original_harness = harness.read_bytes()
    # Base state for every variant: G3 base source = current lib with the BASE_V1 harness.
    shutil.copyfile(G3 / 'g3_harness_base.dart', harness)
    pristine = snapshot_lib(app)
    backup = root / ('lib_backup_' + datetime.datetime.now().strftime('%Y%m%dT%H%M%S'))
    shutil.copytree(app_dir(app) / 'lib', backup)
    summary_path = root / 'summary.json'
    summary = json.loads(summary_path.read_text()) if summary_path.is_file() else {}
    try:
        release = ref_release(app, root)
        if SPLIT:
            our_release(app, root)
        summary['_ref_release'] = json.loads((release / 'done.json').read_text())
        for v in variants:
            out = root / v
            (out / 'ref').mkdir(parents=True, exist_ok=True)
            (out / 'ours').mkdir(parents=True, exist_ok=True)
            changed = TRANSFORMS[v](app)
            row = {'files_changed': len(changed),
                   'bytes_changed_files': sum(p.stat().st_size for p in changed),
                   'started': datetime.datetime.now().isoformat(timespec='seconds')}
            try:
                row['ref'] = ref_patch(app, release, out / 'ref')
                row['ours'] = our_patch(app, out / 'ours')
            except Exception as e:
                row['error'] = str(e)
            finally:
                restore_lib(app, backup, pristine)
            summary[v] = row
            summary_path.write_text(json.dumps(summary, indent=2) + '\n')
            r, o = row.get('ref', {}), row.get('ours', {})
            print(v, 'files', row['files_changed'], '| ref delta', r.get('delta'), 'link', r.get('link_percentage'),
                  '| ours delta', o.get('delta'), 'link', o.get('link_percentage'), row.get('error', ''), flush=True)
    finally:
        harness.write_bytes(original_harness)


if __name__ == '__main__':
    main()
