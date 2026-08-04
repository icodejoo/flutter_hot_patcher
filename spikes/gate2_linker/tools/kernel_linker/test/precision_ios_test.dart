/// iOS arm64 precision test — 0 false negatives, 0 false positives.
/// Run: dart --packages=.dart_tool/package_config.json test/precision_ios_test.dart
import 'dart:convert';
import 'dart:io';
import 'package:kernel/kernel.dart';
import '../lib/kernel_diff.dart';
import '../lib/manifest_output.dart';

final fixtures = '${Platform.script.resolve('../test/fixtures').toFilePath()}';

void _pass(String name) => print('  PASS: $name');
void _fail(String name, String msg) {
  print('  FAIL: $name — $msg');
  exitCode = 1;
}

void main() {
  print('=== iOS arm64 precision tests ===');

  final baseFile = '$fixtures/greet_base.dill';
  final patchFile = '$fixtures/greet_patch.dill';

  if (!File(baseFile).existsSync() || !File(patchFile).existsSync()) {
    print('SKIP: fixtures missing ($fixtures)');
    return;
  }

  // Test 1: identity diff → 0 changes, 0 affected (0 false positives)
  {
    final base = loadComponentFromBinary(baseFile);
    final result = diffComponents(base, base);
    if (result.directlyChanged.isEmpty && result.added.isEmpty &&
        result.transitivelyAffected.isEmpty) {
      _pass('identity diff: 0 changes, 0 affected (0 false positives)');
    } else {
      _fail('identity diff', 'changed=${result.directlyChanged} '
          'affected=${result.transitivelyAffected}');
    }
  }

  // Test 2: greet changed, greetAlt NOT changed (0 false negatives for greet,
  //         0 false positives for greetAlt)
  {
    final base = loadComponentFromBinary(baseFile);
    final patch = loadComponentFromBinary(patchFile);
    final result = diffComponents(base, patch);
    final changed = result.directlyChanged.map((f) => f.toString()).toList();
    final greetChanged = changed.any((s) => s.endsWith('::greet'));
    final greetAltChanged = changed.any((s) => s.contains('greetAlt'));
    if (greetChanged && !greetAltChanged) {
      _pass('greet in changed, greetAlt NOT in changed (0 false neg/pos)');
    } else {
      _fail('greet/greetAlt detection',
          'changed=$changed (greetChanged=$greetChanged, greetAltChanged=$greetAltChanged)');
    }
  }

  // Test 3: getResult transitively affected (because it calls callGreet → greetVar)
  //         setup NOT in changed or transitively (assigns greet but doesn't call it)
  {
    final base = loadComponentFromBinary(baseFile);
    final patch = loadComponentFromBinary(patchFile);
    final result = diffComponents(base, patch);
    final affected = result.transitivelyAffected.map((f) => f.toString()).toList();
    final changed = result.directlyChanged.map((f) => f.toString()).toList();
    final allAffected = {...changed, ...affected};
    final getResultAffected = allAffected.any((s) => s.contains('getResult'));
    final setupAffected = allAffected.any((s) => s.contains('setup'));
    if (getResultAffected && !setupAffected) {
      _pass('getResult in patch set, setup NOT (0 false positives for setup)');
    } else {
      _fail('getResult/setup', 'allAffected=$allAffected');
    }
  }

  // Test 4: manifest.json produced correctly
  {
    final base = loadComponentFromBinary(baseFile);
    final patch = loadComponentFromBinary(patchFile);
    final result = diffComponents(base, patch);
    final tmp = Directory.systemTemp.createTempSync('precision_');
    try {
      writeManifest(
        outputDir: tmp.path,
        result: result,
        dartSdkCommit: '1aa7d7321fb',
        baselineSha256: 'testhash',
      );
      final m = jsonDecode(
          File('${tmp.path}/manifest.json').readAsStringSync()) as Map;
      final changedFns = m['changed_functions'] as List;
      final ok = m['format_version'] == '1' &&
          m['dart_sdk_commit'] == '1aa7d7321fb' &&
          changedFns.any((s) => s.toString().endsWith('::greet')) &&
          !changedFns.any((s) => s.toString().contains('greetAlt')) &&
          m['class_hierarchy_changed'] == false &&
          File('${tmp.path}/entry_table.bin').existsSync() &&
          File('${tmp.path}/cid_map.bin').existsSync();
      if (ok) {
        _pass('manifest.json: correct format, greet in changed, greetAlt not, files present');
      } else {
        _fail('manifest', 'changed=$changedFns manifest=${m.toString().substring(0, 200)}');
      }
    } finally {
      tmp.deleteSync(recursive: true);
    }
  }

  print('');
  if (exitCode == 0) {
    print('All precision tests passed! (0 false negatives, 0 false positives)');
  } else {
    print('SOME TESTS FAILED');
  }
}
