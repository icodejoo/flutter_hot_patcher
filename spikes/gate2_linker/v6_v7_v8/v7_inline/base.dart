// V7 inline cascade — BASE.
//
// `leaf` is small and inlinable (NO vm:never-inline) so AOT inlines its body
// into every caller. The callers ARE vm:never-inline so they stay distinct
// symbols we can inspect. When the patch changes leaf's body, each caller's
// machine code — which embeds leaf's old body — changes too, so condition 1
// (own bytes changed) must flag EVERY inline site. `untouched` never calls
// leaf and must stay equivalent. This tests that inlining creates no hidden
// copy the linker misses.
library;

import 'dart:io';

// Inlinable leaf — its body gets copied into each caller's code.
int leaf(int x) => x * 3 + 1;

@pragma('vm:never-inline')
int callerA(int x) => leaf(x) + 10;

@pragma('vm:never-inline')
int callerB(int x) => leaf(x) * 2 + leaf(x + 1);

@pragma('vm:never-inline')
int untouched(int x) => x * 7 + 99; // never calls leaf — expect equivalent

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(callerA(n) + callerB(n) + untouched(n));
}
