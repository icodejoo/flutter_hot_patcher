library;

import 'dart:io';
import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String compute() => 'ORIGINAL';

@pragma('vm:never-inline')
String computeAlt() => 'ALT';  // prevents CHA from specializing closureVar to single target

late final String Function() computeVar;

@pragma('vm:never-inline')
String callCompute() => 'result: ${computeVar()}';

Function? _patchClosure;

@pragma('vm:entry-point')
@pragma('vm:never-inline')
String patchedTrampoline() => internal.invokeDynamicModuleClosure(_patchClosure!) as String;

void main(List<String> args) {
  print('=== e2e hotpatch (V2/closure) ===');
  // Two possible assignments → AOT cannot specialize callCompute to direct call
  computeVar = args.contains('--alt') ? computeAlt : compute;
  print('BEFORE: ${callCompute()}');

  final patchPath = args.where((a) => !a.startsWith('--')).firstOrNull ?? '';
  if (patchPath.isEmpty || !File(patchPath).existsSync()) {
    print('(no patch — running baseline)');
    print('=== done ===');
    return;
  }

  final bytes = File(patchPath).readAsBytesSync();
  final loaded = internal.loadDynamicModuleClosure(bytes: bytes);
  if (loaded == null || loaded is! Function) {
    print('loadDynamicModuleClosure returned: $loaded');
    exit(1);
  }
  _patchClosure = loaded;
  print('patch loaded as closure');

  internal.redirectClosureEntryPoint(computeVar, patchedTrampoline);
  print('V2 redirect applied');

  print('AFTER:  ${callCompute()}');

  final ok = callCompute().contains('PATCHED');
  print(ok ? 'E2E PASS: V2 + bytecode patch working' : 'E2E FAIL');
  exit(ok ? 0 : 1);
}
