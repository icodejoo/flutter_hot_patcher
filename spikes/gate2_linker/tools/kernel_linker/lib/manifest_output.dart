// lib/manifest_output.dart
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'kernel_diff.dart';

/// Writes manifest.json + entry_table.bin + cid_map.bin to [outputDir].
void writeManifest({
  required String outputDir,
  required DiffResult result,
  required String dartSdkCommit,
  required String baselineSha256,
}) {
  Directory(outputDir).createSync(recursive: true);

  final ch = result.classHierarchy;
  final classHierarchyChanged = ch.addedClasses.isNotEmpty ||
      ch.removedClasses.isNotEmpty ||
      ch.hierarchyChanged.isNotEmpty ||
      ch.memberLayoutChanged.isNotEmpty;

  final changedFunctions = [
    ...result.directlyChanged.map((f) => f.toString()),
    ...result.added.map((f) => f.toString()),
  ]..sort();

  final affectedClosure =
      result.transitivelyAffected.map((f) => f.toString()).toList()..sort();

  final icfAffected =
      result.icfAffected.map((f) => f.toString()).toList()..sort();

  // manifest.json
  final manifest = {
    'format_version': '1',
    'dart_sdk_commit': dartSdkCommit,
    'baseline_sha256': baselineSha256,
    'changed_functions': changedFunctions,
    'icf_affected': icfAffected,
    'affected_closure': affectedClosure,
    'class_hierarchy_changed': classHierarchyChanged,
    'class_hierarchy': {
      'added_classes': ch.addedClasses,
      'removed_classes': ch.removedClasses,
      'hierarchy_changed': ch.hierarchyChanged,
      'member_layout_changed': ch.memberLayoutChanged,
    },
  };
  File('$outputDir/manifest.json')
      .writeAsStringSync(JsonEncoder.withIndent('  ').convert(manifest));

  // entry_table.bin
  _writeEntryTable(outputDir, changedFunctions, icfAffected, affectedClosure);

  // cid_map.bin (empty until snapshot-level cid analysis is added in 4-D)
  _writeCidMap(outputDir, {});
}

void _writeEntryTable(
  String dir,
  List<String> changed,
  List<String> icfAffected,
  List<String> affected,
) {
  final interpreter = <String>{...changed, ...icfAffected, ...affected};
  final buf = BytesBuilder();
  buf.add(_u32(interpreter.length));
  for (final name in interpreter.toList()..sort()) {
    final nameBytes = utf8.encode(name);
    buf.add(_u16(nameBytes.length));
    buf.add(nameBytes);
    buf.addByte(0x01); // 0x01 = interpreter_stub
  }
  File('$dir/entry_table.bin').writeAsBytesSync(buf.toBytes());
}

void _writeCidMap(String dir, Map<int, int> cidMap) {
  final buf = BytesBuilder();
  buf.add(_u32(cidMap.length));
  for (final entry in cidMap.entries) {
    buf.add(_u32(entry.key));
    buf.add(_u32(entry.value));
  }
  File('$dir/cid_map.bin').writeAsBytesSync(buf.toBytes());
}

List<int> _u32(int v) => [
      v & 0xFF,
      (v >> 8) & 0xFF,
      (v >> 16) & 0xFF,
      (v >> 24) & 0xFF,
    ];
List<int> _u16(int v) => [v & 0xFF, (v >> 8) & 0xFF];
