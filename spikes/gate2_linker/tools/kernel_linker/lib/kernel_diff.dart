import 'package:kernel/ast.dart' as k;
import 'package:kernel/text/ast_to_text.dart';
import 'canonical_name.dart';

class ProcedureInfo {
  final FunctionId id;
  final k.Procedure proc;
  final String bodyFingerprint;

  ProcedureInfo(this.id, this.proc, this.bodyFingerprint);
}

class DiffResult {
  /// Procedures whose body changed between base and patch.
  final List<FunctionId> directlyChanged;

  /// Procedures added in patch (not in base).
  final List<FunctionId> added;

  /// Procedures removed from patch (in base, not in patch).
  final List<FunctionId> removed;

  /// Callers of changed/added functions that are themselves unchanged
  /// but need re-linking.
  final List<FunctionId> transitivelyAffected;

  final int baseCount;
  final int patchCount;

  DiffResult({
    required this.directlyChanged,
    required this.added,
    required this.removed,
    required this.transitivelyAffected,
    required this.baseCount,
    required this.patchCount,
  });
}

/// Compute a normalized text fingerprint of a procedure's body.
/// File positions (@NN) are stripped so logically identical code
/// at different source locations compares as equal.
String _fingerprint(k.Procedure proc, k.Library lib) {
  final buf = StringBuffer();
  final printer = Printer(buf, showOffsets: false);
  printer.writeProcedureInLibrary(proc, lib);
  return buf
      .toString()
      .replaceAll(RegExp(r'@\d+'), '')
      .replaceAll(RegExp(r'[ \t]+\n'), '\n')
      .trim();
}

/// Build id → ProcedureInfo index for a component.
Map<FunctionId, ProcedureInfo> _index(k.Component component) {
  final procs = extractUserProcedures(component);
  final nameCounts = <String, int>{};
  for (final proc in procs) {
    final base = functionIdForProcedure(proc).base;
    nameCounts[base] = (nameCounts[base] ?? 0) + 1;
  }

  final map = <FunctionId, ProcedureInfo>{};
  for (final proc in procs) {
    final fid = functionIdForProcedure(proc);
    FunctionId key;
    if ((nameCounts[fid.base] ?? 0) > 1) {
      key = FunctionId(
        libraryUri: fid.libraryUri,
        className: fid.className,
        memberName: '${fid.memberName}@${fid.fileOffset}',
        fileOffset: fid.fileOffset,
      );
    } else {
      key = fid;
    }
    final fp = _fingerprint(proc, proc.enclosingLibrary);
    map[key] = ProcedureInfo(key, proc, fp);
  }
  return map;
}

/// Collect static call targets from a procedure body (R3: partial, static edges).
Set<String> _staticCallees(k.Procedure proc) {
  final targets = <String>{};
  proc.accept(_CalleeCollector(targets));
  return targets;
}

class _CalleeCollector extends k.RecursiveVisitor {
  final Set<String> targets;
  _CalleeCollector(this.targets);

  @override
  void visitStaticInvocation(k.StaticInvocation node) {
    final target = node.target;
    final lib = target.enclosingLibrary;
    if (isUserLibrary(lib)) {
      targets.add(functionIdForProcedure(target).base);
    }
    super.visitStaticInvocation(node);
  }
}

/// Diff two components and propagate changes through the static call graph.
DiffResult diffComponents(k.Component base, k.Component patch) {
  final baseIdx = _index(base);
  final patchIdx = _index(patch);

  final added = <FunctionId>[];
  final removed = <FunctionId>[];
  final changed = <FunctionId>[];

  for (final entry in patchIdx.entries) {
    final baseInfo = baseIdx[entry.key];
    if (baseInfo == null) {
      added.add(entry.key);
    } else if (baseInfo.bodyFingerprint != entry.value.bodyFingerprint) {
      changed.add(entry.key);
    }
  }

  for (final key in baseIdx.keys) {
    if (!patchIdx.containsKey(key)) removed.add(key);
  }

  // Build reverse call graph from the patch component.
  final reverseEdges = <String, Set<String>>{};
  for (final info in patchIdx.values) {
    for (final callee in _staticCallees(info.proc)) {
      reverseEdges.putIfAbsent(callee, () => <String>{}).add(info.id.base);
    }
  }

  // BFS propagation from directly changed / added.
  final directBases = {for (final id in [...changed, ...added]) id.base};
  final visited = <String>{...directBases};
  final queue = List<String>.from(directBases);
  final transitively = <FunctionId>[];

  while (queue.isNotEmpty) {
    final cur = queue.removeLast();
    for (final caller in reverseEdges[cur] ?? const <String>{}) {
      if (visited.add(caller)) {
        queue.add(caller);
        if (!directBases.contains(caller)) {
          final fid = patchIdx.keys.firstWhere(
            (k) => k.base == caller,
            orElse: () =>
                FunctionId(libraryUri: '', memberName: caller, fileOffset: -1),
          );
          transitively.add(fid);
        }
      }
    }
  }

  return DiffResult(
    directlyChanged: changed,
    added: added,
    removed: removed,
    transitivelyAffected: transitively,
    baseCount: baseIdx.length,
    patchCount: patchIdx.length,
  );
}
