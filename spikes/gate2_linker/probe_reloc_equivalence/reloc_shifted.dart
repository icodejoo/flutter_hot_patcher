// Experiment A (position-independence): identical pureLeaf / caller / callsLib
// source as reloc_base.dart, but three unrelated functions are added (and
// used) before them, perturbing the snapshot's overall layout without changing
// the logic of the three functions under test.
library;

import 'dart:io';

@pragma('vm:never-inline')
int unrelatedA(int x) => x + 11111;
@pragma('vm:never-inline')
int unrelatedB(int x) => x * 7 - 222;
@pragma('vm:never-inline')
int unrelatedC(int x) => (x ^ 0x5a5a) + 3;

@pragma('vm:never-inline')
int pureLeaf(int x) => x * 3 + 1;

@pragma('vm:never-inline')
int caller(int x) => pureLeaf(x) + pureLeaf(x + 1);

@pragma('vm:never-inline')
int callsLib(int x) {
  stdout.writeln('val=$x');
  return x + 7;
}

void main(List<String> args) {
  final n = args.length;
  final r = caller(n) +
      callsLib(n) +
      unrelatedA(n) +
      unrelatedB(n) +
      unrelatedC(n);
  stdout.writeln(r);
}
