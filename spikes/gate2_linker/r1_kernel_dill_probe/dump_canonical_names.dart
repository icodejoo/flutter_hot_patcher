// R1 probe: does parsing the .dill Kernel binary directly (via package:kernel,
// NOT via gen_snapshot --disassemble or DWARF) give library URIs in
// `package:` form (portable, environment-independent) rather than the
// `file:///...` absolute-path form that both the disassembler output and
// DWARF debug info give (established negative result, see
// ../r2_pool_probe/NOTES.md "R1 CanonicalName -- 探索一条捷径, 证伪")?
import 'dart:io';
import 'package:kernel/kernel.dart';
import 'package:kernel/ast.dart';

void main(List<String> args) {
  final dillPath = args.isNotEmpty ? args[0] : 'probe.dill';
  final component = loadComponentFromBinary(dillPath);

  for (final library in component.libraries) {
    // Skip core/platform libraries -- only interested in OUR package's code.
    if (!library.importUri.toString().contains('probe_pkg') &&
        library.importUri.scheme != 'file') {
      continue;
    }
    if (library.importUri.scheme == 'dart') continue;
    print('LIBRARY uri=${library.importUri} scheme=${library.importUri.scheme}');
    for (final klass in library.classes) {
      print('  CLASS ${klass.name}');
      for (final proc in klass.procedures) {
        print('    MEMBER ${proc.name} (kind=${proc.kind}, '
            'fileOffset=${proc.fileOffset})');
      }
    }
    for (final proc in library.procedures) {
      print('  TOP-LEVEL ${proc.name} (fileOffset=${proc.fileOffset})');
    }
  }
}
