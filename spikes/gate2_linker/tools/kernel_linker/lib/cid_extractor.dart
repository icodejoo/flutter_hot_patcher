// lib/cid_extractor.dart
//
// L4 fix: Extract class→cid mapping from snapshot using analyze_snapshot tool.
// analyze_snapshot is only available in some Dart SDK builds; we return {}
// if the tool is absent so the rest of the pipeline degrades gracefully.
//
// JSON format (analyzer_version: 2):
//   { "objects": [ { "type": "Class", "class_id": 611, "name": "Foo", ... }, ... ] }

import 'dart:convert';
import 'dart:io';

/// Extract class name→class_id mapping from snapshot using analyze_snapshot tool.
/// Returns {} if analyze_snapshot is not available or fails.
Map<String, int> extractCidMap(String snapshotPath, String analyzePath) {
  if (!File(analyzePath).existsSync()) return {};
  if (!File(snapshotPath).existsSync()) return {};

  final tmpJson =
      '${Directory.systemTemp.path}/cid_map_tmp_${pid}_${snapshotPath.hashCode.abs()}.json';
  final result =
      Process.runSync(analyzePath, ['--out=$tmpJson', snapshotPath]);
  if (result.exitCode != 0) {
    stderr.writeln('analyze_snapshot failed: ${result.stderr}');
    return {};
  }

  try {
    final data = jsonDecode(File(tmpJson).readAsStringSync())
        as Map<String, dynamic>;
    final objs = (data['objects'] as List?) ?? [];
    return {
      for (final obj in objs)
        if (obj is Map &&
            obj['type'] == 'Class' &&
            obj['name'] != null &&
            obj['class_id'] != null)
          obj['name'] as String: obj['class_id'] as int
    };
  } catch (e) {
    stderr.writeln('Failed to parse analyze_snapshot output: $e');
    return {};
  } finally {
    try {
      File(tmpJson).deleteSync();
    } catch (_) {}
  }
}

/// Generate cid_map.bin bytes from base and patch snapshot class mappings.
/// Maps old_cid → new_cid for classes that shifted position.
List<int> generateCidMapBytes(
    Map<String, int> baseCids, Map<String, int> patchCids) {
  final changed = <int, int>{};
  for (final entry in baseCids.entries) {
    final patchCid = patchCids[entry.key];
    if (patchCid != null && patchCid != entry.value) {
      changed[entry.value] = patchCid;
    }
  }

  final buf = <int>[];

  // count (u32 LE)
  buf.addAll(_u32(changed.length));

  for (final entry in changed.entries) {
    buf.addAll(_u32(entry.key));
    buf.addAll(_u32(entry.value));
  }

  return buf;
}

List<int> _u32(int v) => [
      v & 0xFF,
      (v >> 8) & 0xFF,
      (v >> 16) & 0xFF,
      (v >> 24) & 0xFF,
    ];
