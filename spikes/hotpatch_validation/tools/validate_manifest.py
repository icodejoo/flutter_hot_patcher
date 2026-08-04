#!/usr/bin/env python3
"""
Validate a kernel_linker manifest.json against expected.json for a given file.
Usage: validate_manifest.py <manifest.json> <expected.json> <file_id> <scenario_ids...>
Outputs: JSON array of per-scenario results to stdout
"""
import json, os, sys

manifest_path = sys.argv[1]
expected_path = sys.argv[2]
file_id = sys.argv[3]
scenario_ids = sys.argv[4:]

# Load manifest (empty dict if not found)
manifest = {}
if os.path.exists(manifest_path):
    try:
        manifest = json.load(open(manifest_path))
    except Exception as e:
        manifest = {'_error': str(e)}

expected_all = json.load(open(expected_path))

actual_changed = set(
    manifest.get('changed_functions', []) +
    manifest.get('icf_affected', [])
)
actual_affected = set(manifest.get('affected_closure', []))
actual_all_patched = actual_changed | actual_affected
actual_class_hier = manifest.get('class_hierarchy_changed', False)

results = []

for sid in scenario_ids:
    exp = expected_all.get(sid)
    if not exp:
        results.append({'id': sid, 'file': file_id, 'kernel_pass': None,
                        'issues': ['no expected entry'], 'known_limitation': False})
        continue

    kl_exp = exp.get('kernel_linker', {})
    issues = []
    false_negatives = []
    false_positives = []

    # Check: expect_no_changes
    if kl_exp.get('expect_no_changes'):
        if actual_changed or actual_affected:
            false_positives.append(f'Expected 0 changes but got: {list(actual_changed)[:3]}')
    else:
        # Check changed_functions_contains
        for fn_fragment in kl_exp.get('changed_functions_contains', []):
            if not any(fn_fragment in s for s in actual_changed):
                false_negatives.append(f'Missing in changed: {fn_fragment}')

        # Check unchanged_functions_not_contains (false positive check)
        for fn_fragment in kl_exp.get('unchanged_functions_not_contains', []):
            if any(fn_fragment in s for s in actual_all_patched):
                false_positives.append(f'False positive: {fn_fragment}')

    # Check class_hierarchy_changed expectation
    if 'class_hierarchy_changed' in kl_exp:
        expected_hier = kl_exp['class_hierarchy_changed']
        if actual_class_hier != expected_hier:
            issues.append(
                f'class_hierarchy_changed: expected={expected_hier}, actual={actual_class_hier}')

    all_issues = issues + false_negatives + false_positives
    kernel_pass = len(all_issues) == 0
    known_limitation = exp.get('known_limitation', False)

    results.append({
        'id': sid,
        'file': file_id,
        'kernel_pass': kernel_pass,
        'false_negatives': false_negatives,
        'false_positives': false_positives,
        'issues': all_issues,
        'known_limitation': known_limitation,
        'manifest_changed_count': len(actual_changed),
        'manifest_affected_count': len(actual_affected),
        'class_hierarchy_changed': actual_class_hier,
    })

print(json.dumps(results))
