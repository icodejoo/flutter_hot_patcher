import 'dart:convert';
import 'dart:io';
import 'package:kernel/kernel.dart';
import '../lib/kernel_diff.dart';

void _usage() {
  stderr.writeln(
      'Usage: kernel_linker --base <base.dill> --patch <patch.dill> [--json] [--verbose] [--allow-empty]');
  exit(1);
}

void main(List<String> args) {
  String? basePath, patchPath;
  var json = false;
  var verbose = false;
  var allowEmpty = false;

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

  // R8: never silently succeed — zero changes is almost certainly a bug
  // (same dill passed twice, wrong paths, build cache not invalidated).
  if (result.directlyChanged.isEmpty &&
      result.added.isEmpty &&
      result.removed.isEmpty) {
    if (allowEmpty) {
      stderr.writeln('[kernel_linker] WARNING: No changes detected '
          '(--allow-empty suppressed exit 3). '
          'Verify that base and patch are different builds.');
    } else {
      stderr.writeln('[kernel_linker] ERROR: No changes detected. '
          'Verify base and patch are different builds, '
          'or pass --allow-empty to suppress this error.');
      exit(3);
    }
  }

  if (json) {
    _printJson(result);
  } else {
    _printText(result, verbose: verbose);
  }
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

  // R5: class hierarchy warnings
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
