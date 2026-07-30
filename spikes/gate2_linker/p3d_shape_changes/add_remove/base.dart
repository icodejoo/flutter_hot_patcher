// Completeness case: add/remove symbols (added-set/removed-set bookkeeping).
// `oldFn` is deleted in the patch (dead code elimination — nothing calls it
// there); `newFn` is added and immediately wired into `helperCaller`.
// `unrelatedX` never touches either — expect equivalent.
library;

import 'dart:io';

@pragma('vm:never-inline')
int oldFn(int x) => x * 2 + 1; // removed entirely in patch

@pragma('vm:never-inline')
int helperCaller(int x) => oldFn(x) + 1; // patch: calls newFn instead

@pragma('vm:never-inline')
int unrelatedX(int x) => x * 9 + 4; // expect equivalent

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(helperCaller(n) + unrelatedX(n));
}
