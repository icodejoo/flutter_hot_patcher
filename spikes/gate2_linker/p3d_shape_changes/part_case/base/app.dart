// Completeness case: part/part-of (one library split across physical files).
// Tests two things: (1) basic diff works when part-file content changes; (2) a
// function MOVED between the part file and the main file with UNCHANGED body
// (a plausible codegen-regeneration scenario, COVERAGE_GAPS #19 / REVIEW C1) —
// canonical key = source-file path, so a pure structural move (no logic change)
// may show as added+removed+cascade (imprecision, not unsoundness).
library;

import 'dart:io';

part 'helpers.dart';

@pragma('vm:never-inline')
int unrelatedPart(int n) => n * 4 + 3; // stays in app.dart both versions

void main(List<String> args) {
  final n = args.length;
  stdout.writeln(helperA(n) + helperB(n) + unrelatedPart(n));
}
