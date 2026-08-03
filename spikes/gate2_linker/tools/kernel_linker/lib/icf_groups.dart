import 'canonical_name.dart';

// R4: ICF (Identical Code Folding) awareness.
// gen_snapshot's DedupInstructions folds functions with identical native code.
// At the Kernel IR layer we cannot see AOT folding decisions, so we
// conservatively treat any two functions with identical body fingerprints as
// potential ICF peers: if A changes, its former peers are also affected.

// fingerprint → List<FunctionId>
Map<String, List<FunctionId>> buildFingerprintGroups(
    Map<FunctionId, String> fingerprints) {
  final groups = <String, List<FunctionId>>{};
  for (final entry in fingerprints.entries) {
    groups.putIfAbsent(entry.value, () => []).add(entry.key);
  }
  return groups;
}

// Returns the ICF peers of [changed] functions in the base component.
// A peer is any function that shared the SAME fingerprint as a changed
// function BEFORE the change (i.e. was an ICF candidate with it).
Set<FunctionId> icfPeers(
  Map<String, List<FunctionId>> baseFpGroups,
  Map<FunctionId, String> baseFingerprints,
  Iterable<FunctionId> changed,
) {
  final peers = <FunctionId>{};
  for (final id in changed) {
    final oldFp = baseFingerprints[id];
    if (oldFp == null) continue; // newly added function — no pre-existing group
    for (final peer in baseFpGroups[oldFp] ?? const <FunctionId>[]) {
      if (peer != id) peers.add(peer);
    }
  }
  return peers;
}
