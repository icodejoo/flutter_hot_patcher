// R2 probe: does gen_snapshot --disassemble --code_comments annotate a
// pooled DOUBLE CONSTANT with its actual value? This is the exact S1
// repro scenario (const fee = 0.07 -> 0.08, invisible to objdump-based
// diff_linker since normalize() wildcards the pool slot).
library;

import 'dart:io';

const fee = 0.08;

@pragma('vm:never-inline')
double total(double v) => v * (1 + fee);

void main(List<String> args) {
  stdout.writeln(total(args.length.toDouble()));
}
