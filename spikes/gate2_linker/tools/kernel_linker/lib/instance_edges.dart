import 'package:kernel/ast.dart' as k;

// R3 fix: conservative devirtualization tracking.
// AOT CHA can devirtualize an InstanceInvocation into a direct call at
// gen_snapshot time. At the Kernel IR layer we cannot see this decision,
// so we conservatively treat any function that calls method 'bar' via an
// instance call as a potential direct caller of any changed function named
// 'bar'. This may over-report but will never miss a devirtualized callsite.
//
// Returns: methodName → Set<callerBase>
Map<String, Set<String>> buildInstanceReverseEdges(
    Iterable<MapEntry<String, k.Procedure>> callerEntries) {
  final edges = <String, Set<String>>{};
  for (final entry in callerEntries) {
    final callerBase = entry.key;
    for (final name in _collectInstanceCallNames(entry.value)) {
      edges.putIfAbsent(name, () => <String>{}).add(callerBase);
    }
  }
  return edges;
}

Set<String> _collectInstanceCallNames(k.Procedure proc) {
  final collector = _InstanceNameCollector();
  proc.accept(collector);
  return collector.names;
}

class _InstanceNameCollector extends k.RecursiveVisitor {
  final names = <String>{};

  @override
  void visitInstanceInvocation(k.InstanceInvocation node) {
    names.add(node.name.text);
    super.visitInstanceInvocation(node);
  }

  @override
  void visitDynamicInvocation(k.DynamicInvocation node) {
    names.add(node.name.text);
    super.visitDynamicInvocation(node);
  }
}
