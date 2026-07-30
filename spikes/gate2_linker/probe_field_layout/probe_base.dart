// Gate 2 probe P1 (baseline layout). Field values derive from a runtime-
// unknown seed (args.length) so the compiler cannot constant-fold the field
// reads away — writeB must emit a real store against the object.
//
// Compare against probe_patched.dart (same class + one inserted field that is
// actually READ). See NOTES.md for the disassembly result.
library;

import 'dart:io';

class Box {
  int a;
  int b;
  int c;
  Box(this.a, this.b, this.c);
}

@pragma('vm:never-inline')
int readB(Box box) => box.b;

@pragma('vm:never-inline')
void writeB(Box box, int v) {
  box.b = v;
}

void main(List<String> args) {
  final seed = args.length; // runtime-unknown, defeats constant folding
  final box = Box(seed, seed + 1, seed + 2);
  stdout.writeln(readB(box));
  writeB(box, seed + 100);
  stdout.writeln(readB(box));
  stdout.writeln(box.a + box.c); // keep all fields live / object escaping
}
