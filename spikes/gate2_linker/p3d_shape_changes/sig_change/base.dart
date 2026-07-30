// Completeness case: SIGNATURE change (change-shape not yet tested — the
// existing corpus only tested constant-body edits). `price` gains a new
// optional named parameter in the patch. `callerA` is updated to pass it
// (source changes); `callerB`'s SOURCE is UNCHANGED (still `price(n)`, relying
// on the new parameter's default) — probes whether a callee signature change
// silently escapes an unchanged call site (REVIEW change-shape-corpus-gap).
library;

import 'dart:io';

@pragma('vm:never-inline')
int price(int qty) => qty * 10;

@pragma('vm:never-inline')
int callerA(int n) => price(n) + (n & 1); // runtime-dependent extra op: not foldable, avoids ICF-merging with callerB

@pragma('vm:never-inline')
int callerB(int n) => price(n); // patch: price() gains {discount=0}; source here UNCHANGED

@pragma('vm:never-inline')
int unrelatedShape(int n) => n * 3 + 1; // no price() — expect equivalent

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(callerA(n) + callerB(n) + unrelatedShape(n));
}
