// Gate 2 probe P1 (patched layout): identical to probe_base EXCEPT one new
// field `x` inserted between `a` and `b`, AND x is actually READ at the end
// of main (a write-only field would be tree-shaken away by TFA and would NOT
// change the layout — that was the first surprise, see NOTES.md).
//
// writeB source is unchanged, so if AOT hard-codes the field offset, its
// machine-code offset must differ from probe_base — proving a layout change
// makes every accessor of the class byte-inequivalent.
library;

import 'dart:io';

class Box {
  int a;
  int x; // <-- inserted field
  int b;
  int c;
  Box(this.a, this.x, this.b, this.c);
}

@pragma('vm:never-inline')
int readB(Box box) => box.b;

@pragma('vm:never-inline')
void writeB(Box box, int v) {
  box.b = v;
}

void main(List<String> args) {
  final seed = args.length;
  final box = Box(seed, seed + 10, seed + 1, seed + 2);
  stdout.writeln(readB(box));
  writeB(box, seed + 100);
  stdout.writeln(readB(box));
  stdout.writeln(box.a + box.c);
  stdout.writeln(box.x); // x is READ, so TFA cannot drop it from the layout
}
