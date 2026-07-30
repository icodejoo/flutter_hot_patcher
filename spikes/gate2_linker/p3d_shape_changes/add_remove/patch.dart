// PATCH: oldFn deleted entirely (dead code); newFn added and wired into
// helperCaller. unrelatedX source unchanged.
library;

import 'dart:io';

@pragma('vm:never-inline')
int newFn(int x) => x * 3 - 2; // NEW function

@pragma('vm:never-inline')
int helperCaller(int x) => newFn(x) + 1; // now calls newFn, not oldFn

@pragma('vm:never-inline')
int unrelatedX(int x) => x * 9 + 4;

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(helperCaller(n) + unrelatedX(n));
}
