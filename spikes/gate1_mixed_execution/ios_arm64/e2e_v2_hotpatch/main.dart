library;

import 'dart:_internal' as internal;

@pragma('vm:never-inline')
String originalImpl() => 'ORIGINAL';

@pragma('vm:never-inline')
String altImpl() => 'ALT';

@pragma('vm:never-inline')
String patchedImpl() => 'PATCHED-iOS-HOTFIX';

late String Function() fn;

@pragma('vm:never-inline')
String callViaFn() => 'via-closure: ${fn()}';

void main(List args) {
  fn = args.contains('--alt') ? altImpl : originalImpl;

  print('BEFORE: ${callViaFn()}');

  if (args.contains('--patch')) {
    internal.redirectClosureEntryPoint(fn, patchedImpl);
    print('AFTER:  ${callViaFn()}');
    if (callViaFn().contains('PATCHED-iOS-HOTFIX')) {
      print('V2-closure iOS PASS');
      return;
    }
    print('V2-closure iOS FAIL');
    return;
  }

  print('(baseline only)');
}
