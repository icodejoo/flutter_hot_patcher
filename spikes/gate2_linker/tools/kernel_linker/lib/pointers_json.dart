// spikes/gate2_linker/tools/kernel_linker/lib/pointers_json.dart

Map<String, dynamic> generatePointersJson({
  required List<String> changedFunctions,
  required int patchVersion,
  required String releaseVersion,
}) {
  final functions = <Map<String, dynamic>>[];
  for (final entry in changedFunctions.asMap().entries) {
    functions.add({
      'canonical_name': entry.value,
      'patch_index': entry.key,
    });
  }
  return {
    'patch_version': patchVersion,
    'release_version': releaseVersion,
    'functions': functions,
  };
}
