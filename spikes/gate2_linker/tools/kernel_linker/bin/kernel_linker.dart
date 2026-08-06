import 'dart:convert';
import 'dart:io';
import 'package:kernel/kernel.dart';
import '../lib/kernel_diff.dart';
import '../lib/manifest_output.dart';
import '../lib/pointers_json.dart';

void _usage() {
  stderr.writeln(
      'Usage: kernel_linker --base <base.dill> --patch <patch.dill> '
      '[--json] [--verbose] [--allow-empty] '
      '[--output-dir <dir>] [--baseline-snapshot <path>] [--dart-sdk-commit <hash>] '
      '[--base-snapshot <path>] [--patch-snapshot <path>] '
      '[--analyze-snapshot <path>] [--pointers-json <path>] '
      '[--patch-version <int>] [--release-version <str>]');
  exit(1);
}

void main(List<String> args) {
  String? basePath, patchPath;
  String? outputDir, baselineSnapshot, dartSdkCommit;
  String? baseSnapshotPath, patchSnapshotPath, analyzeSnapshotBin;
  var json = false;
  var verbose = false;
  var allowEmpty = false;
  String? pointersJsonPath;
  int patchVersion = 0;
  String releaseVersion = 'unknown';

  for (var i = 0; i < args.length; i++) {
    switch (args[i]) {
      case '--base':
        basePath = args[++i];
      case '--patch':
        patchPath = args[++i];
      case '--json':
        json = true;
      case '--verbose':
        verbose = true;
      case '--allow-empty':
        allowEmpty = true;
      case '--output-dir':
        outputDir = args[++i];
      case '--baseline-snapshot':
        baselineSnapshot = args[++i];
      case '--dart-sdk-commit':
        dartSdkCommit = args[++i];
      case '--base-snapshot':
        baseSnapshotPath = args[++i];
      case '--patch-snapshot':
        patchSnapshotPath = args[++i];
      case '--analyze-snapshot':
        analyzeSnapshotBin = args[++i];
      case '--pointers-json':
        pointersJsonPath = args[++i];
      case '--patch-version':
        final parsed = int.tryParse(args[++i]);
        if (parsed == null) {
          stderr.writeln('--patch-version must be an integer');
          exit(1);
        }
        patchVersion = parsed;
      case '--release-version':
        releaseVersion = args[++i];
      default:
        stderr.writeln('Unknown flag: ${args[i]}');
        _usage();
    }
  }

  if (basePath == null || patchPath == null) _usage();

  if (!File(basePath!).existsSync()) {
    stderr.writeln('Error: base dill not found: $basePath');
    exit(2);
  }
  if (!File(patchPath!).existsSync()) {
    stderr.writeln('Error: patch dill not found: $patchPath');
    exit(2);
  }

  stderr.writeln('[kernel_linker] Loading $basePath ...');
  final base = loadComponentFromBinary(basePath);
  stderr.writeln('[kernel_linker] Loading $patchPath ...');
  final patch = loadComponentFromBinary(patchPath);

  stderr.writeln('[kernel_linker] Diffing ...');
  final result = diffComponents(base, patch);

  if (result.directlyChanged.isEmpty &&
      result.added.isEmpty &&
      result.removed.isEmpty) {
    if (allowEmpty) {
      stderr.writeln('[kernel_linker] WARNING: No changes detected '
          '(--allow-empty suppressed exit 3).');
    } else {
      stderr.writeln('[kernel_linker] ERROR: No changes detected. '
          'Verify base and patch are different builds, '
          'or pass --allow-empty to suppress this error.');
      exit(3);
    }
  }

  // Write manifest output if requested
  if (outputDir != null) {
    String sha256hex = '';
    if (baselineSnapshot != null && File(baselineSnapshot).existsSync()) {
      final bytes = File(baselineSnapshot).readAsBytesSync();
      sha256hex = _sha256hex(bytes);
    }
    writeManifest(
      outputDir: outputDir,
      result: result,
      dartSdkCommit: dartSdkCommit ?? 'unknown',
      baselineSha256: sha256hex,
      baseSnapshotPath: baseSnapshotPath,
      patchSnapshotPath: patchSnapshotPath,
      analyzeSnapshotBin: analyzeSnapshotBin,
    );
    stderr.writeln('[kernel_linker] Manifest written to $outputDir/');
  }

  if (pointersJsonPath != null) {
    final changedFunctions = [
      ...result.directlyChanged.map((id) => id.toString()),
      ...result.added.map((id) => id.toString()),
    ];
    final pointersData = generatePointersJson(
      changedFunctions: changedFunctions,
      patchVersion: patchVersion,
      releaseVersion: releaseVersion,
    );
    try {
      File(pointersJsonPath!).writeAsStringSync(
        JsonEncoder.withIndent('  ').convert(pointersData));
      stderr.writeln('[kernel_linker] pointers.json written to $pointersJsonPath');
    } catch (e) {
      stderr.writeln('[kernel_linker] ERROR writing pointers.json: $e');
      exit(1);
    }
  }

  if (json) {
    _printJson(result);
  } else {
    _printText(result, verbose: verbose);
  }
}

String _sha256hex(List<int> bytes) {
  // Simple SHA-256 using dart:convert is not available without crypto package.
  // Use a file hash via shasum subprocess as fallback.
  // For now, return empty string if crypto not available.
  // TODO: add package:crypto to pubspec/package_config in Task 2.
  return '';
}

void _printText(DiffResult r, {required bool verbose}) {
  print('=== kernel_linker ===');
  print('Base : ${r.baseCount} procedures');
  print('Patch: ${r.patchCount} procedures');
  print('');

  if (r.added.isNotEmpty) {
    print('ADDED (${r.added.length}):');
    for (final id in r.added) print('  + $id');
  }

  if (r.removed.isNotEmpty) {
    print('REMOVED (${r.removed.length}):');
    for (final id in r.removed) print('  - $id');
  }

  if (r.directlyChanged.isNotEmpty) {
    print('CHANGED (${r.directlyChanged.length}):');
    for (final id in r.directlyChanged) print('  ~ $id');
  }

  if (r.icfAffected.isNotEmpty) {
    print('ICF PEERS (${r.icfAffected.length}) — were identical to a changed function:');
    if (verbose) {
      for (final id in r.icfAffected) print('  = $id');
    } else {
      print('  (use --verbose to list)');
    }
  }

  if (r.transitivelyAffected.isNotEmpty) {
    print('TRANSITIVELY AFFECTED (${r.transitivelyAffected.length}):');
    if (verbose) {
      for (final id in r.transitivelyAffected) print('  > $id');
    } else {
      print('  (use --verbose to list)');
    }
  }

  final ch = r.classHierarchy;
  if (!ch.isEmpty) {
    print('');
    print('CLASS HIERARCHY CHANGES (${ch.totalChanged}) — cid/vtable drift risk:');
    for (final c in ch.addedClasses) print('  +class $c');
    for (final c in ch.removedClasses) print('  -class $c');
    for (final c in ch.hierarchyChanged) print('  ~super $c');
    for (final c in ch.memberLayoutChanged) print('  ~vtable $c');
    print('  NOTE: Any class hierarchy change may shift cid values and '
        'invalidate virtual dispatch. Require full app restart.');
  }

  final total = r.directlyChanged.length +
      r.added.length +
      r.icfAffected.length +
      r.transitivelyAffected.length;
  print('');
  print('Patch set: $total functions');
}

void _printJson(DiffResult r) {
  final ch = r.classHierarchy;
  print(JsonEncoder.withIndent('  ').convert({
    'base_count': r.baseCount,
    'patch_count': r.patchCount,
    'added': r.added.map((i) => i.toString()).toList(),
    'removed': r.removed.map((i) => i.toString()).toList(),
    'changed': r.directlyChanged.map((i) => i.toString()).toList(),
    'icf_affected': r.icfAffected.map((i) => i.toString()).toList(),
    'transitively_affected':
        r.transitivelyAffected.map((i) => i.toString()).toList(),
    'class_hierarchy': {
      'added_classes': ch.addedClasses,
      'removed_classes': ch.removedClasses,
      'hierarchy_changed': ch.hierarchyChanged,
      'member_layout_changed': ch.memberLayoutChanged,
    },
  }));
}
