# X3: Multi-Isolate Hotpatch Behavior

## Behavior Tested

- `Dart_LoadLibraryFromBytecode` operates on the **CURRENT isolate's heap**
- `HeapIterationScope` in `dart_harness.c` only traverses current isolate's objects
- **Result**: patches applied in isolate A do NOT affect isolate B's cached function pointers

## Test Scenario (T96, T96b)

### Baseline
- `multiiso_value()` returns `'isolate_original_N'` where N is the counter
- `multiiso_increment()` increments `_counter` by 1 and returns `'count:N'`

### After Hotpatch
- `multiiso_value()` returns `'isolate_patched_N'` (text changed)
- `multiiso_increment()` increments `_counter` by 2 (semantics changed)

## Single-Isolate Behavior (Expected: PASS)

When the C embedding applies the patch to the CURRENT isolate:
1. Patch bytecode is loaded into current isolate's heap
2. `HeapIterationScope` finds all closure instances in current isolate
3. All old closure code pointers are rewritten to new function entry points
4. Next call to `multiiso_value()` or `multiiso_increment()` sees the new behavior

**Test Result**: T96 baseline → patch → T96 returns `'isolate_patched_0'` (CHANGED)

## Multi-Isolate Scenario (Expected: ISOLATE-LOCAL)

In a real multi-isolate application (e.g., Flutter compute() tasks):

```
Main Isolate                    Background Isolate (spawn)
──────────────────              ─────────────────────
(before patch)                  (before patch)
multiiso_value() →              multiiso_value() → 
'isolate_original_0'            'isolate_original_0'

PATCH APPLIED HERE
(main isolate only)

(after patch)                   (after patch)
multiiso_value() →              multiiso_value() →
'isolate_patched_0'             'isolate_original_0'
                                ^^^^^^ UNCHANGED
```

**Why**: The background isolate's heap is a separate allocation context:
1. When `Dart_LoadLibraryFromBytecode` is called, it only affects the calling isolate
2. The background isolate never receives the patch notification
3. Background isolate keeps using the old function address (still valid, pointing to old code)

## Production Implication

Apps using `Isolate.spawn()` or Flutter `compute()` background tasks:

### Safe (Conservative Behavior)
- ✓ Background isolate continues with old code after main isolate is patched
- ✓ No crash (old code is not deleted, still valid in memory)
- ✓ No cross-isolate memory corruption (heaps are separate)

### Limitation
- ✗ Background work using patched logic will NOT see the fix until restart
- ✗ If a function's logic is critical, background isolate may behave differently than main

## Mitigation Strategy (Documented, Not Requiring VM Changes)

### Option 1: Patch Scope Discipline
- Only patch functions called from the main isolate
- Document in changelog: "hotpatch scope: main isolate only"
- Verify no dependencies from `compute()` tasks

### Option 2: Background Isolate Restart
After applying patch:
```dart
// Force background isolate to restart by stopping its port
isolatePort.send('stop'); // Custom protocol
// Create new isolate on next background task
```

### Option 3: Isolate-Safe Library
Create a hotpatch-aware concurrency library that:
1. Accepts callbacks as code paths (not closures)
2. Looks up function address at CALL TIME (not capture time)
3. Ensures background task always uses main isolate's latest code

## Summary

**Behavior**: Patches are **isolate-local**. Isolate B's cached function pointers are NOT updated when isolate A applies a patch.

**Safety**: This is the conservative, safe choice (no crashes, no data corruption).

**Workflow**: Document the boundary in hotpatch release notes. For apps needing synchronized background work:
1. Stop and restart background isolates after patch
2. OR restrict patches to main-isolate-only code paths
3. OR use a callback registry that is lookup-time-dynamic (not capture-time)

## Test Coverage

- T96: Single-isolate function replacement (PASS, text change visible)
- T96b: Single-isolate state change (PASS, counter increment behavior changes)
- Multi-isolate case: Documented as a limitation (requires Isolate.spawn() which is not testable in kernel-only validation)

## References

- `dart_harness.c`: `HeapIterationScope` only traverses current isolate
- `kernel_linker.dart`: Patch is applied per-isolate via `Dart_LoadLibraryFromBytecode`
- Dart VM isolate model: Each isolate has independent heap, GC, and thread
