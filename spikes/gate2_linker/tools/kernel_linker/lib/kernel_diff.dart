import 'package:kernel/ast.dart' as k;
import 'package:kernel/text/ast_to_text.dart';
import 'canonical_name.dart';
import 'class_hierarchy.dart';
import 'icf_groups.dart';
import 'instance_edges.dart';

class ProcedureInfo {
  final FunctionId id;
  final k.Procedure proc;
  final String bodyFingerprint;

  ProcedureInfo(this.id, this.proc, this.bodyFingerprint);
}

class DiffResult {
  final List<FunctionId> directlyChanged;
  final List<FunctionId> added;
  final List<FunctionId> removed;
  final List<FunctionId> transitivelyAffected;

  /// R4: functions that were ICF peers of a changed function in the base build.
  final List<FunctionId> icfAffected;

  /// R5: class hierarchy / vtable layout changes.
  final ClassHierarchyDiff classHierarchy;

  final int baseCount;
  final int patchCount;

  DiffResult({
    required this.directlyChanged,
    required this.added,
    required this.removed,
    required this.transitivelyAffected,
    required this.icfAffected,
    required this.classHierarchy,
    required this.baseCount,
    required this.patchCount,
  });
}

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
    final FunctionId key;
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
    map[key] = ProcedureInfo(key, proc, _fingerprint(proc, proc.enclosingLibrary));
  }
  return map;
}

Set<String> _staticCallees(k.Procedure proc) {
  final targets = <String>{};
  proc.accept(_StaticCalleeCollector(targets));
  return targets;
}

class _StaticCalleeCollector extends k.RecursiveVisitor {
  final Set<String> targets;
  _StaticCalleeCollector(this.targets);

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

DiffResult diffComponents(k.Component base, k.Component patch) {
  final baseIdx = _index(base);
  final patchIdx = _index(patch);

  // ── 1. Compute directly changed / added / removed ────────────────────────
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

  // ── 2. R4: ICF peer expansion ────────────────────────────────────────────
  final baseFingerprints = {
    for (final e in baseIdx.entries) e.key: e.value.bodyFingerprint
  };
  final baseFpGroups = buildFingerprintGroups(baseFingerprints);
  final peers = icfPeers(baseFpGroups, baseFingerprints, changed);
  // Track ICF-affected separately so callers can inspect them.
  // They also seed the BFS so their callers are found.
  final icfAffected = peers.toList();

  // ── 3. Build reverse call graphs ─────────────────────────────────────────
  final staticRev = <String, Set<String>>{};    // callee.base → caller.base
  final instanceRev = <String, Set<String>>{};  // methodName  → caller.base (R3 fix)
  final baseToFid = <String, FunctionId>{};

  for (final info in patchIdx.values) {
    baseToFid[info.id.base] = info.id;
    for (final callee in _staticCallees(info.proc)) {
      staticRev.putIfAbsent(callee, () => <String>{}).add(info.id.base);
    }
  }
  // R3 fix: build instance-call reverse edges
  final instanceEntries = patchIdx.values
      .map((info) => MapEntry(info.id.base, info.proc));
  final instanceEdges = buildInstanceReverseEdges(instanceEntries);
  for (final e in instanceEdges.entries) {
    instanceRev[e.key] = e.value;
  }

  // ── 4. BFS: propagate from {changed ∪ added ∪ icfPeers} ─────────────────
  final directBases = <String>{
    for (final id in [...changed, ...added, ...peers]) id.base
  };
  final visited = <String>{...directBases};
  final queue = List<String>.from(directBases);
  final transitively = <FunctionId>[];

  while (queue.isNotEmpty) {
    final cur = queue.removeLast();

    // Static callers
    for (final caller in staticRev[cur] ?? const <String>{}) {
      if (visited.add(caller)) {
        queue.add(caller);
        if (!directBases.contains(caller)) {
          transitively.add(_resolveFid(caller, patchIdx, baseToFid));
        }
      }
    }

    // R3 fix: instance callers (conservative devirtualization)
    final memberName = _memberName(cur, baseToFid);
    for (final caller in instanceRev[memberName] ?? const <String>{}) {
      if (visited.add(caller)) {
        queue.add(caller);
        if (!directBases.contains(caller)) {
          transitively.add(_resolveFid(caller, patchIdx, baseToFid));
        }
      }
    }
  }

  // ── 5. R5: class hierarchy diff ──────────────────────────────────────────
  final classHierarchy = diffClassHierarchy(base, patch);

  return DiffResult(
    directlyChanged: changed,
    added: added,
    removed: removed,
    transitivelyAffected: transitively,
    icfAffected: icfAffected,
    classHierarchy: classHierarchy,
    baseCount: baseIdx.length,
    patchCount: patchIdx.length,
  );
}

// ─── helpers ─────────────────────────────────────────────────────────────────

String _memberName(String base, Map<String, FunctionId> baseToFid) {
  final fid = baseToFid[base];
  if (fid != null) return fid.memberName;
  // Fallback: parse 'pkg::ClassName.methodName' or 'pkg::methodName'
  final afterColons = base.contains('::') ? base.split('::').last : base;
  return afterColons.contains('.') ? afterColons.split('.').last : afterColons;
}

FunctionId _resolveFid(
  String callerBase,
  Map<FunctionId, ProcedureInfo> patchIdx,
  Map<String, FunctionId> baseToFid,
) {
  final fid = baseToFid[callerBase];
  if (fid != null) return fid;
  return FunctionId(libraryUri: '', memberName: callerBase, fileOffset: -1);
}
