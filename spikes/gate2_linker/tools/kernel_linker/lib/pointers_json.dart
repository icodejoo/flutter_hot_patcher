// spikes/gate2_linker/tools/kernel_linker/lib/pointers_json.dart

Map<String, dynamic> generatePointersJson({
  required List<String> changedFunctions,
  required int patchVersion,
  required String releaseVersion,
}) {
  final functions = <Map<String, dynamic>>[];
  for (var i = 0; i < changedFunctions.length; i++) {
    functions.add({
      'canonical_name': changedFunctions[i],
      'patch_index': i,
    });
  }
  return {
    'patch_version': patchVersion,
    'release_version': releaseVersion,
    'functions': functions,
  };
}
