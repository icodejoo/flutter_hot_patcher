// lib/cid_extractor.dart
//
// L4 fix: Extract class→cid mapping from snapshot using analyze_snapshot tool.
// analyze_snapshot is only available in some Dart SDK builds; we return {}
// if the tool is absent so the rest of the pipeline degrades gracefully.
//
// NOTE: analyze_snapshot was NOT found in the current SDK build at
//   ~/dart/sdk/xcodebuild/ReleaseARM64/
// Once it becomes available, pass its path as analyzePath.

import 'dart:convert';
import 'dart:io';

/// Extract class→cid mapping from snapshot using analyze_snapshot tool.
/// Returns {} if analyze_snapshot is not available or fails.
Map<String, int> extractCidMap(String dillPath, String analyzePath) {
  if (!File(analyzePath).existsSync()) return {};

  final tmpJson = '${Directory.systemTemp.path}/cid_map_tmp_${pid}.json';
  final result = Process.runSync(analyzePath, ['--out=$tmpJson', dillPath]);
  if (result.exitCode != 0) {
    stderr.writeln('analyze_snapshot failed: ${result.stderr}');
    return {};
  }

  try {
    final data = jsonDecode(File(tmpJson).readAsStringSync());
    final classes = (data['classes'] as List?) ?? [];
    return {
      for (final cls in classes)
        if (cls['name'] != null && cls['cid'] != null)
          cls['name'] as String: cls['cid'] as int
    };
  } catch (e) {
    stderr.writeln('Failed to parse analyze_snapshot output: $e');
    return {};
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
  final count = changed.length;
  buf.addAll(_u32(count));

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
