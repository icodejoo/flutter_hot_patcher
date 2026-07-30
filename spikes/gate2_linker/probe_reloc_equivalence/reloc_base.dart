library;

import 'dart:io';

@pragma('vm:never-inline')
int pureLeaf(int x) => x * 3 + 1; // no external refs — expect position-independent

@pragma('vm:never-inline')
int caller(int x) => pureLeaf(x) + pureLeaf(x + 1); // calls another function

@pragma('vm:never-inline')
int callsLib(int x) {
  stdout.writeln('val=$x'); // references a string const + a library call
  return x + 7;
}

void main(List<String> args) {
  final n = args.length;
  final r = caller(n) + callsLib(n);
  stdout.writeln(r);
}
