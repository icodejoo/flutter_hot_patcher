#!/usr/bin/env python3
"""R3.1 spike probe: add Internal_countClosuresForFunction, a heap-walk native
that counts all live Closure instances whose .function() matches a given
target Function. Answers: can we enumerate all closures pointing at a changed
function (the completeness gap identified in r3_boundary_contract/NOTES.md)?

Uses HeapIterationScope/ObjectVisitor (runtime/vm/heap/heap.h,
runtime/vm/visitor.h) -- confirmed by source read to have NO PRODUCT/
DART_ENABLE_HEAP_SNAPSHOT_WRITER gating (unlike ObjectGraph, which IS gated
out of product builds) -- so this is a production-viable mechanism, not just
a debug-only spike trick.

Usage: python3 apply_probe_patch.py /root/dart/sdk
"""
import sys, re

sdk = sys.argv[1]

# 1. runtime/lib/object.cc -- visitor class + native entry
object_cc = f"{sdk}/runtime/lib/object.cc"
with open(object_cc, encoding="utf-8") as f:
    src = f.read()

anchor = "DEFINE_NATIVE_ENTRY(Internal_ensureDeeplyImmutable, 0, 1) {"
assert anchor in src, "anchor not found in object.cc -- file layout drifted"

insertion = '''// Gate 1 spike (flutter_hot_patcher) R3.1 probe: heap-walk to count all live
// Closure instances whose .function() matches [sample]'s function. Answers
// "can a patch-application engine enumerate every closure instance that
// needs its entry_point redirected" -- see
// spikes/gate2_linker/r3_boundary_contract/NOTES.md. Uses HeapIterationScope/
// ObjectVisitor (NOT ObjectGraph -- that one is compiled out of PRODUCT
// builds via DART_ENABLE_HEAP_SNAPSHOT_WRITER; HeapIterationScope has no such
// gating, confirmed by reading runtime/vm/heap/heap.cc).
class ClosureFunctionCounter : public ObjectVisitor {
 public:
  explicit ClosureFunctionCounter(FunctionPtr target)
      : target_(target), count_(0) {}
  void VisitObject(ObjectPtr obj) override {
    if (obj->GetClassIdOfHeapObject() == kClosureCid) {
      if (static_cast<ClosurePtr>(obj)->untag()->function() == target_) {
        ++count_;
      }
    }
  }
  intptr_t count() const { return count_; }

 private:
  FunctionPtr target_;
  intptr_t count_;
};

DEFINE_NATIVE_ENTRY(Internal_countClosuresForFunction, 0, 1) {
  GET_NON_NULL_NATIVE_ARGUMENT(Closure, sample, arguments->NativeArgAt(0));
  const FunctionPtr target = sample.function();
  HeapIterationScope iteration(thread);
  ClosureFunctionCounter visitor(target);
  iteration.IterateObjects(&visitor);
  return Integer::New(visitor.count());
}

'''
src = src.replace(anchor, insertion + anchor, 1)
with open(object_cc, "w", encoding="utf-8") as f:
    f.write(src)
print("patched", object_cc)

# make sure vm/visitor.h is included (ObjectVisitor) -- heap.h may pull it in
# transitively already, but be explicit/safe.
if '#include "vm/visitor.h"' not in src:
    src = src.replace(
        '#include "vm/resolver.h"',
        '#include "vm/resolver.h"\n#include "vm/visitor.h"',
        1,
    )
    with open(object_cc, "w", encoding="utf-8") as f:
        f.write(src)
    print("  + added vm/visitor.h include")

# 2. runtime/vm/bootstrap_natives.h
bn_h = f"{sdk}/runtime/vm/bootstrap_natives.h"
with open(bn_h, encoding="utf-8") as f:
    src = f.read()
anchor = "  V(Internal_redirectClosureEntryPoint, 2)                                   \\\n"
assert anchor in src, "anchor not found in bootstrap_natives.h -- file layout drifted"
src = src.replace(
    anchor,
    anchor + "  V(Internal_countClosuresForFunction, 1)                                    \\\n",
    1,
)
with open(bn_h, "w", encoding="utf-8") as f:
    f.write(src)
print("patched", bn_h)

# 3. sdk/lib/internal/internal.dart
internal_dart = f"{sdk}/sdk/lib/internal/internal.dart"
with open(internal_dart, encoding="utf-8") as f:
    src = f.read()
anchor = "external Object? redirectClosureEntryPoint(Object target, Object replacement);\n"
assert anchor in src, "anchor not found in internal.dart -- file layout drifted"
src = src.replace(
    anchor,
    anchor
    + "\n/// Gate 1 spike (flutter_hot_patcher) R3.1 probe: count all live Closure\n"
    + "/// instances whose function matches [sampleClosure]'s function (heap walk).\n"
    + "external int countClosuresForFunction(Object sampleClosure);\n",
    1,
)
with open(internal_dart, "w", encoding="utf-8") as f:
    f.write(src)
print("patched", internal_dart)

# 4. sdk/lib/_internal/vm/lib/internal_patch.dart
internal_patch_dart = f"{sdk}/sdk/lib/_internal/vm/lib/internal_patch.dart"
with open(internal_patch_dart, encoding="utf-8") as f:
    src = f.read()
anchor = 'external Object? _redirectClosureEntryPoint(Object target, Object replacement);\n'
assert anchor in src, "anchor not found in internal_patch.dart -- file layout drifted"
insertion = '''
@patch
int countClosuresForFunction(Object sampleClosure) {
  return _countClosuresForFunction(sampleClosure);
}

@pragma("vm:external-name", "Internal_countClosuresForFunction")
external int _countClosuresForFunction(Object sampleClosure);
'''
src = src.replace(anchor, anchor + insertion, 1)
with open(internal_patch_dart, "w", encoding="utf-8") as f:
    f.write(src)
print("patched", internal_patch_dart)

print("\nAll 4 files patched. Next: normal build.py, then the two forced")
print("ninja refreshes from vm_patch/README.md (vm_platform.dill + touch")
print("bootstrap_natives.cc + rebuild dartaotruntime_product/gen_snapshot_product),")
print("then verify with: nm out/ReleaseX64/dartaotruntime_product | grep DN_Internal_countClosuresForFunction")
