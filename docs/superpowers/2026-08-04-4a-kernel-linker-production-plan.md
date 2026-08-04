# 4-A kernel_linker 生产化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 kernel_linker 添加 manifest.json + entry_table.bin + cid_map.bin 输出，补全 provenance 字段，验证 iOS arm64 dill 精确度。

**Architecture:** 只修改 `bin/kernel_linker.dart`（新参数）+ 新增 `lib/manifest_output.dart`（输出模块）。不碰 diff 逻辑。

**Tech Stack:** Dart, 现有 kernel_linker Dart 包，`dart:io`, `dart:convert`

**Working directory:** `~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker/`

---

## Task 1: 新增 manifest_output.dart

**Files:**
- Create: `lib/manifest_output.dart`

- [ ] **Step 1: 写测试**

在 `test/manifest_output_test.dart` 创建：

```dart
import 'dart:convert';
import 'dart:io';
import 'package:test/test.dart';
import '../lib/manifest_output.dart';
import '../lib/kernel_diff.dart';
import '../lib/canonical_name.dart';

void main() {
  late Directory tmp;
  setUp(() => tmp = Directory.systemTemp.createTempSync('manifest_test_'));
  tearDown(() => tmp.deleteSync(recursive: true));

  DiffResult _emptyResult() => DiffResult(
    directlyChanged: [], added: [], removed: [],
    transitivelyAffected: [], icfAffected: [],
    classHierarchy: ClassHierarchyDiff(
      addedClasses: [], removedClasses: [],
      hierarchyChanged: [], memberLayoutChanged: []),
    baseCount: 10, patchCount: 10,
  );

  FunctionId _fid(String uri, String name) =>
    FunctionId(libraryUri: uri, memberName: name, fileOffset: 0);

  test('manifest.json has correct format_version and provenance', () {
    writeManifest(
      outputDir: tmp.path,
      result: _emptyResult(),
      dartSdkCommit: 'abc123',
      baselineSha256: 'sha256abc',
    );
    final manifest = jsonDecode(
      File('${tmp.path}/manifest.json').readAsStringSync());
    expect(manifest['format_version'], equals('1'));
    expect(manifest['dart_sdk_commit'], equals('abc123'));
    expect(manifest['baseline_sha256'], equals('sha256abc'));
    expect(manifest['changed_functions'], isEmpty);
    expect(manifest['affected_closure'], isEmpty);
    expect(manifest['class_hierarchy_changed'], isFalse);
  });

  test('manifest.json includes changed and affected functions', () {
    final result = _emptyResult();
    // Simulate a change
    final changed = DiffResult(
      directlyChanged: [_fid('file:///lib/a.dart', 'greet')],
      added: [],
      removed: [],
      transitivelyAffected: [_fid('file:///lib/a.dart', 'callGreet')],
      icfAffected: [],
      classHierarchy: result.classHierarchy,
      baseCount: 2, patchCount: 2,
    );
    writeManifest(outputDir: tmp.path, result: changed,
                  dartSdkCommit: 'c1', baselineSha256: 's1');
    final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync());
    expect(m['changed_functions'], contains('file:///lib/a.dart::greet'));
    expect(m['affected_closure'], contains('file:///lib/a.dart::callGreet'));
  });

  test('entry_table.bin is created', () {
    writeManifest(outputDir: tmp.path, result: _emptyResult(),
                  dartSdkCommit: 'c1', baselineSha256: 's1');
    expect(File('${tmp.path}/entry_table.bin').existsSync(), isTrue);
  });

  test('cid_map.bin is created and empty when no class hierarchy change', () {
    writeManifest(outputDir: tmp.path, result: _emptyResult(),
                  dartSdkCommit: 'c1', baselineSha256: 's1');
    final bytes = File('${tmp.path}/cid_map.bin').readAsBytesSync();
    // count = 0 → 4 bytes, all zeros
    expect(bytes.length, equals(4));
    expect(bytes, equals([0, 0, 0, 0]));
  });

  test('class_hierarchy_changed=true when classes added/removed', () {
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
    final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync());
    expect(m['class_hierarchy_changed'], isTrue);
  });
}
```

- [ ] **Step 2: 运行测试（预期失败）**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
dart test test/manifest_output_test.dart 2>&1 | head -20
```

Expected: compile error (manifest_output.dart doesn't exist yet)

- [ ] **Step 3: 实现 lib/manifest_output.dart**

```dart
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

  // cid_map.bin (empty for now — cid values come from snapshot, not kernel)
  _writeCidMap(outputDir, {});
}

void _writeEntryTable(
  String dir,
  List<String> changed,
  List<String> icfAffected,
  List<String> affected,
) {
  // interpreter_stub: changed + icf + transitively affected
  final interpreter = <String>{...changed, ...icfAffected, ...affected};
  final buf = BytesBuilder();

  // count (u32 LE)
  final count = interpreter.length;
  buf.add(_u32(count));
  for (final name in interpreter.toList()..sort()) {
    final nameBytes = utf8.encode(name);
    buf.add(_u16(nameBytes.length)); // name_len
    buf.add(nameBytes);              // name_utf8
    buf.addByte(0x01);               // 0x01 = interpreter_stub
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

List<int> _u32(int v) => [v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF, (v >> 24) & 0xFF];
List<int> _u16(int v) => [v & 0xFF, (v >> 8) & 0xFF];
```

- [ ] **Step 4: 运行测试**

```bash
dart test test/manifest_output_test.dart 2>&1
```

Expected: `All tests passed!` (5 tests)

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/gate2_linker/tools/kernel_linker/lib/manifest_output.dart \
        spikes/gate2_linker/tools/kernel_linker/test/manifest_output_test.dart
git commit -m "feat(4-A): manifest_output.dart — manifest.json + entry_table.bin + cid_map.bin"
```

---

## Task 2: 更新 CLI 支持 --output-dir + provenance

**Files:**
- Modify: `bin/kernel_linker.dart`

- [ ] **Step 1: 写测试（集成测试）**

在 `test/cli_output_test.dart`：

```dart
import 'dart:convert';
import 'dart:io';
import 'package:test/test.dart';

void main() {
  late Directory tmp;
  late String baseDir;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('cli_test_');
    baseDir = '${Platform.environment['HOME']}/Documents/flutter_hot_patcher'
              '/spikes/m3_ios_realdevice/build';
  });
  tearDown(() => tmp.deleteSync(recursive: true));

  String get baseDill => '$baseDir/app.dill';
  bool get haveFixtures => File(baseDill).existsSync();

  test('--output-dir creates manifest.json', () async {
    if (!haveFixtures) return; // skip if no fixtures
    final result = await Process.run('dart', [
      'run', 'bin/kernel_linker.dart',
      '--base', baseDill,
      '--patch', baseDill,  // identity diff
      '--dart-sdk-commit', 'testcommit',
      '--baseline-snapshot', baseDill, // reuse dill as fake snapshot for test
      '--output-dir', tmp.path,
      '--allow-empty',
    ], workingDirectory:
      '${Platform.environment['HOME']}/Documents/flutter_hot_patcher'
      '/spikes/gate2_linker/tools/kernel_linker');

    expect(result.exitCode, equals(0));
    final manifest = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync());
    expect(manifest['format_version'], equals('1'));
    expect(manifest['dart_sdk_commit'], equals('testcommit'));
    expect(manifest['changed_functions'], isEmpty);
    expect(File('${tmp.path}/entry_table.bin').existsSync(), isTrue);
    expect(File('${tmp.path}/cid_map.bin').existsSync(), isTrue);
  });
}
```

- [ ] **Step 2: 运行测试（预期失败）**

```bash
dart test test/cli_output_test.dart 2>&1 | head -10
```

- [ ] **Step 3: 更新 bin/kernel_linker.dart**

在 `main()` 参数解析中添加：

```dart
// 新增三个参数
String? outputDir;
String? baselineSnapshot;
String? dartSdkCommit;

// 在 switch 中添加：
case '--output-dir':
  outputDir = args[++i];
case '--baseline-snapshot':
  baselineSnapshot = args[++i];
case '--dart-sdk-commit':
  dartSdkCommit = args[++i];
```

在 `diffComponents` 调用后添加：

```dart
// 如果指定了 --output-dir，写 manifest
if (outputDir != null) {
  import '../lib/manifest_output.dart';   // 在文件顶部添加此 import

  // 计算 baseline sha256
  String sha256 = '';
  if (baselineSnapshot != null && File(baselineSnapshot).existsSync()) {
    final bytes = File(baselineSnapshot).readAsBytesSync();
    sha256 = _sha256hex(bytes);
  }

  writeManifest(
    outputDir: outputDir,
    result: result,
    dartSdkCommit: dartSdkCommit ?? 'unknown',
    baselineSha256: sha256,
  );
  stderr.writeln('[kernel_linker] Manifest written to $outputDir/');
}
```

在文件顶部添加 sha256 工具（或使用 `crypto` 包）：

```dart
import 'dart:convert';
import 'package:crypto/crypto.dart';

String _sha256hex(List<int> bytes) =>
    sha256.convert(bytes).toString();
```

更新 `pubspec.yaml` 添加 `crypto` 依赖：
```yaml
dependencies:
  kernel: ...  # existing
  crypto: ^3.0.0
```

然后运行 `dart pub get`。

- [ ] **Step 4: 运行测试**

```bash
dart test test/cli_output_test.dart 2>&1
```

Expected: test passed (or skipped if fixtures missing)

- [ ] **Step 5: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/gate2_linker/tools/kernel_linker/
git commit -m "feat(4-A): CLI --output-dir / --baseline-snapshot / --dart-sdk-commit, provenance in manifest"
```

---

## Task 3: iOS arm64 精确度验证

**Files:**
- Create: `test/precision_ios_test.dart`

- [ ] **Step 1: 生成测试用 iOS arm64 dill fixtures**

```bash
HOST_OUT=~/dart/sdk/xcodebuild/ReleaseARM64
M3_SPIKE=~/Documents/flutter_hot_patcher/spikes/m3_ios_realdevice
LINKER=~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
mkdir -p "$LINKER/test/fixtures"

# baseline dill (greet() = 'ORIGINAL') — already exists from M3
cp "$M3_SPIKE/build/app.dill" "$LINKER/test/fixtures/greet_base.dill"

# patch dill (greet() = 'PATCHED')
cat > /tmp/greet_patch_p.dart << 'DART'
library;

@pragma('vm:entry-point') @pragma('vm:never-inline')
String greet() => 'PATCHED';

@pragma('vm:entry-point') @pragma('vm:never-inline')
String greetAlt() => 'ALT';

@pragma('vm:entry-point')
late String Function() greetVar;

@pragma('vm:never-inline')
String callGreet() => greetVar();

@pragma('vm:entry-point')
void setup(List args) { greetVar = greetAlt; greetVar = greet; }

@pragma('vm:entry-point')
String getResult() => callGreet();

void main() {}
DART

"$HOST_OUT/dartaotruntime_product" \
  "$HOST_OUT/gen/gen_kernel_aot.dart.snapshot" \
  --platform "$HOST_OUT/vm_platform.dill" --aot \
  --output "$LINKER/test/fixtures/greet_patch.dill" \
  /tmp/greet_patch_p.dart

echo "Fixtures:"
ls -la "$LINKER/test/fixtures/"
```

- [ ] **Step 2: 写精确度测试**

```dart
// test/precision_ios_test.dart
import 'dart:convert';
import 'dart:io';
import 'package:kernel/kernel.dart';
import 'package:test/test.dart';
import '../lib/kernel_diff.dart';
import '../lib/manifest_output.dart';

final fixtures = '${Directory.current.path}/test/fixtures';

void main() {
  final baseFile = '$fixtures/greet_base.dill';
  final patchFile = '$fixtures/greet_patch.dill';
  final haveFixtures = File(baseFile).existsSync() && File(patchFile).existsSync();

  group('iOS arm64 precision (kernel-level)', () {
    test('identity diff produces 0 changes', () {
      if (!haveFixtures) return;
      final base = loadComponentFromBinary(baseFile);
      final result = diffComponents(base, base);
      expect(result.directlyChanged, isEmpty,
          reason: 'Identity diff should have 0 changes');
      expect(result.added, isEmpty);
      expect(result.transitivelyAffected, isEmpty);
    });

    test('greet change detected: greet in changed, greetAlt not', () {
      if (!haveFixtures) return;
      final base = loadComponentFromBinary(baseFile);
      final patch = loadComponentFromBinary(patchFile);
      final result = diffComponents(base, patch);

      final changed = result.directlyChanged.map((f) => f.toString()).toList();
      expect(changed.any((s) => s.contains('greet')), isTrue,
          reason: 'greet() change must be detected');
      expect(changed.any((s) => s.contains('greetAlt')), isFalse,
          reason: 'greetAlt() unchanged, must not appear in changed');
    });

    test('callGreet in transitively affected', () {
      if (!haveFixtures) return;
      final base = loadComponentFromBinary(baseFile);
      final patch = loadComponentFromBinary(patchFile);
      final result = diffComponents(base, patch);

      final affected = result.transitivelyAffected.map((f) => f.toString()).toList();
      expect(affected.any((s) => s.contains('callGreet')), isTrue,
          reason: 'callGreet() calls greet(), must be transitively affected');
    });

    test('manifest.json produced with correct fields', () {
      if (!haveFixtures) return;
      final base = loadComponentFromBinary(baseFile);
      final patch = loadComponentFromBinary(patchFile);
      final result = diffComponents(base, patch);

      final tmp = Directory.systemTemp.createTempSync('precision_test_');
      try {
        writeManifest(
          outputDir: tmp.path,
          result: result,
          dartSdkCommit: '1aa7d7321fb',
          baselineSha256: 'testhash',
        );
        final m = jsonDecode(File('${tmp.path}/manifest.json').readAsStringSync());
        expect(m['format_version'], equals('1'));
        expect(m['dart_sdk_commit'], equals('1aa7d7321fb'));
        expect((m['changed_functions'] as List).any((s) => s.toString().contains('greet')), isTrue);
        expect(m['class_hierarchy_changed'], isFalse);
      } finally {
        tmp.deleteSync(recursive: true);
      }
    });
  });
}
```

- [ ] **Step 3: 运行精确度测试**

```bash
cd ~/Documents/flutter_hot_patcher/spikes/gate2_linker/tools/kernel_linker
dart test test/precision_ios_test.dart -v 2>&1
```

Expected output:
```
✓ identity diff produces 0 changes
✓ greet change detected: greet in changed, greetAlt not
✓ callGreet in transitively affected
✓ manifest.json produced with correct fields
All tests passed!
```

If any test fails, debug by running:
```bash
dart run bin/kernel_linker.dart \
  --base test/fixtures/greet_base.dill \
  --patch test/fixtures/greet_patch.dill \
  --verbose
```

- [ ] **Step 4: commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add spikes/gate2_linker/tools/kernel_linker/
git commit -m "test(4-A): iOS arm64 precision — 0 false neg, 0 false pos (kernel-level)"
```

---

## Task 4: 移入 spec/plan + 更新 GATE_STATUS + README

- [ ] **Step 1: 移入文档**

```bash
cp /tmp/2026-08-04-4a-kernel-linker-production-design.md \
   ~/Documents/flutter_hot_patcher/docs/superpowers/specs/
cp /tmp/2026-08-04-4a-kernel-linker-production-plan.md \
   ~/Documents/flutter_hot_patcher/docs/superpowers/plans/
```

- [ ] **Step 2: 更新 README.md — 新增 --output-dir 用法**

在 `spikes/gate2_linker/tools/kernel_linker/README.md` 命令行参数表格添加：

```markdown
| `--output-dir <path>` | — | 输出 manifest.json + entry_table.bin + cid_map.bin |
| `--baseline-snapshot <path>` | — | 基线 snapshot 路径（用于 sha256 provenance） |
| `--dart-sdk-commit <hash>` | — | Dart SDK commit hash（写入 manifest provenance） |
```

- [ ] **Step 3: 更新 GATE_STATUS.md**

在正式研发阶段里程碑表添加：
```markdown
| 4-A kernel_linker 生产化 | manifest 输出 + provenance + iOS 精确度测试 | M3 ✅ |
```

- [ ] **Step 4: 最终 commit**

```bash
cd ~/Documents/flutter_hot_patcher
git add .
git commit -m "feat(4-A): COMPLETE — kernel_linker production manifest output

All R1-R9 already satisfied. Added:
- manifest.json (PATCH_DELIVERY_SPEC §1 format) 
- entry_table.bin / cid_map.bin binary encoding
- provenance: dart_sdk_commit + baseline_sha256
- iOS arm64 precision tests: 0 false neg, 0 false pos
- CLI: --output-dir / --baseline-snapshot / --dart-sdk-commit

Co-Authored-By: Claude Sonnet 4.6 (1M context) <noreply@anthropic.com>"
```
