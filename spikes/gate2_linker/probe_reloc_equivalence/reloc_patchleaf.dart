// Experiment C (byte-equality is unsound): same as reloc_base.dart EXCEPT
// pureLeaf's body changes ONE constant (x*3+1 -> x*3+2). Same-width immediate
// => pureLeaf keeps the same machine-code SIZE => caller's `call pureLeaf`
// rel32 (a relative distance) is unchanged => caller's bytes are IDENTICAL to
// reloc_base's caller. Yet caller must run interpreted in the new program,
// because the pureLeaf it directly calls was replaced. Proves byte-equality
// alone is not a sound equivalence test; the call target must also be valid.
library;

import 'dart:io';

@pragma('vm:never-inline')
int pureLeaf(int x) => x * 3 + 2; // <-- was +1

@pragma('vm:never-inline')
int caller(int x) => pureLeaf(x) + pureLeaf(x + 1); // UNCHANGED source

@pragma('vm:never-inline')
int callsLib(int x) {
  stdout.writeln('val=$x');
  return x + 7;
}

void main(List<String> args) {
  final n = args.length;
  final r = caller(n) + callsLib(n);
  stdout.writeln(r);
}
