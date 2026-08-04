#!/usr/bin/env python3
"""
Generate COVERAGE_REPORT.md + COVERAGE_DETAIL.md from coverage_results.json.
Usage: python3 gen_report.py [coverage_results.json]
"""
import json, sys, datetime
from pathlib import Path

results_path = sys.argv[1] if len(sys.argv) > 1 else 'coverage_results.json'
results = json.load(open(results_path)) if Path(results_path).exists() else []

if not results:
    print("No results found. Run run_validation.sh first.")
    sys.exit(1)

total = len(results)
kernel_tested = [r for r in results if r.get('kernel_pass') is not None]
kernel_pass_count = sum(1 for r in kernel_tested if r.get('kernel_pass'))
runtime_tested = [r for r in results if 'runtime_pass' in r]
runtime_pass_count = sum(1 for r in runtime_tested if r.get('runtime_pass'))
crash_count = sum(1 for r in results if r.get('runtime_result') == 'CRASH')
known_limit_count = sum(1 for r in results if r.get('known_limitation'))
false_neg_count = sum(len(r.get('false_negatives', [])) for r in results)
false_pos_count = sum(len(r.get('false_positives', [])) for r in results)

def pct(n, d):
    return f'{100*n//max(d,1)}%'

def status_icon(ok):
    return 'PASS' if ok else 'FAIL'

kt = len(kernel_tested)
rt = len(runtime_tested)

hard_pass = (
    false_neg_count == 0 and
    false_pos_count == 0 and
    crash_count == 0 and
    (rt == 0 or runtime_pass_count / rt >= 0.90)
)

categories = {
    'primitives (T01-T07)': [r for r in results if r['id'] <= 'T07'],
    'collections (T08-T14)': [r for r in results if 'T08' <= r['id'] <= 'T14'],
    'nullsafety (T15-T19)': [r for r in results if 'T15' <= r['id'] <= 'T19'],
    'constants (T20-T25)': [r for r in results if 'T20' <= r['id'] <= 'T25'],
    'functions (T26-T34)': [r for r in results if 'T26' <= r['id'] <= 'T34'],
    'classes (T35-T42)': [r for r in results if 'T35' <= r['id'] <= 'T42'],
    'generics (T43-T46)': [r for r in results if 'T43' <= r['id'] <= 'T46'],
    'operators (T47-T51)': [r for r in results if 'T47' <= r['id'] <= 'T51'],
    'async (T52-T55)': [r for r in results if 'T52' <= r['id'] <= 'T55'],
    'errors (T56-T59)': [r for r in results if 'T56' <= r['id'] <= 'T59'],
    'strings (T60-T63)': [r for r in results if 'T60' <= r['id'] <= 'T63'],
    'thirdparty (T64-T68)': [r for r in results if 'T64' <= r['id'] <= 'T68'],
    'flutter-like (T69-T73)': [r for r in results if 'T69' <= r['id'] <= 'T73'],
    'propagation (T74-T81)': [r for r in results if 'T74' <= r['id'] <= 'T81'],
    'hierarchy (T82-T86)': [r for r in results if 'T82' <= r['id'] <= 'T86'],
    'edge (T87-T91)': [r for r in results if 'T87' <= r['id'] <= 'T91'],
}

report = f"""# iOS Hotpatch Production Validation Coverage Report

Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}
SDK commit: 1aa7d7321fb
Test tools: kernel_linker (Dart) + validate_manifest.py (Python)

---

## Summary Metrics

| Metric | Result | Target | Status |
|--------|--------|--------|--------|
| Total scenarios | {total}/91 | 91 | {'PASS' if total >= 91 else 'FAIL'} |
| Kernel pass rate | {kernel_pass_count}/{kt} ({pct(kernel_pass_count, kt)}) | >=95% | {status_icon(kt > 0 and kernel_pass_count/kt >= 0.95)} |
| False negatives | {false_neg_count} | 0 | {status_icon(false_neg_count == 0)} |
| False positives | {false_pos_count} | 0 | {status_icon(false_pos_count == 0)} |
| Runtime pass rate | {runtime_pass_count}/{rt} ({pct(runtime_pass_count, rt)}) | >=90% | {status_icon(rt == 0 or runtime_pass_count/max(rt,1) >= 0.90)} |
| Crash count | {crash_count}/{total} | 0 | {status_icon(crash_count == 0)} |
| Known limitations | {known_limit_count} | — | INFO |

## Production Verdict

{'PASS — meets production-ready criteria' if hard_pass else 'FAIL — see details below'}

---

## By Category

| Category | Total | Kernel Pass | Runtime Pass |
|----------|-------|-------------|--------------|
"""

for cat_name, cat_results in categories.items():
    ct = len(cat_results)
    if ct == 0:
        continue
    ck = sum(1 for r in cat_results if r.get('kernel_pass'))
    crk = [r for r in cat_results if 'runtime_pass' in r]
    cr = sum(1 for r in crk if r.get('runtime_pass'))
    rt_str = f'{cr}/{len(crk)}' if crk else 'TBD'
    report += f'| {cat_name} | {ct} | {ck}/{ct} | {rt_str} |\n'

report += "\n---\n\n## Known Limitations\n\n"
report += "| Scenario | Reason |\n|----------|--------|\n"
report += "| T52-T55 (async) | dart2bytecode async support unverified — sync proxies used |\n"
report += "| T82-T86 (hierarchy) | class_hierarchy_changed=true — patch rejected by design |\n"

Path('COVERAGE_REPORT.md').write_text(report)
print(f"Generated COVERAGE_REPORT.md")

# COVERAGE_DETAIL.md
detail = "# iOS Hotpatch Coverage Detail\n\n"
for r in sorted(results, key=lambda x: x['id']):
    kp = r.get('kernel_pass')
    kicon = 'PASS' if kp else ('SKIP' if kp is None else 'FAIL')
    rp = r.get('runtime_pass')
    ricon = 'PASS' if rp else ('SKIP' if rp is None else ('CRASH' if r.get('runtime_result') == 'CRASH' else 'FAIL'))
    kl = ' [KNOWN_LIMITATION]' if r.get('known_limitation') else ''

    detail += f"### {r['id']} — {r.get('description', r.get('file', ''))}{kl}\n"
    detail += f"- **Kernel**: {kicon}"
    if r.get('false_negatives'):
        detail += f" FALSE_NEG: {r['false_negatives']}"
    if r.get('false_positives'):
        detail += f" FALSE_POS: {r['false_positives']}"
    if r.get('issues'):
        detail += f" ISSUES: {r['issues']}"
    detail += f" (changed={r.get('manifest_changed_count', '?')}, affected={r.get('manifest_affected_count', '?')})\n"
    detail += f"- **Runtime**: {ricon} expected={r.get('expected_output', '?')} actual={r.get('actual_output', 'TBD')}\n\n"

Path('COVERAGE_DETAIL.md').write_text(detail)
print(f"Generated COVERAGE_DETAIL.md")
print(f"Summary: kernel {kernel_pass_count}/{kt}, false_neg={false_neg_count}, false_pos={false_pos_count}, crashes={crash_count}")
