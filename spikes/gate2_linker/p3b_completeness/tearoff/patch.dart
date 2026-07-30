// Completeness case: change a torn-off method/function. `target` is torn off
// (`_held = target`) and called INDIRECTLY via the closure, and also called
// DIRECTLY by `direct`. Changing target must: (a) flag target (its own bytes
// change, cond 1); (b) cascade to `direct` (direct caller, cond 2); (c) NOT
// require `useHeld` to reinterpret — the tear-off closure resolves target's
// entry, so runtime entry redirection (Gate 1 V1/V2) covers the indirect path.
// This verifies the DIFF-LINKER flags target (the P2 observation that a tear-off
// call site doesn't cascade is correct — the target itself carries the change).
library;

import 'dart:io';

@pragma('vm:never-inline')
int target(int x) => x + 2;

int Function(int)? _held;

@pragma('vm:never-inline')
int useHeld(int x) => _held!(x); // INDIRECT call through the tear-off closure

@pragma('vm:never-inline')
int direct(int x) => target(x) + 100; // DIRECT caller — must cascade

void main(List<String> args) {
  final n = args.length;
  _held = target; // tear-off
  stdout.writeln(useHeld(n) + direct(n));
}
