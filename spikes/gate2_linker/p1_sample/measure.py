#!/usr/bin/env python3
"""P1 precision measurement: compare the diff-linker's in-sample closure against
the ground-truth closure computed from manifest.json's direct call edges.

ground truth = fixpoint from `changed` over DIRECT edges: a caller joins the
closure if it directly calls a closure member (the two-condition model's cond 2;
cond 1 = the changed elements themselves). Virtual edges are intentionally
absent from the manifest, so a polymorphic caller must NOT appear.

Reports, restricted to in-sample (app/mod) functions:
  - misses     = ground-truth members the linker did NOT flag (UNSOUND if any)
  - false-pos  = linker-flagged in-sample funcs NOT in ground truth (imprecision)
Perfect precision = both empty.

Usage: measure.py manifest.json closure.txt
  closure.txt = lines "CLOSURE\t<key>" from diff_linker --emit-closure
"""
import json, sys, re

def app_key(k):
    # in-sample keys look like "modI.dart::name" or "app.dart::name" after the
    # src-root prefix was stripped by diff_linker.
    return bool(re.match(r'^(app|mod\d+)\.dart::', k))

def main():
    manifest = json.load(open(sys.argv[1]))
    closure_lines = open(sys.argv[2]).read().splitlines()
    actual = {l.split('\t', 1)[1] for l in closure_lines if l.startswith('CLOSURE\t')}
    actual_in = {k for k in actual if app_key(k)}

    changed = set(manifest['changed'])
    # reverse adjacency: callee -> {callers}
    callers = {}
    for caller, callee in manifest['edges']:
        callers.setdefault(callee, set()).add(caller)
    # fixpoint: start from changed, add any direct caller of a closure member
    expected = set(changed)
    frontier = list(changed)
    while frontier:
        n = frontier.pop()
        for c in callers.get(n, ()):
            if c not in expected:
                expected.add(c)
                frontier.append(c)
    expected_in = {k for k in expected if app_key(k)}

    misses = expected_in - actual_in
    false_pos = actual_in - expected_in

    print(f'in-sample ground-truth closure : {len(expected_in)}')
    print(f'in-sample linker closure        : {len(actual_in)}')
    print(f'changed elements (cond 1 seeds) : {len(changed)}')
    print(f'MISSES (unsound, must be 0)      : {len(misses)}')
    for m in sorted(misses):
        print(f'    MISS  {m}')
    print(f'FALSE POSITIVES (imprecision)    : {len(false_pos)}')
    for f in sorted(false_pos):
        print(f'    FP    {f}')
    ok = not misses and not false_pos
    print(f'RESULT: {"PASS — closure == ground truth (sound + precise)" if ok else "MISMATCH"}')
    # also report how many out-of-sample (SDK) funcs were flagged (should be ~0)
    sdk_flagged = len(actual) - len(actual_in)
    print(f'(SDK/library funcs flagged: {sdk_flagged} — expect 0; >0 = residual alignment noise)')
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
