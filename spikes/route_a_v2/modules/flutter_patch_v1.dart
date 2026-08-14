import 'package:route_a_flutter/patchable.dart' as patchable;

@pragma('dyn-module:entry-point')
void patchEntry() {
  patchable.impl = () => 'PATCHED_V1';
}
