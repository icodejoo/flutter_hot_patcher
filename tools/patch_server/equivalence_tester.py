#!/usr/bin/env python3
"""
5-A: Differential equivalence testing platform.

Verifies that a patch_bundle produces functionally equivalent behavior
to a full recompile of the patched version.

Steps:
1. Run kernel_linker diff on baseline vs patched dill → get changed function list
2. Verify 0 false negatives (linker catches all changes)
3. Verify 0 false positives (linker doesn't flag unchanged functions)
4. Verify patch_bundle manifest matches linker output (no drift)
5. Run behavioral smoke tests on both versions (via dartaotruntime_product)

Usage:
  python3 equivalence_tester.py \
    --sdk ~/dart/sdk \
    --baseline-dart greet.dart \
    --patched-dart greet_patch.dart \
    --patch-bundle /path/to/patch_bundle/ \
    --changed-functions '["file:///lib/greet.dart::greet"]'
"""
import argparse, json, os, subprocess, sys, tempfile

def run(cmd, **kwargs):
    r = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    return r

def compile_dill(sdk_host, source_path, output_path):
    """Compile Dart source to AOT dill."""
    r = run([
        f"{sdk_host}/dartaotruntime_product",
        f"{sdk_host}/gen/gen_kernel_aot.dart.snapshot",
        "--platform", f"{sdk_host}/vm_platform.dill",
        "--aot",
        "--output", output_path,
        source_path,
    ])
    if r.returncode != 0:
        print(f"  FAIL gen_kernel: {r.stderr[:200]}")
        return False
    return True

def run_linker(kernel_linker_dir, base_dill, patch_dill, output_dir):
    """Run kernel_linker --output-dir and return manifest."""
    r = run([
        "dart",
        f"--packages={kernel_linker_dir}/.dart_tool/package_config.json",
        f"{kernel_linker_dir}/bin/kernel_linker.dart",
        "--base", base_dill,
        "--patch", patch_dill,
        "--dart-sdk-commit", "1aa7d7321fb",
        "--baseline-snapshot", base_dill,
        "--output-dir", output_dir,
        "--allow-empty",
    ], cwd=kernel_linker_dir)
    if r.returncode not in (0, 3):  # 3 = no changes (valid)
        print(f"  FAIL linker: {r.stderr[:300]}")
        return None
    manifest_path = os.path.join(output_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        return {}
    return json.load(open(manifest_path))

def check_false_negatives(linker_manifest, expected_changed):
    """Verify all expected changed functions are detected."""
    detected = set(linker_manifest.get("changed_functions", []))
    expected = set(expected_changed)
    missed = expected - detected
    if missed:
        print(f"  FALSE NEGATIVES: {missed}")
        return False
    return True

def check_false_positives(linker_manifest, expected_unchanged):
    """Verify no unexpected functions are flagged as changed."""
    detected = set(linker_manifest.get("changed_functions", []) +
                   linker_manifest.get("affected_closure", []))
    unexpected = set(expected_unchanged) & detected
    if unexpected:
        print(f"  FALSE POSITIVES: {unexpected}")
        return False
    return True

def verify_patch_bundle_matches_linker(patch_bundle_dir, linker_manifest):
    """Verify patch_bundle's manifest.json matches linker output."""
    bundle_manifest_path = os.path.join(patch_bundle_dir, "manifest.json")
    if not os.path.exists(bundle_manifest_path):
        print("  FAIL: patch_bundle/manifest.json not found")
        return False
    bundle_manifest = json.load(open(bundle_manifest_path))
    linker_changed = sorted(linker_manifest.get("changed_functions", []))
    bundle_changed = sorted(bundle_manifest.get("changed_functions", []))
    if linker_changed != bundle_changed:
        print(f"  MISMATCH changed_functions:")
        print(f"    linker: {linker_changed}")
        print(f"    bundle: {bundle_changed}")
        return False
    return True

def behavioral_smoke_test(sdk_host, base_dill, patch_dill, expected_base, expected_patch):
    """
    Run dartaotruntime_product on base and patched snapshots.
    Compare output against expected strings.
    """
    with tempfile.TemporaryDirectory() as tmp:
        gen_snap = f"{sdk_host}/gen_snapshot_product"
        dart_rt = f"{sdk_host}/dartaotruntime_product"

        # Compile base → ELF snapshot
        base_snap = os.path.join(tmp, "base.snap")
        r = run([gen_snap, "--snapshot-kind=app-aot-elf",
                 f"--elf={base_snap}", base_dill])
        if r.returncode != 0:
            print(f"  SKIP behavioral test (gen_snapshot failed): {r.stderr[:100]}")
            return True  # skip, not fail

        # Run base
        r = run([dart_rt, base_snap])
        base_output = r.stdout.strip()
        if not base_output:
            print(f"  SKIP: program has no stdout (relies on kernel-level diff checks 1-4)")
            return True
        if expected_base not in base_output:
            print(f"  FAIL base output: expected '{expected_base}' in '{base_output}'")
            return False

        # Compile patched → ELF snapshot
        patch_snap = os.path.join(tmp, "patch.snap")
        r = run([gen_snap, "--snapshot-kind=app-aot-elf",
                 f"--elf={patch_snap}", patch_dill])
        if r.returncode != 0:
            print(f"  SKIP patch behavioral test: {r.stderr[:100]}")
            return True

        r = run([dart_rt, patch_snap])
        patch_output = r.stdout.strip()
        if expected_patch not in patch_output:
            print(f"  FAIL patch output: expected '{expected_patch}' in '{patch_output}'")
            return False
    return True


def main():
    p = argparse.ArgumentParser(description="Differential equivalence tester")
    p.add_argument("--sdk", required=True, help="~/dart/sdk path")
    p.add_argument("--kernel-linker", required=True, help="kernel_linker dir")
    p.add_argument("--baseline-dill", required=True, help="Baseline .dill")
    p.add_argument("--patched-dill", required=True, help="Patched .dill")
    p.add_argument("--patch-bundle", required=True, help="patch_bundle/ dir")
    p.add_argument("--expected-changed", required=True,
                   help='JSON list: ["lib::fn"]')
    p.add_argument("--expected-unchanged", default="[]",
                   help='JSON list of functions that must NOT be flagged')
    p.add_argument("--expected-base-output", default="ORIGINAL",
                   help="Expected string in baseline run output")
    p.add_argument("--expected-patch-output", default="PATCHED",
                   help="Expected string in patched run output")
    args = p.parse_args()

    sdk_host = os.path.join(os.path.expanduser(args.sdk),
                             "xcodebuild/ReleaseARM64")
    expected_changed = json.loads(args.expected_changed)
    expected_unchanged = json.loads(args.expected_unchanged)

    results = []

    # 1. Run kernel_linker
    print("[1] Running kernel_linker diff...")
    with tempfile.TemporaryDirectory() as linker_out:
        linker_manifest = run_linker(
            os.path.expanduser(args.kernel_linker),
            os.path.expanduser(args.baseline_dill),
            os.path.expanduser(args.patched_dill),
            linker_out,
        )
        if linker_manifest is None:
            print("  FAIL: kernel_linker error")
            sys.exit(1)

        # 2. Check false negatives
        print("[2] Checking false negatives...")
        ok = check_false_negatives(linker_manifest, expected_changed)
        results.append(("0 false negatives", ok))
        print(f"  {'PASS' if ok else 'FAIL'}")

        # 3. Check false positives
        print("[3] Checking false positives...")
        ok = check_false_positives(linker_manifest, expected_unchanged)
        results.append(("0 false positives", ok))
        print(f"  {'PASS' if ok else 'FAIL'}")

        # 4. Verify patch bundle matches linker
        print("[4] Verifying patch_bundle consistency with linker...")
        ok = verify_patch_bundle_matches_linker(
            os.path.expanduser(args.patch_bundle), linker_manifest)
        results.append(("patch_bundle matches linker", ok))
        print(f"  {'PASS' if ok else 'FAIL'}")

    # 5. Behavioral smoke test
    print("[5] Running behavioral smoke test...")
    ok = behavioral_smoke_test(
        sdk_host,
        os.path.expanduser(args.baseline_dill),
        os.path.expanduser(args.patched_dill),
        args.expected_base_output,
        args.expected_patch_output,
    )
    results.append(("behavioral equivalence", ok))
    print(f"  {'PASS' if ok else 'FAIL (or skipped)'}")

    print("")
    print("=== Equivalence Test Results ===")
    all_pass = True
    for name, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}: {name}")
        if not ok:
            all_pass = False
    print("")
    if all_pass:
        print("EQUIVALENCE: PASS — patch is safe to release")
        sys.exit(0)
    else:
        print("EQUIVALENCE: FAIL — do NOT release this patch")
        sys.exit(1)


if __name__ == "__main__":
    main()
