/// Simple test script — no package:test needed, uses assert + print.
/// Run: dart --packages=.dart_tool/package_config.json test/pointers_json_test.dart
import 'dart:io';
import '../lib/pointers_json.dart';

void _pass(String name) => print('  PASS: $name');
void _fail(String name, String msg) {
  print('  FAIL: $name — $msg');
  exitCode = 1;
}

void main() {
  print('=== pointers_json tests ===');

  // Test 1: basic structure
  {
    const name = 'generatePointersJson produces valid JSON with correct structure';
    final changed = [
      'file:///lib/main.dart::MyClass::greet',
      'file:///lib/main.dart::MyClass::farewell',
    ];
    final result = generatePointersJson(
      changedFunctions: changed,
      patchVersion: 7,
      releaseVersion: '1.0+1',
    );
    if (result['patch_version'] != 7) {
      _fail(name, 'expected patch_version=7, got ${result["patch_version"]}');
    } else if (result['release_version'] != '1.0+1') {
      _fail(name, 'expected release_version=1.0+1');
    } else {
      final fns = result['functions'] as List;
      if (fns.length != 2) {
        _fail(name, 'expected 2 functions, got ${fns.length}');
      } else if ((fns[0] as Map)['canonical_name'] != 'file:///lib/main.dart::MyClass::greet') {
        _fail(name, 'wrong canonical_name at index 0');
      } else if ((fns[0] as Map)['patch_index'] != 0) {
        _fail(name, 'expected patch_index=0');
      } else if ((fns[1] as Map)['patch_index'] != 1) {
        _fail(name, 'expected patch_index=1');
      } else {
        _pass(name);
      }
    }
  }

  // Test 2: empty list
  {
    const name = 'generatePointersJson with empty list';
    final result = generatePointersJson(
      changedFunctions: [],
      patchVersion: 1,
      releaseVersion: '2.0+0',
    );
    final fns = result['functions'] as List;
    if (fns.isEmpty) {
      _pass(name);
    } else {
      _fail(name, 'expected empty functions list');
    }
  }

  if (exitCode == 0) print('All tests passed!');
}
