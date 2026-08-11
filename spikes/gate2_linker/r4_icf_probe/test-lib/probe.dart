// R4 ICF probe: are functionA/functionB (byte-identical bodies) folded by
// gen_snapshot? If so, does analyze_snapshot's structured JSON output reveal
// the fold (e.g. two Function objects pointing at the SAME Code object, or
// two Code objects with identical offset/size), giving kernel_linker an
// exact, non-heuristic way to detect ICF groups -- an alternative to guessing
// from Kernel-level fingerprint matches (Mac's Option A/B question).
@pragma('vm:never-inline')
int functionA() => 42;

@pragma('vm:never-inline')
int functionB() => 42;

@pragma('vm:never-inline')
int functionC() => 43; // deliberately different, control/negative case

void main(List<String> args) {
  print('${functionA()} ${functionB()} ${functionC()}');
}
