// R3.1 probe: create several DISTINCT Closure instances that all wrap the
// SAME underlying Function (an instance method torn off from N different
// receiver objects -- each tear-off necessarily binds a different `this`,
// so the compiler cannot canonicalize/intern them the way it can a
// captureless top-level-function tear-off, which round 1 of this probe
// showed DOES get collapsed to a single shared instance -- see NOTES.md
// "round 1" for that negative result and why this test is shaped this way).
//
// Then ask the VM to heap-walk-count how many live Closure instances point
// at that Function. Ground truth = N (5, fixed by handlers.length below).
import 'dart:_internal' as internal;

class Handler {
  final int id;
  Handler(this.id);
  @pragma('vm:never-inline')
  int handle() => id;
}

void main(List<String> args) {
  // args.length is runtime-opaque (always 0 here, but the VALUE isn't what
  // matters -- what matters is that each Handler instance is distinct, which
  // forces a distinct bound-receiver Closure per tear-off regardless of
  // whether the loop bound itself is constant-foldable).
  final n = 5 + args.length;
  final handlers = List<Handler>.generate(n, (i) => Handler(i));
  final registry = <int Function()>[for (final h in handlers) h.handle];

  final sample = handlers[0].handle; // only used to pass the Function identity
  final count = internal.countClosuresForFunction(sample);
  final total = registry.fold<int>(0, (a, f) => a + f());
  print('total=$total handlers=${handlers.length} COUNT=$count');
  // Ground truth: `registry` holds handlers.length (5) distinct Closure
  // instances (one per receiver) + `sample` is a 6th, freshly torn off from
  // handlers[0] AFTER registry was built -> expected VM report = 6, UNLESS
  // the compiler canonicalizes repeat same-receiver tear-offs (registry[0]
  // and sample are both handlers[0].handle) into one shared instance, in
  // which case expected = 5. Either way this distinguishes "all collapsed to
  // 1" (round 1's negative result) from "each receiver gets its own,
  // enumerable instance" (the actually-interesting case for R3.1).
}
