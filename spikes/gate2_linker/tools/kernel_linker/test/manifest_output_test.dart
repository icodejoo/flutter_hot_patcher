/// Simple test script — no package:test needed, uses assert + print.
/// Run: dart --packages=.dart_tool/package_config.json test/manifest_output_test.dart
import 'dart:convert';
import 'dart:io';
import '../lib/manifest_output.dart';
import '../lib/kernel_diff.dart';
import '../lib/canonical_name.dart';
import '../lib/class_hierarchy.dart';

DiffResult _empty() => DiffResult(
  directlyChanged: [], added: [], removed: [],
  transitivelyAffected: [], icfAffected: [],
  classHierarchy: ClassHierarchyDiff(
    addedClasses: [], removedClasses: [],
    hierarchyChanged: [], memberLayoutChanged: []),
  baseCount: 10, patchCount: 10,
);

FunctionId _fid(String uri, String name) =>
    FunctionId(libraryUri: uri, memberName: name, fileOffset: 0);

void _pass(String name) => print('  PASS: $name');
void _fail(String name, String msg) {
  print('  FAIL: $name — $msg');
  exitCode = 1;
}

void main() {
  print('=== manifest_output tests ===');

  // Test 1
  {
    final tmp = Directory.systemTemp.createTempSync('t1_');
    writeManifest(outputDir: tmp.path, result: _empty(),
        dartSdkCommit: 'abc123', baselineSha256: 'sha256abc');
    final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync()) as Map;
    if (m['format_version'] == '1' &&
        m['dart_sdk_commit'] == 'abc123' &&
        m['baseline_sha256'] == 'sha256abc' &&
        (m['changed_functions'] as List).isEmpty &&
        m['class_hierarchy_changed'] == false) {
      _pass('format_version and provenance');
    } else {
      _fail('format_version and provenance', m.toString());
    }
    tmp.deleteSync(recursive: true);
  }

  // Test 2
  {
    final tmp = Directory.systemTemp.createTempSync('t2_');
    final result = DiffResult(
      directlyChanged: [_fid('file:///lib/a.dart', 'greet')],
      added: [], removed: [],
      transitivelyAffected: [_fid('file:///lib/a.dart', 'callGreet')],
      icfAffected: [],
      classHierarchy: ClassHierarchyDiff(
        addedClasses: [], removedClasses: [],
        hierarchyChanged: [], memberLayoutChanged: []),
      baseCount: 2, patchCount: 2,
    );
    writeManifest(outputDir: tmp.path, result: result,
        dartSdkCommit: 'c1', baselineSha256: 's1');
    final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync()) as Map;
    final changed = m['changed_functions'] as List;
    final affected = m['affected_closure'] as List;
    if (changed.contains('file:///lib/a.dart::greet') &&
        affected.contains('file:///lib/a.dart::callGreet')) {
      _pass('changed and affected functions');
    } else {
      _fail('changed and affected', 'changed=$changed affected=$affected');
    }
    tmp.deleteSync(recursive: true);
  }

  // Test 3
  {
    final tmp = Directory.systemTemp.createTempSync('t3_');
    writeManifest(outputDir: tmp.path, result: _empty(),
        dartSdkCommit: 'c1', baselineSha256: 's1');
    if (File('${tmp.path}/entry_table.bin').existsSync()) {
      _pass('entry_table.bin created');
    } else {
      _fail('entry_table.bin created', 'file missing');
    }
    tmp.deleteSync(recursive: true);
  }

  // Test 4
  {
    final tmp = Directory.systemTemp.createTempSync('t4_');
    writeManifest(outputDir: tmp.path, result: _empty(),
        dartSdkCommit: 'c1', baselineSha256: 's1');
    final bytes = File('${tmp.path}/cid_map.bin').readAsBytesSync();
    if (bytes.length == 4 && bytes.every((b) => b == 0)) {
      _pass('cid_map.bin empty (count=0)');
    } else {
      _fail('cid_map.bin empty', 'bytes=$bytes');
    }
    tmp.deleteSync(recursive: true);
  }

  // Test 5
  {
    final tmp = Directory.systemTemp.createTempSync('t5_');
    final result = DiffResult(
      directlyChanged: [], added: [], removed: [],
      transitivelyAffected: [], icfAffected: [],
      classHierarchy: ClassHierarchyDiff(
        addedClasses: ['NewClass'], removedClasses: [],
        hierarchyChanged: [], memberLayoutChanged: []),
      baseCount: 5, patchCount: 6,
    );
    writeManifest(outputDir: tmp.path, result: result,
        dartSdkCommit: 'c1', baselineSha256: 's1');
    final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync()) as Map;
    if (m['class_hierarchy_changed'] == true) {
      _pass('class_hierarchy_changed=true when class added');
    } else {
      _fail('class_hierarchy_changed', m.toString());
    }
    tmp.deleteSync(recursive: true);
  }

  print('');
  if (exitCode == 0) {
    print('All tests passed!');
  } else {
    print('SOME TESTS FAILED');
  }
}
