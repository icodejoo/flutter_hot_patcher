// PATCH: price() gains an optional named parameter {discount=0} (a real
// signature change: new arguments descriptor at every call site). callerA is
// updated to pass discount:5 (source changes). callerB's SOURCE is IDENTICAL
// to base — still `price(n)` — testing whether it's silently missed.
library;

import 'dart:io';

@pragma('vm:never-inline')
int price(int qty, {int discount = 0}) => qty * 10 - discount;

@pragma('vm:never-inline')
int callerA(int n) => price(n, discount: 5) + (n & 1);

@pragma('vm:never-inline')
int callerB(int n) => price(n); // UNCHANGED source vs base.dart

@pragma('vm:never-inline')
int unrelatedShape(int n) => n * 3 + 1;

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(callerA(n) + callerB(n) + unrelatedShape(n));
}
