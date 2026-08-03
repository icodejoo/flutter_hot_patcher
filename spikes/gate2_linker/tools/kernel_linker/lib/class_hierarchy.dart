import 'package:kernel/ast.dart' as k;
import 'canonical_name.dart';

// R5: Class hierarchy / cid-layout change detection.
// Adding/removing classes or changing inheritance shifts cid values,
// which can silently break virtual dispatch even when no method body changed.
// This does NOT directly fix cid drift; it surfaces the risk so the caller
// can decide (e.g. require a full app restart for any class layout change).

class ClassHierarchyDiff {
  /// Classes present in patch but not in base.
  final List<String> addedClasses;

  /// Classes present in base but not in patch.
  final List<String> removedClasses;

  /// Classes whose superclass or mixin list changed.
  final List<String> hierarchyChanged;

  /// Classes whose virtual member list (name+order) changed without a
  /// superclass change — affects vtable/dispatch-table slot assignment.
  final List<String> memberLayoutChanged;

  ClassHierarchyDiff({
    required this.addedClasses,
    required this.removedClasses,
    required this.hierarchyChanged,
    required this.memberLayoutChanged,
  });

  bool get isEmpty =>
      addedClasses.isEmpty &&
      removedClasses.isEmpty &&
      hierarchyChanged.isEmpty &&
      memberLayoutChanged.isEmpty;

  int get totalChanged =>
      addedClasses.length +
      removedClasses.length +
      hierarchyChanged.length +
      memberLayoutChanged.length;
}

ClassHierarchyDiff diffClassHierarchy(
    k.Component base, k.Component patch) {
  final baseClasses = _buildClassMap(base);
  final patchClasses = _buildClassMap(patch);

  final added = <String>[];
  final removed = <String>[];
  final hierarchyChanged = <String>[];
  final memberLayoutChanged = <String>[];

  for (final entry in patchClasses.entries) {
    final key = entry.key;
    final pc = entry.value;
    final bc = baseClasses[key];
    if (bc == null) {
      added.add(key);
      continue;
    }
    if (bc.superName != pc.superName ||
        !_listEq(bc.mixinNames, pc.mixinNames)) {
      hierarchyChanged.add(key);
    } else if (!_listEq(bc.virtualMembers, pc.virtualMembers)) {
      memberLayoutChanged.add(key);
    }
  }

  for (final key in baseClasses.keys) {
    if (!patchClasses.containsKey(key)) removed.add(key);
  }

  return ClassHierarchyDiff(
    addedClasses: added,
    removedClasses: removed,
    hierarchyChanged: hierarchyChanged,
    memberLayoutChanged: memberLayoutChanged,
  );
}

// ─── internal ────────────────────────────────────────────────────────────────

class _ClassSnapshot {
  final String? superName;
  final List<String> mixinNames;
  final List<String> virtualMembers; // override-able procedure names, in order
  _ClassSnapshot(this.superName, this.mixinNames, this.virtualMembers);
}

Map<String, _ClassSnapshot> _buildClassMap(k.Component component) {
  final map = <String, _ClassSnapshot>{};
  for (final lib in component.libraries) {
    if (!isUserLibrary(lib)) continue;
    for (final cls in lib.classes) {
      final key = '${lib.importUri}::${cls.name}';
      final superName = cls.supertype?.classNode.name;
      final mixinNames =
          [if (cls.mixedInType != null) cls.mixedInType!.classNode.name];
      // Virtual members: procedures that can be overridden (not static, not abstract stubs)
      final virtualMembers = cls.procedures
          .where((p) => !p.isStatic && p.kind == k.ProcedureKind.Method)
          .map((p) => p.name.text)
          .toList();
      map[key] = _ClassSnapshot(superName, mixinNames, virtualMembers);
    }
  }
  return map;
}

bool _listEq(List<String> a, List<String> b) {
  if (a.length != b.length) return false;
  for (var i = 0; i < a.length; i++) {
    if (a[i] != b[i]) return false;
  }
  return true;
}
