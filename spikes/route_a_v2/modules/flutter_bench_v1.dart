import 'package:route_a_flutter/hot.dart' as hot;
import 'package:route_a_flutter/patchable.dart' as patchable;

/// Rebinds the hot loop to a body that lives in this module, i.e. one the KBC
/// interpreter executes. The loop is byte-for-byte the same work as
/// hot.hotLoopNative.
@pragma('dyn-module:entry-point')
void patchEntry() {
  patchable.impl = () => 'PATCHED_V1';
  hot.hotLoop = () {
    int sum = 0;
    for (int i = 0; i < 10000; i++) {
      sum += i;
    }
    return sum;
  };
}
